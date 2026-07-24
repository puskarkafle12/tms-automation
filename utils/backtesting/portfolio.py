"""Deterministic shared-capital replay over persisted stock-level trades."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List

from sqlalchemy import text

from utils.backtesting.nepse_charges import buy_charges, maximum_affordable_quantity, sell_charges


def build_portfolios_for_run(session, run_id: str, configuration: Dict[str, Any]) -> None:
    allocation = {
        "max_stock_pct": 10.0, "max_sector_pct": 30.0, "max_positions": 10,
        "cash_reserve_pct": 5.0, "max_volume_participation_pct": 10.0,
        "charge_model": configuration.get("charge_model") or "nepse_equity",
        "investor_type": configuration.get("investor_type") or "individual",
        "apply_cgt": configuration.get("apply_cgt", True),
        "dp_charge": configuration.get("dp_charge", 25),
        "fee_pct": configuration.get("fee_pct", .4),
        "fixed_fee": configuration.get("fixed_fee", 0),
        **(configuration.get("portfolio") or {}),
    }
    initial = float(configuration.get("initial_capital") or 100000)
    presets = session.execute(text(
        """SELECT DISTINCT preset_id,preset_name FROM backtest_results
           WHERE run_id=:run_id
             AND ((total_trades>=16 AND win_rate_pct>=50)
                  OR (total_trades>=9 AND win_rate_pct>=60))
           ORDER BY preset_id"""
    ), {"run_id": run_id}).mappings().all()
    session.execute(text("DELETE FROM backtest_portfolio_results WHERE run_id=:run_id"), {"run_id": run_id})
    for preset in presets:
        trades = [dict(row) for row in session.execute(text(
            """SELECT t.*,r.symbol,r.robust_score,COALESCE(s.sector,'Unknown') AS sector,s.latest_volume
               FROM backtest_trades t JOIN backtest_results r ON r.result_id=t.result_id
               JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol
               WHERE r.run_id=:run_id AND r.preset_id=:preset_id
                 AND ((r.total_trades>=16 AND r.win_rate_pct>=50)
                      OR (r.total_trades>=9 AND r.win_rate_pct>=60))
               ORDER BY t.entry_date,r.robust_score DESC,r.symbol,t.sequence_no"""
        ), {"run_id": run_id, "preset_id": preset["preset_id"]}).mappings().all()]
        summary, curve = replay_shared_capital(trades, initial, allocation)
        session.execute(text(
            """INSERT INTO backtest_portfolio_results
               (run_id,preset_id,preset_name,summary,equity_curve,allocation_config)
               VALUES (:run_id,:preset_id,:preset_name,CAST(:summary AS JSONB),CAST(:curve AS JSONB),CAST(:allocation AS JSONB))"""
        ), {"run_id": run_id, "preset_id": preset["preset_id"], "preset_name": preset["preset_name"],
            "summary": json.dumps(summary), "curve": json.dumps(curve), "allocation": json.dumps(allocation)})


def replay_shared_capital(trades: List[Dict[str, Any]], initial: float, allocation: Dict[str, Any]) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    def as_date(value: Any) -> date:
        return value if isinstance(value, date) else date.fromisoformat(str(value))

    charge_options = {
        "charge_model": allocation.get("charge_model") or "nepse_equity",
        "fee_pct": float(allocation.get("fee_pct", .4)),
        "fixed_fee": float(allocation.get("fixed_fee", 0)),
    }
    cash = initial
    positions: Dict[str, Dict[str, Any]] = {}
    sector_cost: Dict[str, float] = defaultdict(float)
    exits: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    entries: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        entries[trade["entry_date"]].append(trade)
        exits[trade["exit_date"]].append(trade)
    dates = sorted(set(entries) | set(exits))
    accepted = rejected = fees = wins = 0
    taxes = broker_total = sebon_total = dp_total = 0.0
    realized_pnl = 0.0
    peak = initial
    max_drawdown = 0.0
    curve: List[Dict[str, Any]] = []
    for session_date in dates:
        for source in exits[session_date]:
            position = positions.pop(source["symbol"], None)
            if not position:
                continue
            gross = position["quantity"] * float(source["exit_price"])
            exit_charges = sell_charges(
                gross, as_date(session_date), entry_total_cost=position["entry_total"],
                holding_days=int(source.get("holding_days") or (as_date(source["exit_date"]) - as_date(source["entry_date"])).days),
                investor_type=str(allocation.get("investor_type") or "individual"),
                apply_cgt=bool(allocation.get("apply_cgt", True)),
                dp_charge=float(allocation.get("dp_charge", 25)), **charge_options,
            )
            exit_fee = exit_charges["total"]
            cash += gross - exit_fee
            pnl = gross - exit_fee - position["entry_total"]
            realized_pnl += pnl
            taxes += exit_charges["capital_gains_tax"]
            fees += position["entry_fee"] + exit_fee - exit_charges["capital_gains_tax"]
            broker_total += position["entry_charges"]["broker_commission"] + exit_charges["broker_commission"]
            sebon_total += position["entry_charges"]["sebon_fee"] + exit_charges["sebon_fee"]
            dp_total += exit_charges["dp_charge"]
            wins += int(pnl > 0)
            sector_cost[position["sector"]] -= position["cost"]
        for source in entries[session_date]:
            symbol = source["symbol"]
            sector = source["sector"]
            if symbol in positions or len(positions) >= int(allocation["max_positions"]):
                rejected += 1
                continue
            reserve = initial * float(allocation["cash_reserve_pct"]) / 100
            stock_cap = initial * float(allocation["max_stock_pct"]) / 100
            sector_room = initial * float(allocation["max_sector_pct"]) / 100 - sector_cost[sector]
            available = min(stock_cap, sector_room, max(0.0, cash - reserve))
            entry_price = float(source["entry_price"])
            quantity = maximum_affordable_quantity(available, entry_price, as_date(session_date), **charge_options)
            latest_volume = float(source.get("latest_volume") or 0)
            if latest_volume > 0:
                quantity = min(quantity, int(latest_volume * float(allocation["max_volume_participation_pct"]) / 100))
            if quantity <= 0:
                rejected += 1
                continue
            cost = entry_price * quantity
            entry_charges = buy_charges(cost, as_date(session_date), **charge_options)
            entry_fee = entry_charges["total"]
            if cost + entry_fee > cash - reserve:
                rejected += 1
                continue
            cash -= cost + entry_fee
            sector_cost[sector] += cost
            positions[symbol] = {"quantity": quantity, "entry_price": entry_price, "entry_fee": entry_fee,
                                 "entry_total": cost + entry_fee, "entry_charges": entry_charges,
                                 "cost": cost, "sector": sector}
            accepted += 1
        equity = cash + sum(item["cost"] for item in positions.values())
        peak = max(peak, equity)
        drawdown = 100 * (peak - equity) / peak if peak else 0
        max_drawdown = max(max_drawdown, drawdown)
        curve.append({"date": session_date.isoformat(), "equity": round(equity, 2), "cash": round(cash, 2), "positions": len(positions), "drawdown_pct": round(drawdown, 4)})
    final_equity = cash + sum(item["cost"] for item in positions.values())
    return {
        "initial_capital": round(initial, 2), "final_equity": round(final_equity, 2),
        "net_return_pct": round((final_equity / initial - 1) * 100, 4) if initial else 0,
        "realized_pnl": round(realized_pnl, 2), "max_drawdown_pct": round(max_drawdown, 4),
        "accepted_signals": accepted, "rejected_signals": rejected, "winning_trades": wins,
        "fees": round(fees, 2), "taxes": round(taxes, 2),
        "total_charges": round(fees + taxes, 2),
        "broker_commission": round(broker_total, 2), "sebon_fees": round(sebon_total, 2),
        "dp_charges": round(dp_total, 2), "open_positions_at_end": len(positions),
    }, curve
