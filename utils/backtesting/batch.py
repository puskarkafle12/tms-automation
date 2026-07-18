"""Multi-core NEPSE universe and multi-preset backtesting."""

from __future__ import annotations

import math
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import text

from utils.backtesting.presets import build_preset_query, get_backtest_presets
from utils.strategy_builder.strategy_parser import retarget_strategy_query
from utils.backtesting.service import (
    BacktestError,
    _historical_rows,
    fetch_combined_snapshot_bars,
    fetch_historical_bars,
    run_backtest,
)
from utils.technical_indicators import ENGINE_VERSION


ProgressCallback = Callable[[int, int, str, int, Optional[Dict[str, Any]]], None]


def get_backtest_universe(
    start_date: date, end_date: date, symbols: Optional[List[str]] = None,
    *, ordinary_shares_only: bool = True, max_listing_age_days: Optional[int] = None,
    min_volume: Optional[float] = None,
) -> List[str]:
    requested = sorted({str(symbol).strip().upper() for symbol in symbols or [] if str(symbol).strip()})[:1000]
    from database import SessionLocal

    session = SessionLocal()
    try:
        equity_filter = "AND c.combined_data->>'security_type' = 'ordinary_share'" if ordinary_shares_only else ""
        age_filter = "AND NULLIF(c.combined_data->>'listing_age_days', '')::FLOAT <= :max_listing_age_days" if max_listing_age_days is not None else ""
        volume_filter = "AND NULLIF(regexp_replace(COALESCE(c.combined_data->>'qty', c.combined_data->>'volume', c.combined_data->>'ml_quantity', ''), '[^0-9.]', '', 'g'), '')::FLOAT >= :min_volume" if min_volume is not None else ""
        symbol_filter = "AND d.symbol = ANY(:requested_symbols)" if requested else ""
        rows = session.execute(
            text(f"""
                SELECT DISTINCT d.symbol
                FROM merolagani_daily_stocks d
                LEFT JOIN market_screener_cache c ON c.symbol = d.symbol
                WHERE d.snapshot_date BETWEEN :start_date AND :end_date
                  {equity_filter}
                  {age_filter}
                  {volume_filter}
                  {symbol_filter}
                ORDER BY d.symbol
                LIMIT 1000
                """),
            {"start_date": start_date, "end_date": end_date, "max_listing_age_days": max_listing_age_days,
             "min_volume": min_volume, "requested_symbols": requested},
        ).scalars().all()
    finally:
        session.close()
    return [str(symbol).strip().upper() for symbol in rows if str(symbol).strip()]


def _confidence_score(win_rate_pct: float, trades: int) -> float:
    """Shrink small samples so one lucky trade cannot top the market ranking."""
    return round(win_rate_pct * math.sqrt(trades / (trades + 5)), 2) if trades else 0.0


def _run_symbol_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Process-safe stock worker: fetch once, prepare once, run every preset."""
    symbol = task["symbol"]
    start_date = task["start_date"]
    end_date = task["end_date"]
    source = task["data_source"]
    selected_presets = task["presets"]
    settings = task["settings"]
    try:
        bars = (
            fetch_combined_snapshot_bars(symbol, start_date, end_date)
            if source == "combined"
            else fetch_historical_bars(symbol, start_date, end_date)
        )
    except BacktestError as exc:
        return {"symbol": symbol, "results": [], "error": str(exc)}
    prepared_rows = list(_historical_rows(symbol, bars))
    professional = bool(settings.get("professional"))
    if professional:
        try:
            from utils.backtesting.cache import store_indicator_history
            store_indicator_history(symbol, bars, prepared_rows, ENGINE_VERSION)
        except Exception:
            pass
    results: List[Dict[str, Any]] = []
    errors: List[str] = []
    for preset in selected_presets:
        defaults = preset["defaults"]
        effective_min_holding_days = int(settings.get("min_holding_days") or defaults.get("min_holding_days") or 0)
        effective_max_holding_days = int(settings.get("max_holding_days") or defaults["max_holding_days"])
        if effective_min_holding_days > effective_max_holding_days:
            errors.append(f'{preset["id"]}: minimum holding days exceeds maximum holding days')
            continue
        custom_query_template = preset.get("custom_query_text")
        executable_query = (
            retarget_strategy_query(custom_query_template, [symbol])
            if custom_query_template else build_preset_query(preset, symbol)
        )
        try:
            entry_signals = None
            if professional and not custom_query_template:
                from utils.backtesting.accelerated import compile_preset_signals
                entry_signals = compile_preset_signals(preset["id"], prepared_rows)
            output = run_backtest(
                symbol=symbol, query_text=executable_query,
                start_date=start_date, end_date=end_date, bars=bars,
                initial_capital=settings["initial_capital"], fee_pct=settings["fee_pct"],
                fixed_fee=settings["fixed_fee"], slippage_pct=settings["slippage_pct"],
                charge_model=settings["charge_model"], investor_type=settings["investor_type"],
                apply_cgt=settings["apply_cgt"], dp_charge=settings["dp_charge"],
                position_size_pct=settings["position_size_pct"],
                trailing_stop_pct=settings["trailing_stop_pct"],
                max_volume_participation_pct=settings["max_volume_participation_pct"],
                risk_free_rate_pct=settings["risk_free_rate_pct"],
                stop_loss_pct=defaults["stop_loss_pct"],
                take_profit_pct=defaults["take_profit_pct"],
                min_holding_days=effective_min_holding_days,
                max_holding_days=effective_max_holding_days,
                prepared_rows=prepared_rows, compact=True, include_trades=professional,
                entry_signals=entry_signals,
            )
        except Exception as exc:
            errors.append(f'{preset["id"]}: {exc}')
            continue
        summary = output["summary"]
        professional_fields: Dict[str, Any] = {}
        current_fields: Dict[str, Any] = {}
        if professional:
            split = max(1, min(len(bars) - 2, int(len(bars) * .70)))
            try:
                oos_output = run_backtest(
                    symbol=symbol, query_text=executable_query,
                    start_date=date.fromisoformat(bars[split].day), end_date=end_date,
                    bars=bars[split:], prepared_rows=prepared_rows[split:], compact=True,
                    entry_signals=entry_signals[split:] if entry_signals is not None else None,
                    initial_capital=settings["initial_capital"], fee_pct=settings["fee_pct"],
                    fixed_fee=settings["fixed_fee"], slippage_pct=settings["slippage_pct"],
                    charge_model=settings["charge_model"], investor_type=settings["investor_type"],
                    apply_cgt=settings["apply_cgt"], dp_charge=settings["dp_charge"],
                    position_size_pct=settings["position_size_pct"],
                    trailing_stop_pct=settings["trailing_stop_pct"],
                    max_volume_participation_pct=settings["max_volume_participation_pct"],
                    risk_free_rate_pct=settings["risk_free_rate_pct"],
                    stop_loss_pct=defaults["stop_loss_pct"], take_profit_pct=defaults["take_profit_pct"],
                    min_holding_days=effective_min_holding_days,
                    max_holding_days=effective_max_holding_days,
                )
                from utils.backtesting.professional import build_validation_fields
                professional_fields = build_validation_fields(
                    summary, oos_output["summary"], bars, output["trades"],
                )
            except Exception as exc:
                professional_fields = {
                    "oos_trades": 0, "oos_win_rate_pct": 0, "oos_return_pct": 0,
                    "oos_expectancy_pct": 0, "oos_sharpe_ratio": None,
                    "oos_max_drawdown_pct": 0, "walk_forward_profitable_pct": None,
                    "data_completeness_pct": 0, "liquidity_score": 0,
                    "p_value": 1, "win_rate_ci_low": 0, "win_rate_ci_high": 0,
                    "warning_codes": ["OOS_EVALUATION_FAILED"],
                    "recommendation_status": "insufficient_sample", "wins": summary.get("wins", 0),
                    "losses": summary.get("losses", 0), "validation_error": str(exc),
                }
            current_active = bool(entry_signals and entry_signals[-1])
            current_evidence: Dict[str, Any] = {
                "active": False, "status": "NO_SIGNAL", "conditions": [],
                "reason": f"{symbol} has no new entry signal on the latest completed session.",
            }
            if custom_query_template:
                try:
                    from utils.backtesting.current_opportunities import evaluate_latest_completed_query
                    current_evidence = evaluate_latest_completed_query(
                        custom_query_template, symbol, prepared_rows, strategy_name=preset["name"],
                    )
                    current_active = bool(current_evidence.get("active"))
                except Exception as exc:
                    current_active = False
                    current_evidence = {"active": False, "status": "EVALUATION_FAILED", "conditions": [], "reason": str(exc)}
            else:
                try:
                    from utils.backtesting.current_opportunities import evaluate_latest_completed_signal
                    current_evidence = evaluate_latest_completed_signal(preset, symbol, prepared_rows)
                    current_active = bool(current_evidence.get("active"))
                except Exception as exc:
                    current_active = False
                    current_evidence = {"active": False, "status": "EVALUATION_FAILED", "conditions": [], "reason": str(exc)}
            technical_score = float(prepared_rows[-1].get("technical_signal_score") or 0)
            indicators_complete = all(prepared_rows[-1].get(field) is not None for field in (
                "technical_rsi_14", "technical_macd_histogram", "technical_adx_14",
            ))
            from utils.backtesting.current_opportunities import qualifies_default, reliability_score
            reliability = reliability_score(
                summary, confidence_score=_confidence_score(summary["win_rate_pct"], summary["total_trades"]),
                technical_score=technical_score, liquidity_score=float(professional_fields.get("liquidity_score") or 0),
                fresh=True, indicators_complete=indicators_complete,
            )
            qualified = qualifies_default(
                summary, active=current_active, fresh=True, indicators_complete=indicators_complete,
                liquidity_score=float(professional_fields.get("liquidity_score") or 0),
            )
            near_trigger = bool(not current_active and current_evidence.get("near_trigger"))
            current_evidence.update({
                "signal_date": bars[-1].day, "calculated_from": "latest_completed_daily_session",
                "data_fresh": True, "indicators_complete": indicators_complete,
                "liquidity_score": professional_fields.get("liquidity_score"),
                "reliability": reliability, "default_requirements_passed": qualified,
            })
            current_fields = {
                "current_signal_active": current_active,
                "current_signal_status": "strong_buy" if qualified else "buy" if current_active and reliability["score"] >= 50 else "watch" if current_active else "near_trigger" if near_trigger else "no_signal",
                "current_signal_date": bars[-1].day, "current_technical_score": technical_score,
                "reliability_score": reliability["score"], "current_evidence": current_evidence,
                "strong_buy_qualified": qualified,
            }
        results.append({
            "symbol": symbol, "preset_id": preset["id"], "preset_name": preset["name"],
            "preset_family": preset.get("family"), "preset_version": preset.get("version"),
            "preset_source_hash": preset.get("source_hash"),
            "category": preset["category"], "bars": output["period"]["bars"],
            "total_trades": summary["total_trades"], "win_rate_pct": summary["win_rate_pct"],
            "confidence_score": _confidence_score(summary["win_rate_pct"], summary["total_trades"]),
            "net_return_pct": summary["net_return_pct"], "max_drawdown_pct": summary["max_drawdown_pct"],
            "sharpe_ratio": summary["sharpe_ratio"], "profit_factor": summary["profit_factor"],
            "expectancy_pct": summary["expectancy_pct"], "alpha_vs_benchmark_pct": summary["alpha_vs_benchmark_pct"],
            "sample_quality": "strong" if summary["total_trades"] >= 20 else "moderate" if summary["total_trades"] >= 5 else "thin",
            "technical_signal": prepared_rows[-1].get("technical_signal"),
            "technical_signal_score": prepared_rows[-1].get("technical_signal_score"),
            "technical_buy_score": prepared_rows[-1].get("technical_buy_score"),
            "technical_sell_score": prepared_rows[-1].get("technical_sell_score"),
            "sortino_ratio": summary.get("sortino_ratio"),
            "exposure_pct": summary.get("exposure_pct"),
            "average_holding_days": summary.get("average_holding_days"),
            "assumptions": {
                **(output.get("assumptions") or {}), "initial_capital": summary.get("initial_capital"),
                "stop_loss_pct": defaults["stop_loss_pct"], "take_profit_pct": defaults["take_profit_pct"],
                "min_holding_days": effective_min_holding_days,
                "max_holding_days": effective_max_holding_days, "preset_version": preset.get("version"),
                "preset_source_hash": preset.get("source_hash"), "period": output.get("period"),
                "data_source": output.get("data_source"), "summary": summary,
                "strategy_mode": "custom" if custom_query_template else "preset",
                "strategy_query": executable_query,
                "strategy_query_template": custom_query_template,
            },
            "trades": output["trades"] if professional else [],
            **professional_fields, **current_fields,
        })
    return {
        "symbol": symbol, "results": results,
        "market_profile": {
            "ltp": float(bars[-1].close), "latest_volume": float(bars[-1].volume),
            "median_volume_20": float(sorted(float(bar.volume or 0) for bar in bars[-20:])[len(bars[-20:]) // 2]),
            "average_turnover_20": round(sum(float(bar.close) * float(bar.volume or 0) for bar in bars[-20:]) / max(len(bars[-20:]), 1), 2),
        },
        "technical_snapshot": {
            "as_of_date": bars[-1].day,
            "indicators": {key: value for key, value in prepared_rows[-1].items() if key.startswith("technical_")},
            "engine_version": ENGINE_VERSION, "bars_count": len(bars),
            "history_start": bars[0].day, "history_end": bars[-1].day,
        },
        "error": "; ".join(errors[:3]) if errors else None,
    }


def build_batch_result(
    *, symbol_outputs: List[Dict[str, Any]], selected_presets: List[Dict[str, Any]],
    data_source: str, symbols_requested: int, workers: int,
) -> Dict[str, Any]:
    """Build the same leaderboard for partial checkpoints and final results."""
    rankings = [result for output in symbol_outputs for result in output.get("results", [])]
    rankings.sort(key=lambda item: (item["win_rate_pct"], item["total_trades"], item["confidence_score"], item["net_return_pct"]), reverse=True)
    reliable_rankings = sorted(
        rankings,
        key=lambda item: (item["confidence_score"], item["win_rate_pct"], item["total_trades"], item["net_return_pct"]),
        reverse=True,
    )
    rows_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for item in rankings:
        if item["total_trades"] > 0:
            rows_by_symbol.setdefault(item["symbol"], []).append(item)
    completed_symbols = [output["symbol"] for output in symbol_outputs]
    stock_summary: List[Dict[str, Any]] = []
    for symbol in completed_symbols:
        rows = rows_by_symbol.get(symbol, [])
        if not rows:
            stock_summary.append({
                "symbol": symbol, "best_preset_id": None, "best_preset_name": None,
                "best_win_rate_pct": 0, "best_confidence_score": 0,
                "best_total_trades": 0, "average_win_rate_pct": 0,
                "presets_with_trades": 0, "total_trades": 0,
            })
            continue
        best = rows[0]
        stock_summary.append({
            "symbol": symbol, "best_preset_id": best["preset_id"],
            "best_preset_name": best["preset_name"], "best_win_rate_pct": best["win_rate_pct"],
            "best_confidence_score": best["confidence_score"], "best_total_trades": best["total_trades"],
            "average_win_rate_pct": round(sum(item["win_rate_pct"] for item in rows) / len(rows), 2),
            "presets_with_trades": len(rows), "total_trades": sum(item["total_trades"] for item in rows),
        })
    stock_summary.sort(key=lambda item: (item["best_win_rate_pct"], item["best_total_trades"], item["best_confidence_score"], item["average_win_rate_pct"]), reverse=True)
    preset_summary: List[Dict[str, Any]] = []
    for preset in selected_presets:
        rows = [item for item in rankings if item["preset_id"] == preset["id"] and item["total_trades"] > 0]
        preset_summary.append({
            "preset_id": preset["id"], "preset_name": preset["name"], "category": preset["category"],
            "symbols_tested": len(rows),
            "average_win_rate_pct": round(sum(item["win_rate_pct"] for item in rows) / len(rows), 2) if rows else 0,
            "average_return_pct": round(sum(item["net_return_pct"] for item in rows) / len(rows), 2) if rows else 0,
            "profitable_symbols": sum(1 for item in rows if item["net_return_pct"] > 0),
            "strong_samples": sum(1 for item in rows if item["sample_quality"] == "strong"),
        })
    preset_summary.sort(key=lambda item: (item["average_win_rate_pct"], item["average_return_pct"]), reverse=True)
    errors = [{"symbol": output["symbol"], "message": output["error"]} for output in symbol_outputs if output.get("error")]
    return {
        "data_source": data_source, "symbols_requested": symbols_requested,
        "symbols_completed": len(symbol_outputs) - len(errors), "presets_tested": len(selected_presets),
        "combinations_tested": len(rankings), "workers": workers, "rankings": rankings,
        "reliable_rankings": reliable_rankings, "stock_summary": stock_summary,
        "preset_summary": preset_summary, "errors": errors[:100],
        "ranking_note": "Sorted by raw win rate descending. Trade count, sample quality, and confidence expose small-sample results.",
    }


def run_market_batch_backtest(
    *, start_date: date, end_date: date, preset_ids: Optional[List[str]] = None,
    symbols: Optional[List[str]] = None, data_source: str = "combined", max_workers: int = 8,
    initial_capital: float = 100000, fee_pct: float = 0.4, fixed_fee: float = 0,
    charge_model: str = "nepse_equity", investor_type: str = "individual",
    apply_cgt: bool = True, dp_charge: float = 25,
    slippage_pct: float = 0.1, position_size_pct: float = 100,
    min_holding_days: int = 0, max_holding_days: Optional[int] = None,
    trailing_stop_pct: Optional[float] = None, max_volume_participation_pct: float = 10,
    risk_free_rate_pct: float = 4, progress_callback: Optional[ProgressCallback] = None,
    completed_symbol_outputs: Optional[List[Dict[str, Any]]] = None,
    ordinary_shares_only: bool = True, indicator_engine_version: str = ENGINE_VERSION,
    max_listing_age_days: Optional[int] = None,
    min_volume: Optional[float] = None,
) -> Dict[str, Any]:
    preset_catalog = get_backtest_presets()
    requested_ids = set(preset_ids or [item["id"] for item in preset_catalog])
    selected_presets = [item for item in preset_catalog if item["id"] in requested_ids]
    if not selected_presets:
        raise BacktestError("Select at least one valid preset strategy.")
    universe = get_backtest_universe(
        start_date, end_date, symbols, ordinary_shares_only=ordinary_shares_only,
        max_listing_age_days=max_listing_age_days,
        min_volume=min_volume,
    )
    if not universe:
        raise BacktestError("No NEPSE symbols were found for the selected period.")
    clean_source = str(data_source or "combined").lower()
    if clean_source not in {"combined", "merolagani"}:
        raise BacktestError("Market scans require combined or merolagani as the data source.")
    cpu_limit = max(os.cpu_count() or 2, 2)
    workers = max(1, min(int(max_workers or 8), 12, cpu_limit))
    symbol_outputs = list(completed_symbol_outputs or [])
    completed_symbols = {output["symbol"] for output in symbol_outputs}
    remaining_symbols = [symbol for symbol in universe if symbol not in completed_symbols]
    combinations = sum(len(output.get("results", [])) for output in symbol_outputs)
    if progress_callback:
        progress_callback(len(symbol_outputs), len(universe), "", combinations, None)

    settings = {
        "initial_capital": initial_capital, "fee_pct": fee_pct, "fixed_fee": fixed_fee,
        "charge_model": charge_model, "investor_type": investor_type,
        "apply_cgt": apply_cgt, "dp_charge": dp_charge,
        "slippage_pct": slippage_pct, "position_size_pct": position_size_pct,
        "min_holding_days": min_holding_days, "max_holding_days": max_holding_days,
        "trailing_stop_pct": trailing_stop_pct,
        "max_volume_participation_pct": max_volume_participation_pct,
        "risk_free_rate_pct": risk_free_rate_pct,
    }
    tasks = [{
        "symbol": symbol, "start_date": start_date, "end_date": end_date,
        "data_source": clean_source, "presets": selected_presets, "settings": settings,
    } for symbol in remaining_symbols]
    if workers == 1:
        outputs = (_run_symbol_task(task) for task in tasks)
        for output in outputs:
            symbol_outputs.append(output)
            combinations += len(output.get("results", []))
            if progress_callback:
                progress_callback(len(symbol_outputs), len(universe), output["symbol"], combinations, output)
    elif tasks:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
            futures = {executor.submit(_run_symbol_task, task): task["symbol"] for task in tasks}
            for future in as_completed(futures):
                output = future.result()
                symbol_outputs.append(output)
                combinations += len(output.get("results", []))
                if progress_callback:
                    progress_callback(len(symbol_outputs), len(universe), output["symbol"], combinations, output)

    return build_batch_result(
        symbol_outputs=symbol_outputs, selected_presets=selected_presets,
        data_source=clean_source, symbols_requested=len(universe), workers=workers,
    )
