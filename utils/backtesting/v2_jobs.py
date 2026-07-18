"""PostgreSQL-leased v2 backtest worker and normalized result persistence."""

from __future__ import annotations

import json
import hashlib
import multiprocessing
import os
import socket
import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text

from utils.backtesting.batch import (
    _run_symbol_task, background_worker_limit, get_backtest_universe,
    initialize_background_worker,
)
from utils.backtesting.jobs import _symbol_metadata
from utils.backtesting.presets import get_backtest_presets
from utils.backtesting.professional import ROBUST_SCORE_VERSION, assign_robust_scores
from utils.technical_indicators import ENGINE_VERSION
from utils.strategy_builder.strategy_parser import (
    StrategyQueryError,
    format_expression,
    format_strategy_query,
    parse_strategy_query,
)


BACKTEST_ENGINE_VERSION = "nepse-daily-v2"
_WORKER_LOCK = threading.Lock()
_WORKER_STARTED = False
_WORKER_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
NEPAL_TZ = ZoneInfo("Asia/Kathmandu")
DAILY_REFRESH_HOURS = (10, 11)
_LAST_DAILY_REFRESH_SLOT: Optional[str] = None


def _scan_key(config: Dict[str, Any], universe: List[str], selected: List[Dict[str, Any]]) -> str:
    """Stable identity for a continuing scan; its end date and display name may advance."""
    requested_symbols = sorted({str(item).strip().upper() for item in (config.get("symbols") or []) if str(item).strip()})
    identity = {
        "run_type": config.get("run_type") or "market_scan",
        "history_mode": config.get("history_mode") or "all_available",
        "start_date": config.get("start_date"),
        # An all-market scan must keep the same identity when a security is newly
        # listed. Explicit single/multi-symbol scans remain scoped to those symbols.
        "symbols": requested_symbols or "all_matching_universe",
        "ordinary_shares_only": bool(config.get("ordinary_shares_only", True)),
        "strategy_mode": config.get("strategy_mode") or "presets",
        "strategies": sorted((item.get("id"), item.get("source_hash")) for item in selected),
        "data_source": config.get("data_source") or "merolagani",
        "costs": {key: config.get(key) for key in (
            "initial_capital", "charge_model", "investor_type", "apply_cgt", "dp_charge",
            "fee_pct", "fixed_fee", "slippage_pct", "position_size_pct",
        )},
        "risk": {key: config.get(key) for key in (
            "min_holding_days", "max_holding_days", "trailing_stop_pct",
            "max_volume_participation_pct", "risk_free_rate_pct",
        )},
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _custom_strategy_descriptor(query_text: str, config: Dict[str, Any]) -> Dict[str, Any]:
    try:
        plan = parse_strategy_query(query_text)
    except StrategyQueryError as exc:
        raise ValueError(f"Custom strategy query is invalid: {exc}") from exc
    if plan.side != "BUY":
        raise ValueError("Custom market backtests currently require a BUY entry strategy.")
    if not plan.rules:
        raise ValueError("Custom strategy query must contain at least one rule.")
    selected_min_holding = int(config.get("min_holding_days") or 0)
    selected_max_holding = config.get("max_holding_days")
    if plan.backtest:
        selected_max_holding = int(selected_max_holding or plan.backtest.max_holding_days)
        if selected_min_holding > selected_max_holding:
            raise ValueError("Minimum holding days cannot exceed maximum holding days.")
        plan.backtest = plan.backtest.model_copy(update={
            "min_holding_days": selected_min_holding,
            "max_holding_days": selected_max_holding,
        })
    canonical = format_strategy_query(plan)
    source_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    backtest = plan.backtest
    conditions = [format_expression(rule.when or rule.signal) for rule in plan.rules if rule.when or rule.signal]
    first_name = plan.rules[0].name
    display_name = first_name if len(plan.rules) == 1 else f"{first_name} + {len(plan.rules) - 1} rules"
    return {
        "id": f"custom_{source_hash[:16]}", "name": display_name,
        "category": "Custom query", "family": "custom_query",
        "description": "Versioned Strategy Language query supplied by the user.",
        "condition": " OR ".join(conditions) or "Custom Strategy Language rules",
        "version": f"strategy-query-v{plan.version}", "source_hash": source_hash,
        "custom_query_text": canonical, "custom_query_source": query_text,
        "defaults": {
            "stop_loss_pct": float(backtest.stop_loss_pct if backtest else config.get("stop_loss_pct") or 5),
            "take_profit_pct": float(backtest.take_profit_pct if backtest else config.get("take_profit_pct") or 10),
            "min_holding_days": int(backtest.min_holding_days if backtest else selected_min_holding),
            "max_holding_days": int(backtest.max_holding_days if backtest else config.get("max_holding_days") or 20),
        },
    }


def _session():
    from database import SessionLocal
    return SessionLocal()


def create_run(configuration: Dict[str, Any], *, owner_id: str = "local") -> Dict[str, Any]:
    config = dict(configuration)
    start = date.fromisoformat(str(config["start_date"]))
    end = date.fromisoformat(str(config["end_date"]))
    config["start_date"] = start.isoformat()
    config["end_date"] = end.isoformat()
    custom_query = str(config.get("custom_query_text") or "").strip()
    if str(config.get("strategy_mode") or "presets") == "custom" and not custom_query:
        raise ValueError("Custom strategy mode requires a complete Strategy Language query.")
    if custom_query:
        custom_strategy = _custom_strategy_descriptor(custom_query, config)
        config["strategy_mode"] = "custom"
        config["custom_strategy"] = custom_strategy
        config["custom_query_text"] = custom_strategy["custom_query_text"]
        config["preset_ids"] = []
        selected = [custom_strategy]
    else:
        presets = get_backtest_presets()
        requested = set(config.get("preset_ids") or [item["id"] for item in presets])
        selected = [item for item in presets if item["id"] in requested]
        if not selected:
            raise ValueError("Select at least one valid preset strategy or provide a custom query.")
        config["strategy_mode"] = "presets"
        config["preset_ids"] = [item["id"] for item in selected]
    config.setdefault("ordinary_shares_only", True)
    config.setdefault("max_workers", 1)
    config.setdefault("data_source", "merolagani")
    config.setdefault("initial_capital", 100000)
    config.setdefault("charge_model", "nepse_equity")
    config.setdefault("investor_type", "individual")
    config.setdefault("apply_cgt", True)
    config.setdefault("dp_charge", 25)
    config.setdefault("fee_pct", .4)
    config.setdefault("fixed_fee", 0)
    config.setdefault("slippage_pct", .1)
    config.setdefault("position_size_pct", 100)
    config.setdefault("min_holding_days", 0)
    config.setdefault("max_holding_days", None)
    config.setdefault("trailing_stop_pct", None)
    config.setdefault("max_volume_participation_pct", 10)
    config.setdefault("risk_free_rate_pct", 4)
    config.setdefault("auto_refresh", True)
    config.setdefault("refresh_times_nepal", ["10:00", "11:00"])
    config.setdefault("refresh_mode", "incremental_market_data_full_metric_replay")
    if config["max_holding_days"] is not None and int(config["min_holding_days"]) > int(config["max_holding_days"]):
        raise ValueError("Minimum holding days cannot exceed maximum holding days.")
    config.setdefault("portfolio", {
        "max_stock_pct": 10, "max_sector_pct": 30, "max_positions": 10,
        "cash_reserve_pct": 5, "max_volume_participation_pct": 10,
    })
    universe = get_backtest_universe(
        start, end, config.get("symbols"),
        ordinary_shares_only=bool(config["ordinary_shares_only"]),
        max_listing_age_days=config.get("max_listing_age_days"),
        min_volume=config.get("min_volume"),
    )
    if not universe:
        raise ValueError("No instruments match the selected universe filters.")
    scan_key = _scan_key(config, universe, selected)
    config["scan_key"] = scan_key
    session = _session()
    try:
        metadata = _symbol_metadata(session)
        manifest = {
            "source": config["data_source"], "start_date": start.isoformat(),
            "end_date": end.isoformat(), "symbols": universe,
            "ordinary_shares_only": bool(config["ordinary_shares_only"]),
            "indicator_engine_version": ENGINE_VERSION,
        }
        import hashlib
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        snapshot_id = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        existing = session.execute(text(
            """SELECT run_id,status,configuration FROM backtest_runs
               WHERE owner_id=:owner_id AND scan_key=:scan_key AND deleted_at IS NULL
               FOR UPDATE"""
        ), {"owner_id": owner_id, "scan_key": scan_key}).mappings().first()
        if not existing:
            # Adopt an exact pre-scan-key workspace instead of creating the first
            # post-upgrade duplicate. Missing/new strategy IDs intentionally make
            # a different identity.
            legacy_rows = session.execute(text(
                """SELECT run_id,status,configuration FROM backtest_runs
                   WHERE owner_id=:owner_id AND scan_key IS NULL AND deleted_at IS NULL
                   ORDER BY updated_at DESC FOR UPDATE"""
            ), {"owner_id": owner_id}).mappings().all()
            preset_catalog = {item["id"]: item for item in get_backtest_presets()}
            for legacy in legacy_rows:
                legacy_config = dict(legacy["configuration"] or {})
                try:
                    if str(legacy_config.get("strategy_mode") or "presets") == "custom":
                        legacy_selected = [legacy_config.get("custom_strategy") or _custom_strategy_descriptor(
                            str(legacy_config.get("custom_query_text") or ""), legacy_config,
                        )]
                    else:
                        legacy_selected = [preset_catalog[item] for item in legacy_config.get("preset_ids") or [] if item in preset_catalog]
                    if legacy_selected and _scan_key(legacy_config, [], legacy_selected) == scan_key:
                        session.execute(text(
                            "UPDATE backtest_runs SET scan_key=:scan_key WHERE run_id=:run_id"
                        ), {"scan_key": scan_key, "run_id": legacy["run_id"]})
                        existing = legacy
                        break
                except (TypeError, ValueError):
                    continue
        if existing:
            existing_config = dict(existing["configuration"] or {})
            existing_end = date.fromisoformat(str(existing_config.get("end_date") or config["end_date"]))
            if existing["status"] in {"queued", "running", "paused"} or end <= existing_end:
                session.rollback()
                return get_run(str(existing["run_id"]), owner_id=owner_id)
            session.execute(text(
                """INSERT INTO backtest_data_snapshots
                   (snapshot_id, source, universe, manifest, data_hash)
                   VALUES (:snapshot_id, :source, CAST(:universe AS JSONB), CAST(:manifest AS JSONB), :data_hash)
                   ON CONFLICT (snapshot_id) DO NOTHING"""
            ), {"snapshot_id": snapshot_id, "source": config["data_source"], "universe": json.dumps(universe), "manifest": encoded, "data_hash": snapshot_id})
            symbol_rows = []
            for symbol in universe:
                item = metadata.get(symbol, {})
                symbol_rows.append({
                    "run_id": existing["run_id"], "symbol": symbol,
                    "security_type": item.get("security_type"), "sector": item.get("sector"),
                    "listing_age_days": item.get("listing_age_days"), "ltp": item.get("ltp"),
                    "latest_volume": item.get("latest_volume"),
                })
            session.execute(text(
                """INSERT INTO backtest_run_symbols
                   (run_id, symbol, security_type, sector, listing_age_days, ltp, latest_volume)
                   VALUES (:run_id, :symbol, :security_type, :sector, :listing_age_days, :ltp, :latest_volume)
                   ON CONFLICT (run_id, symbol) DO UPDATE SET
                     security_type=EXCLUDED.security_type,sector=EXCLUDED.sector,
                     listing_age_days=EXCLUDED.listing_age_days,ltp=EXCLUDED.ltp,
                     latest_volume=EXCLUDED.latest_volume"""
            ), symbol_rows)
            session.execute(text(
                """UPDATE backtest_run_symbols SET status='queued',error=NULL,completed_at=NULL
                   WHERE run_id=:run_id"""
            ), {"run_id": existing["run_id"]})
            session.execute(text(
                """UPDATE backtest_runs SET name=:name,notes=:notes,status='queued',configuration=CAST(:configuration AS JSONB),
                          data_snapshot_id=:snapshot_id,symbols_completed=0,
                          symbols_total=(SELECT COUNT(*) FROM backtest_run_symbols WHERE run_id=:run_id),
                          progress_pct=0,current_symbol=NULL,cancel_requested=FALSE,pause_requested=FALSE,
                          error_summary=NULL,finished_at=NULL,updated_at=NOW()
                   WHERE run_id=:run_id"""
            ), {"run_id": existing["run_id"], "name": str(config.get("name") or "NEPSE research")[:200],
                "notes": config.get("notes"), "configuration": json.dumps(config), "snapshot_id": snapshot_id})
            session.commit()
            return get_run(str(existing["run_id"]), owner_id=owner_id)
        run_id = uuid.uuid4().hex
        session.execute(text(
            """INSERT INTO backtest_data_snapshots
               (snapshot_id, source, universe, manifest, data_hash)
               VALUES (:snapshot_id, :source, CAST(:universe AS JSONB), CAST(:manifest AS JSONB), :data_hash)
               ON CONFLICT (snapshot_id) DO NOTHING"""
        ), {"snapshot_id": snapshot_id, "source": config["data_source"], "universe": json.dumps(universe), "manifest": encoded, "data_hash": snapshot_id})
        session.execute(text(
            """INSERT INTO backtest_runs
               (run_id, owner_id, scan_key, name, notes, run_type, status, configuration,
                strategy_version, engine_version, indicator_engine_version,
                data_snapshot_id, symbols_total)
               VALUES (:run_id, :owner_id, :scan_key, :name, :notes, :run_type, 'queued',
                       CAST(:configuration AS JSONB), :strategy_version, :engine_version,
                       :indicator_version, :snapshot_id, :symbols_total)"""
        ), {
            "run_id": run_id, "owner_id": owner_id, "scan_key": scan_key,
            "name": str(config.get("name") or f"NEPSE research {start} to {end}")[:200],
            "notes": config.get("notes"), "run_type": config.get("run_type") or "market_scan",
            "configuration": json.dumps(config), "engine_version": BACKTEST_ENGINE_VERSION,
            "strategy_version": selected[0].get("version") if len(selected) == 1 else "strategy-catalog-v2",
            "indicator_version": ENGINE_VERSION, "snapshot_id": snapshot_id,
            "symbols_total": len(universe),
        })
        symbol_rows = []
        for symbol in universe:
            item = metadata.get(symbol, {})
            symbol_rows.append({
                "run_id": run_id, "symbol": symbol,
                "security_type": item.get("security_type"), "sector": item.get("sector"),
                "listing_age_days": item.get("listing_age_days"), "ltp": item.get("ltp"),
                "latest_volume": item.get("latest_volume"),
            })
        session.execute(text(
            """INSERT INTO backtest_run_symbols
               (run_id, symbol, security_type, sector, listing_age_days, ltp, latest_volume)
               VALUES (:run_id, :symbol, :security_type, :sector, :listing_age_days, :ltp, :latest_volume)"""
        ), symbol_rows)
        session.commit()
        return get_run(run_id, owner_id=owner_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _public_run(row: Dict[str, Any]) -> Dict[str, Any]:
    output = dict(row)
    for key in ("created_at", "started_at", "finished_at", "updated_at", "heartbeat_at"):
        output[key] = output[key].isoformat() if output.get(key) else None
    output.pop("lease_owner", None)
    output.pop("lease_expires_at", None)
    output["has_results"] = int(output.get("combinations_completed") or 0) > 0
    return output


def get_run(run_id: str, *, owner_id: str = "local") -> Dict[str, Any]:
    session = _session()
    try:
        row = session.execute(text(
            """SELECT * FROM backtest_runs
               WHERE run_id = :run_id AND owner_id = :owner_id AND deleted_at IS NULL"""
        ), {"run_id": run_id, "owner_id": owner_id}).mappings().first()
        if not row:
            raise ValueError("Backtest run was not found.")
        return _public_run(dict(row))
    finally:
        session.close()


def list_runs(*, owner_id: str = "local", page: int = 1, page_size: int = 25) -> Dict[str, Any]:
    session = _session()
    try:
        rows = session.execute(text(
            """SELECT * FROM backtest_runs WHERE owner_id=:owner_id AND deleted_at IS NULL
               ORDER BY CASE WHEN status IN ('queued','running','paused') THEN 0 ELSE 1 END,
                        updated_at DESC,created_at DESC"""
        ), {"owner_id": owner_id}).mappings().all()
        unique: List[Dict[str, Any]] = []
        seen = set()
        for mapped in rows:
            row = dict(mapped)
            config = dict(row.get("configuration") or {})
            legacy_identity = dict(config)
            for key in ("name", "notes", "end_date", "max_workers", "scan_key"):
                legacy_identity.pop(key, None)
            display_key = row.get("scan_key") or hashlib.sha256(json.dumps(
                legacy_identity, sort_keys=True, separators=(",", ":"), default=str,
            ).encode("utf-8")).hexdigest()
            if display_key in seen:
                continue
            seen.add(display_key)
            unique.append(_public_run(row))
        total = len(unique)
        offset = (page - 1) * page_size
        return {"items": unique[offset:offset + page_size], "page": page, "page_size": page_size, "total": total}
    finally:
        session.close()


def _claim_next_run() -> Optional[str]:
    session = _session()
    try:
        row = session.execute(text(
            """SELECT run_id FROM backtest_runs
               WHERE deleted_at IS NULL AND cancel_requested = FALSE AND pause_requested = FALSE
                 AND (status = 'queued' OR (status = 'running' AND lease_expires_at < NOW()))
               ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"""
        )).scalar()
        if not row:
            session.rollback()
            return None
        session.execute(text(
            """UPDATE backtest_runs SET status='running', started_at=COALESCE(started_at,NOW()),
                      lease_owner=:owner, lease_expires_at=NOW()+INTERVAL '45 seconds',
                      heartbeat_at=NOW(), updated_at=NOW(), error_summary=NULL
               WHERE run_id=:run_id"""
        ), {"owner": _WORKER_ID, "run_id": row})
        session.commit()
        return str(row)
    finally:
        session.close()


def _control_state(run_id: str) -> Dict[str, bool]:
    session = _session()
    try:
        row = session.execute(text(
            "SELECT cancel_requested, pause_requested FROM backtest_runs WHERE run_id=:run_id"
        ), {"run_id": run_id}).mappings().one()
        session.execute(text(
            """UPDATE backtest_runs SET heartbeat_at=NOW(), lease_expires_at=NOW()+INTERVAL '45 seconds',
                      updated_at=NOW() WHERE run_id=:run_id AND lease_owner=:owner"""
        ), {"run_id": run_id, "owner": _WORKER_ID})
        session.commit()
        return {"cancel": bool(row["cancel_requested"]), "pause": bool(row["pause_requested"])}
    finally:
        session.close()


def _persist_symbol_output(run_id: str, output: Dict[str, Any]) -> None:
    symbol = str(output["symbol"])
    session = _session()
    try:
        session.execute(text("DELETE FROM backtest_results WHERE run_id=:run_id AND symbol=:symbol"), {"run_id": run_id, "symbol": symbol})
        partial_rows = list(output.get("results") or [])
        assign_robust_scores(partial_rows)
        for row in partial_rows:
            trades = list(row.pop("trades", []) or [])
            result_id = session.execute(text(
                """INSERT INTO backtest_results
                   (run_id,symbol,preset_id,preset_name,preset_family,category,evaluation_split,bars,
                    total_trades,wins,losses,win_rate_pct,win_rate_ci_low,win_rate_ci_high,
                    confidence_score,robust_score,net_return_pct,max_drawdown_pct,sharpe_ratio,
                    sortino_ratio,profit_factor,expectancy_pct,alpha_vs_benchmark_pct,exposure_pct,
                    average_holding_days,oos_trades,oos_win_rate_pct,oos_return_pct,oos_expectancy_pct,
                    oos_sharpe_ratio,oos_max_drawdown_pct,walk_forward_profitable_pct,p_value,fdr_q_value,
                    data_completeness_pct,liquidity_score,sample_quality,recommendation_status,
                    current_signal_active,current_signal_status,current_signal_date,current_technical_score,
                    reliability_score,strong_buy_qualified,current_evidence,
                    warning_codes,technical_snapshot,assumptions)
                   VALUES (:run_id,:symbol,:preset_id,:preset_name,:preset_family,:category,'full',:bars,
                    :total_trades,:wins,:losses,:win_rate_pct,:win_rate_ci_low,:win_rate_ci_high,
                    :confidence_score,:robust_score,:net_return_pct,:max_drawdown_pct,:sharpe_ratio,
                    :sortino_ratio,:profit_factor,:expectancy_pct,:alpha_vs_benchmark_pct,:exposure_pct,
                    :average_holding_days,:oos_trades,:oos_win_rate_pct,:oos_return_pct,:oos_expectancy_pct,
                    :oos_sharpe_ratio,:oos_max_drawdown_pct,:walk_forward_profitable_pct,:p_value,:fdr_q_value,
                    :data_completeness_pct,:liquidity_score,:sample_quality,:recommendation_status,
                    :current_signal_active,:current_signal_status,:current_signal_date,:current_technical_score,
                    :reliability_score,:strong_buy_qualified,CAST(:current_evidence AS JSONB),
                    CAST(:warning_codes AS JSONB),CAST(:technical_snapshot AS JSONB),CAST(:assumptions AS JSONB))
                   RETURNING result_id"""
            ), {
                **{key: row.get(key) for key in (
                    "preset_id","preset_name","preset_family","category","bars","total_trades",
                    "wins","losses","win_rate_pct","win_rate_ci_low","win_rate_ci_high",
                    "confidence_score","net_return_pct","max_drawdown_pct","sharpe_ratio",
                    "sortino_ratio","profit_factor","expectancy_pct","alpha_vs_benchmark_pct",
                    "exposure_pct","average_holding_days","oos_trades","oos_win_rate_pct",
                    "oos_return_pct","oos_expectancy_pct","oos_sharpe_ratio","oos_max_drawdown_pct",
                    "walk_forward_profitable_pct","p_value","data_completeness_pct","liquidity_score",
                    "sample_quality","recommendation_status","robust_score","fdr_q_value",
                    "current_signal_active","current_signal_status","current_signal_date",
                    "current_technical_score","reliability_score","strong_buy_qualified",
                )},
                "run_id": run_id, "symbol": symbol,
                "warning_codes": json.dumps(row.get("warning_codes") or []),
                "current_evidence": json.dumps(row.get("current_evidence") or {}),
                "technical_snapshot": json.dumps({key: row.get(key) for key in ("technical_signal","technical_signal_score","technical_buy_score","technical_sell_score")}),
                "assumptions": json.dumps(row.get("assumptions") or {}),
            }).scalar_one()
            if trades:
                session.execute(text(
                    """INSERT INTO backtest_trades
                       (result_id,sequence_no,signal_date,entry_date,entry_price,exit_date,exit_price,
                        quantity,holding_days,exit_reason,fees,broker_commission,buy_broker_commission,
                        sell_broker_commission,sebon_fee,buy_sebon_fee,sell_sebon_fee,dp_charge,
                        capital_gains_tax,capital_gains_tax_rate_pct,total_charges,gross_pnl,
                        net_pnl_before_tax,slippage_cost,pnl,return_pct)
                       VALUES (:result_id,:sequence_no,:signal_date,:entry_date,:entry_price,:exit_date,
                               :exit_price,:quantity,:holding_days,:exit_reason,:fees,:broker_commission,
                               :buy_broker_commission,:sell_broker_commission,:sebon_fee,:buy_sebon_fee,
                               :sell_sebon_fee,:dp_charge,:capital_gains_tax,:capital_gains_tax_rate_pct,
                               :total_charges,:gross_pnl,:net_pnl_before_tax,:slippage_cost,:pnl,:return_pct)"""
                ), [{
                    "result_id": result_id, "sequence_no": index + 1,
                    "signal_date": trade.get("signal_date"), "entry_date": trade["entry_date"],
                    "entry_price": trade["entry_price"], "exit_date": trade["exit_date"],
                    "exit_price": trade["exit_price"], "quantity": trade["quantity"],
                    "holding_days": trade.get("holding_days") or 0,
                    "exit_reason": trade.get("exit_reason"), "fees": trade.get("fees") or 0,
                    "broker_commission": trade.get("broker_commission") or 0,
                    "buy_broker_commission": trade.get("buy_broker_commission") or 0,
                    "sell_broker_commission": trade.get("sell_broker_commission") or 0,
                    "sebon_fee": trade.get("sebon_fee") or 0,
                    "buy_sebon_fee": trade.get("buy_sebon_fee") or 0,
                    "sell_sebon_fee": trade.get("sell_sebon_fee") or 0,
                    "dp_charge": trade.get("dp_charge") or 0,
                    "capital_gains_tax": trade.get("capital_gains_tax") or 0,
                    "capital_gains_tax_rate_pct": trade.get("capital_gains_tax_rate_pct") or 0,
                    "total_charges": trade.get("total_charges") or 0,
                    "gross_pnl": trade.get("gross_pnl") or 0,
                    "net_pnl_before_tax": trade.get("net_pnl_before_tax") or 0,
                    "slippage_cost": trade.get("slippage_cost") or 0,
                    "pnl": trade.get("pnl") or 0, "return_pct": trade.get("return_pct") or 0,
                } for index, trade in enumerate(trades)])
        status = "failed" if output.get("error") and not output.get("results") else "completed"
        profile = output.get("market_profile") or {}
        session.execute(text(
            """UPDATE backtest_run_symbols SET status=:status,bars_count=:bars,
                      combinations_completed=:count,error=:error,completed_at=NOW(),
                      ltp=COALESCE(:ltp,ltp),latest_volume=COALESCE(:latest_volume,latest_volume),
                      average_volume_20=:average_volume_20,median_volume_20=:median_volume_20,
                      average_turnover_20=:average_turnover_20,last_tested_session=:last_tested_session
               WHERE run_id=:run_id AND symbol=:symbol"""
        ), {"status": status, "bars": int((output.get("technical_snapshot") or {}).get("bars_count") or 0),
            "count": len(output.get("results") or []), "error": output.get("error"),
            "ltp": profile.get("ltp"), "latest_volume": profile.get("latest_volume"),
            "average_volume_20": profile.get("average_volume_20"),
            "median_volume_20": profile.get("median_volume_20"),
            "average_turnover_20": profile.get("average_turnover_20"),
            "last_tested_session": (output.get("technical_snapshot") or {}).get("as_of_date"),
            "run_id": run_id, "symbol": symbol})
        technical_snapshot = dict(output.get("technical_snapshot") or {})
        indicators = dict(technical_snapshot.get("indicators") or {})
        indicators.update({key: profile.get(key) for key in (
            "latest_volume", "average_volume_20", "median_volume_20", "average_turnover_20",
        )})
        if indicators and technical_snapshot.get("as_of_date"):
            from utils.market_data.repository import save_technical_indicator_snapshot
            save_technical_indicator_snapshot(
                session, symbol=symbol, as_of_date=date.fromisoformat(str(technical_snapshot["as_of_date"])),
                indicators=indicators, engine_version=str(technical_snapshot.get("engine_version") or ENGINE_VERSION),
                bars_count=int(technical_snapshot.get("bars_count") or 0),
                history_start=date.fromisoformat(str(technical_snapshot.get("history_start") or technical_snapshot["as_of_date"])),
                history_end=date.fromisoformat(str(technical_snapshot.get("history_end") or technical_snapshot["as_of_date"])),
            )
        session.execute(text(
            """UPDATE backtest_runs SET symbols_completed=(SELECT COUNT(*) FROM backtest_run_symbols WHERE run_id=:run_id AND status IN ('completed','failed')),
                      combinations_completed=(SELECT COUNT(*) FROM backtest_results WHERE run_id=:run_id),
                      current_symbol=:symbol,
                      progress_pct=ROUND((100.0*(SELECT COUNT(*) FROM backtest_run_symbols WHERE run_id=:run_id AND status IN ('completed','failed'))/NULLIF(symbols_total,0))::numeric,1)::double precision,
                      heartbeat_at=NOW(),lease_expires_at=NOW()+INTERVAL '45 seconds',updated_at=NOW()
               WHERE run_id=:run_id"""
        ), {"run_id": run_id, "symbol": symbol})
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _finalize_scores(run_id: str) -> None:
    session = _session()
    try:
        rows = [dict(row) for row in session.execute(text(
            """SELECT result_id,oos_expectancy_pct,oos_return_pct,oos_sharpe_ratio,
                      oos_max_drawdown_pct,walk_forward_profitable_pct,oos_trades,
                      data_completeness_pct,p_value,warning_codes
               FROM backtest_results WHERE run_id=:run_id"""
        ), {"run_id": run_id}).mappings().all()]
        assign_robust_scores(rows)
        session.execute(text(
            """UPDATE backtest_results SET robust_score=:robust_score,fdr_q_value=:fdr_q_value,
                      warning_codes=CAST(:warning_codes AS JSONB) WHERE result_id=:result_id"""
        ), [{"result_id": row["result_id"], "robust_score": row["robust_score"],
             "fdr_q_value": row["fdr_q_value"], "warning_codes": json.dumps(row["warning_codes"])} for row in rows])
        session.execute(text(
            """WITH latest AS (SELECT MAX(current_signal_date) AS max_date FROM backtest_results WHERE run_id=:run_id)
               UPDATE backtest_results r SET strong_buy_qualified=FALSE,current_signal_status='stale',
                      reliability_score=GREATEST(0,reliability_score-32),
                      current_evidence=jsonb_set(jsonb_set(COALESCE(current_evidence,'{}'::jsonb),
                        '{data_fresh}','false'::jsonb,TRUE),'{stale_reason}',to_jsonb('A newer completed session exists in this run.'::text),TRUE)
               FROM latest WHERE r.run_id=:run_id AND r.current_signal_active=TRUE
                 AND r.current_signal_date < latest.max_date"""
        ), {"run_id": run_id})
        configuration = dict(session.execute(text(
            "SELECT configuration FROM backtest_runs WHERE run_id=:run_id"
        ), {"run_id": run_id}).scalar() or {})
        from utils.backtesting.portfolio import build_portfolios_for_run
        build_portfolios_for_run(session, run_id, configuration)
        session.commit()
        from utils.backtesting.recommendations import materialize_recommendations
        materialize_recommendations(session, owner_id="local")
        session.commit()
    finally:
        session.close()


def run_claimed_run(run_id: str) -> None:
    session = _session()
    try:
        row = session.execute(text("SELECT configuration FROM backtest_runs WHERE run_id=:run_id"), {"run_id": run_id}).mappings().one()
        config = dict(row["configuration"] or {})
        symbols = session.execute(text(
            "SELECT symbol FROM backtest_run_symbols WHERE run_id=:run_id AND status NOT IN ('completed') ORDER BY symbol"
        ), {"run_id": run_id}).scalars().all()
    finally:
        session.close()
    if config.get("strategy_mode") == "custom" and config.get("custom_strategy"):
        presets = [dict(config["custom_strategy"])]
    else:
        presets = [item for item in get_backtest_presets() if item["id"] in set(config.get("preset_ids") or [])]
    settings = {
        "initial_capital": float(config.get("initial_capital") or 100000),
        "charge_model": str(config.get("charge_model") or "nepse_equity"),
        "investor_type": str(config.get("investor_type") or "individual"),
        "apply_cgt": bool(config.get("apply_cgt", True)),
        "dp_charge": float(config.get("dp_charge") if config.get("dp_charge") is not None else 25),
        "fee_pct": float(config.get("fee_pct") or .4), "fixed_fee": float(config.get("fixed_fee") or 0),
        "slippage_pct": float(config.get("slippage_pct") or .1),
        "position_size_pct": float(config.get("position_size_pct") or 100),
        "min_holding_days": int(config.get("min_holding_days") or 0),
        "max_holding_days": int(config["max_holding_days"]) if config.get("max_holding_days") is not None else None,
        "trailing_stop_pct": config.get("trailing_stop_pct"),
        "max_volume_participation_pct": float(config.get("max_volume_participation_pct") or 10),
        "risk_free_rate_pct": float(config.get("risk_free_rate_pct") or 4), "professional": True,
    }
    tasks = [{"symbol": symbol, "start_date": date.fromisoformat(config["start_date"]),
              "end_date": date.fromisoformat(config["end_date"]), "data_source": config.get("data_source") or "merolagani",
              "presets": presets, "settings": settings} for symbol in symbols]
    workers = background_worker_limit(config.get("max_workers"))
    try:
        if tasks:
            context = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=workers, mp_context=context, initializer=initialize_background_worker,
            ) as executor:
                futures = {executor.submit(_run_symbol_task, task): task["symbol"] for task in tasks}
                for future in as_completed(futures):
                    control = _control_state(run_id)
                    if control["cancel"] or control["pause"]:
                        for pending in futures:
                            pending.cancel()
                        break
                    try:
                        output = future.result()
                    except Exception as exc:
                        output = {"symbol": futures[future], "results": [], "error": str(exc)}
                    _persist_symbol_output(run_id, output)
        control = _control_state(run_id)
        session = _session()
        try:
            if control["cancel"]:
                status = "cancelled"
            elif control["pause"]:
                status = "paused"
            else:
                _finalize_scores(run_id)
                status = "completed"
            session.execute(text(
                """UPDATE backtest_runs SET status=:status,progress_pct=CASE WHEN :status='completed' THEN 100 ELSE progress_pct END,
                          current_symbol=NULL,finished_at=CASE WHEN :status IN ('completed','cancelled') THEN NOW() ELSE finished_at END,
                          last_refresh_at=CASE WHEN :status='completed' THEN NOW() ELSE last_refresh_at END,
                          lease_owner=NULL,lease_expires_at=NULL,updated_at=NOW()
                   WHERE run_id=:run_id"""
            ), {"status": status, "run_id": run_id})
            session.commit()
        finally:
            session.close()
    except Exception as exc:
        session = _session()
        try:
            session.execute(text(
                """UPDATE backtest_runs SET status='failed',error_summary=:error,finished_at=NOW(),
                          lease_owner=NULL,lease_expires_at=NULL,updated_at=NOW() WHERE run_id=:run_id"""
            ), {"run_id": run_id, "error": str(exc)[:4000]})
            session.commit()
        finally:
            session.close()


def _queue_scheduled_refreshes() -> int:
    """Queue each continuing scan once at 10:00 and 11:00 Nepal time."""
    global _LAST_DAILY_REFRESH_SLOT
    if os.getenv("BACKTEST_DAILY_REFRESH_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return 0
    now = datetime.now(NEPAL_TZ)
    if now.hour not in DAILY_REFRESH_HOURS:
        return 0
    from utils.market_status import get_market_hours_status
    if not get_market_hours_status(now)["is_trading_day"]:
        return 0
    slot = f"{now.date().isoformat()}T{now.hour:02d}:00+05:45"
    check_minute = f"{slot}:{now.minute:02d}"
    if check_minute == _LAST_DAILY_REFRESH_SLOT:
        return 0
    _LAST_DAILY_REFRESH_SLOT = check_minute
    session = _session()
    queued = 0
    try:
        rows = session.execute(text(
            """SELECT DISTINCT ON (COALESCE(scan_key,run_id)) run_id,configuration,status
               FROM backtest_runs
               WHERE deleted_at IS NULL AND COALESCE((configuration->>'auto_refresh')::boolean,TRUE)=TRUE
               ORDER BY COALESCE(scan_key,run_id),updated_at DESC"""
        )).mappings().all()
        metadata = _symbol_metadata(session)
        for row in rows:
            if row["status"] in {"queued", "running", "paused"}:
                continue
            config = dict(row["configuration"] or {})
            if config.get("last_refresh_slot") == slot:
                continue
            config["end_date"] = now.date().isoformat()
            config["last_refresh_slot"] = slot
            metadata_updates = [
                {"run_id": row["run_id"], "symbol": symbol, "ltp": item.get("ltp"),
                 "latest_volume": item.get("latest_volume")}
                for symbol, item in metadata.items()
            ]
            stale_symbols = 0
            if metadata_updates:
                stale_symbols = session.execute(text(
                    """UPDATE backtest_run_symbols SET status='queued',error=NULL,completed_at=NULL,
                              ltp=COALESCE(:ltp,ltp),latest_volume=COALESCE(:latest_volume,latest_volume)
                       WHERE run_id=:run_id AND symbol=:symbol
                         AND (last_tested_session IS NULL OR last_tested_session < COALESCE((
                             SELECT MAX((to_timestamp(m.source_timestamp) AT TIME ZONE 'UTC')::date)
                             FROM market_ohlcv_daily m WHERE m.symbol=:symbol AND m.adjusted=TRUE
                         ),last_tested_session))"""
                ), metadata_updates).rowcount
            if not stale_symbols:
                config["last_refresh_slot"] = slot
                session.execute(text(
                    "UPDATE backtest_runs SET configuration=CAST(:configuration AS JSONB),last_refresh_at=NOW(),updated_at=NOW() WHERE run_id=:run_id"
                ), {"run_id": row["run_id"], "configuration": json.dumps(config)})
                continue
            session.execute(text(
                """UPDATE backtest_runs SET status='queued',configuration=CAST(:configuration AS JSONB),
                          symbols_completed=0,progress_pct=0,current_symbol=NULL,cancel_requested=FALSE,
                          pause_requested=FALSE,error_summary=NULL,finished_at=NULL,updated_at=NOW()
                   WHERE run_id=:run_id"""
            ), {"run_id": row["run_id"], "configuration": json.dumps(config)})
            queued += 1
        session.commit()
        return queued
    except Exception:
        session.rollback()
        return 0
    finally:
        session.close()


def worker_loop() -> None:
    while True:
        _queue_scheduled_refreshes()
        run_id = _claim_next_run()
        if run_id:
            run_claimed_run(run_id)
        else:
            time.sleep(2)


def start_worker() -> bool:
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return False
        _WORKER_STARTED = True
    threading.Thread(target=worker_loop, name="backtest-v2-worker", daemon=True).start()
    return True


def set_run_control(run_id: str, action: str, *, owner_id: str = "local") -> Dict[str, Any]:
    if action not in {"cancel", "pause", "resume"}:
        raise ValueError("Unsupported run control action.")
    session = _session()
    try:
        if action == "cancel":
            statement = "UPDATE backtest_runs SET cancel_requested=TRUE,updated_at=NOW() WHERE run_id=:run_id AND owner_id=:owner_id AND status IN ('queued','running','paused')"
        elif action == "pause":
            statement = "UPDATE backtest_runs SET pause_requested=TRUE,updated_at=NOW() WHERE run_id=:run_id AND owner_id=:owner_id AND status IN ('queued','running')"
        else:
            statement = "UPDATE backtest_runs SET pause_requested=FALSE,cancel_requested=FALSE,status='queued',updated_at=NOW() WHERE run_id=:run_id AND owner_id=:owner_id AND status IN ('paused','failed')"
        changed = session.execute(text(statement), {"run_id": run_id, "owner_id": owner_id}).rowcount
        if not changed:
            session.rollback()
            raise ValueError("Run cannot perform that action in its current state.")
        session.commit()
    finally:
        session.close()
    return get_run(run_id, owner_id=owner_id)


def clone_run(run_id: str, *, owner_id: str = "local", name: Optional[str] = None) -> Dict[str, Any]:
    source = get_run(run_id, owner_id=owner_id)
    configuration = dict(source.get("configuration") or {})
    configuration["name"] = name or f"{source['name']} (copy)"
    return create_run(configuration, owner_id=owner_id)


def retry_failed_symbols(run_id: str, *, owner_id: str = "local") -> Dict[str, Any]:
    session = _session()
    try:
        changed = session.execute(text(
            """UPDATE backtest_run_symbols s SET status='queued',error=NULL,completed_at=NULL
               FROM backtest_runs r WHERE s.run_id=r.run_id AND s.run_id=:run_id AND r.owner_id=:owner_id
                 AND s.status='failed'"""
        ), {"run_id": run_id, "owner_id": owner_id}).rowcount
        if not changed:
            raise ValueError("This run has no failed symbols to retry.")
        session.execute(text(
            """UPDATE backtest_runs SET status='queued',cancel_requested=FALSE,pause_requested=FALSE,
                      error_summary=NULL,finished_at=NULL,updated_at=NOW() WHERE run_id=:run_id AND owner_id=:owner_id"""
        ), {"run_id": run_id, "owner_id": owner_id})
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return get_run(run_id, owner_id=owner_id)
