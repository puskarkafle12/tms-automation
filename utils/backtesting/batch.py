"""Multi-core NEPSE universe and multi-preset backtesting."""

from __future__ import annotations

import math
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, timedelta
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


def market_research_is_constrained() -> bool:
    """Protect interactive trading during NEPSE pre-open and continuous hours."""
    from utils.market_status import get_market_hours_status, get_nepal_now

    status = get_market_hours_status(get_nepal_now())
    return bool(status["is_pre_open"] or status["market_hours_open"])


def _positive_env_int(name: str, fallback: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(fallback))))
    except ValueError:
        return fallback


def _nonnegative_env_float(name: str, fallback: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(fallback))))
    except ValueError:
        return fallback


def background_chunk_delay_seconds() -> float:
    """Small yield between background scan chunks to protect web/API traffic."""
    return _nonnegative_env_float("BACKTEST_CHUNK_DELAY_SECONDS", 1.0)


def background_cache_worker_limit(requested_workers: int) -> int:
    """Limit DB/cache helper threads used by background scans."""
    configured = _positive_env_int("BACKTEST_CACHE_MAX_WORKERS", 1)
    return max(1, min(int(requested_workers or 1), configured))


def background_refresh_worker_limit(requested_workers: int) -> int:
    """Limit network tail-refresh helper threads used by background scans."""
    configured = _positive_env_int("BACKTEST_REFRESH_FETCH_WORKERS", 2)
    return max(1, min(int(requested_workers or 1), configured))


def background_worker_limit(
    requested_workers: Optional[int],
    *,
    market_constrained: Optional[bool] = None,
) -> int:
    """Choose a bounded CPU process count without starving interactive traffic.

    During NEPSE pre-open/live hours research defaults to one process. Outside
    that window it uses every spare CPU after the interactive reserve. Child
    processes retain a low OS priority and one BLAS thread, so API/database work
    can pre-empt research under load.
    """
    reserved_cpus = _positive_env_int("BACKTEST_RESERVED_CPUS", 1)
    available_cpus = max(1, (os.cpu_count() or 2) - reserved_cpus)
    constrained = market_research_is_constrained() if market_constrained is None else market_constrained
    raw_off_hours = os.getenv("BACKTEST_OFF_HOURS_MAX_WORKERS", "").strip()
    if constrained:
        phase_limit = _positive_env_int("BACKTEST_MARKET_MAX_WORKERS", 1)
    else:
        phase_limit = (
            _positive_env_int("BACKTEST_OFF_HOURS_MAX_WORKERS", available_cpus)
            if raw_off_hours
            else available_cpus
        )
    raw_global_limit = os.getenv("BACKTEST_MAX_WORKERS", "").strip()
    global_limit = (
        _positive_env_int("BACKTEST_MAX_WORKERS", available_cpus)
        if raw_global_limit
        else available_cpus if raw_off_hours else 1
    )
    configured_limit = min(phase_limit, global_limit)
    requested = max(1, int(requested_workers or configured_limit))
    return min(requested, configured_limit, available_cpus)


def background_turn_size(
    workers: int,
    *,
    market_constrained: Optional[bool] = None,
) -> int:
    """Return a fair stock quantum large enough to keep the process pool busy."""
    explicit = os.getenv("BACKTEST_ROUND_ROBIN_STOCKS_PER_TURN", "").strip()
    if explicit:
        return min(16, _positive_env_int("BACKTEST_ROUND_ROBIN_STOCKS_PER_TURN", 1))
    constrained = market_research_is_constrained() if market_constrained is None else market_constrained
    if constrained:
        return 1
    worker_count = max(1, int(workers))
    default_cap = worker_count
    raw_cap = os.getenv("BACKTEST_OFF_HOURS_STOCKS_PER_TURN", "").strip()
    cap = _positive_env_int("BACKTEST_OFF_HOURS_STOCKS_PER_TURN", default_cap) if raw_cap else default_cap
    return max(1, min(16, cap, max(1, worker_count * 2)))


def initialize_background_worker() -> None:
    """Lower OS scheduling priority for CPU-heavy child scan processes."""
    try:
        niceness = max(0, int(os.getenv("BACKTEST_WORKER_NICE", "5")))
        if niceness:
            os.nice(niceness)
    except (AttributeError, OSError, ValueError):
        # Niceness is a best-effort Linux/macOS optimization; scans still run
        # correctly on platforms that do not expose it.
        pass


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
        age_filter = """AND (
            SELECT MIN(history.session_date)
            FROM market_ohlcv_daily history
            WHERE history.symbol=d.symbol AND history.adjusted=TRUE
        ) >= :listing_cutoff""" if max_listing_age_days is not None else ""
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
            {"start_date": start_date, "end_date": end_date,
             "listing_cutoff": end_date - timedelta(days=max_listing_age_days) if max_listing_age_days is not None else None,
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
        defaults = dict(preset["defaults"])
        selected_exit_rule_id = preset.get("exit_rule_id")
        selected_exit_condition = preset.get("exit_condition")
        selected_atr_stop_multiple = None
        selected_break_even_trigger_pct = None
        protection_optimization: Optional[Dict[str, Any]] = None
        effective_trailing_stop_pct = (
            settings.get("trailing_stop_pct")
            if settings.get("trailing_stop_pct") is not None
            else defaults.get("trailing_stop_pct")
        )
        if (
            preset.get("component_ids")
            or preset.get("enforce_preset_holding")
            or settings.get("use_preset_holding_days")
        ):
            effective_min_holding_days = max(
                int(settings.get("min_holding_days") if settings.get("min_holding_days") is not None else 0),
                int(defaults.get("min_holding_days") or 0),
            )
            effective_max_holding_days = min(
                int(settings.get("max_holding_days") or 60), int(defaults["max_holding_days"]),
            )
        else:
            effective_min_holding_days = int(settings.get("min_holding_days") if settings.get("min_holding_days") is not None else defaults.get("min_holding_days") or 0)
            effective_max_holding_days = int(settings.get("max_holding_days") or defaults["max_holding_days"])
        if effective_min_holding_days > effective_max_holding_days:
            errors.append(f'{preset["id"]}: minimum holding days exceeds maximum holding days')
            continue
        custom_query_template = preset.get("custom_query_text")
        executable_query = (
            retarget_strategy_query(custom_query_template, [symbol])
            if custom_query_template else build_preset_query(
                preset, symbol,
                backtest_config={
                    **settings,
                    "stop_loss_pct": defaults["stop_loss_pct"],
                    "take_profit_pct": defaults["take_profit_pct"],
                    "min_holding_days": effective_min_holding_days,
                    "max_holding_days": effective_max_holding_days,
                    "trailing_stop_pct": effective_trailing_stop_pct,
                    "data_source": source,
                },
            )
        )
        try:
            entry_signals = None
            exit_signals = None
            if preset.get("force_condition_compiler"):
                from utils.backtesting.accelerated import (
                    compile_condition_signals, compile_preset_exit_signals,
                )
                entry_signals = compile_condition_signals(
                    str(preset["condition"]), prepared_rows,
                )
                if preset.get("exit_condition"):
                    exit_signals = compile_preset_exit_signals(preset["id"], prepared_rows)
            elif preset.get("component_ids"):
                from utils.backtesting.accelerated import compile_preset_signals
                component_signals = [
                    compile_preset_signals(component_id, prepared_rows, trigger_on_cross=False)
                    for component_id in preset["component_ids"]
                ]
                combined_state = [all(values) for values in zip(*component_signals)]
                gate_condition = str(preset.get("ipo_tradability_gate_condition") or "").strip()
                if preset.get("apply_ipo_tradability_gate") and gate_condition:
                    from utils.backtesting.accelerated import compile_condition_signals
                    gate_signals = compile_condition_signals(
                        gate_condition, prepared_rows, trigger_on_cross=False,
                    )
                    combined_state = [
                        bool(state and gate)
                        for state, gate in zip(combined_state, gate_signals)
                    ]
                entry_signals = combined_state.copy()
                for index in range(1, len(entry_signals)):
                    entry_signals[index] = combined_state[index] and not combined_state[index - 1]
                from utils.backtesting.strategy_discovery import compile_discovery_exit_signals
                exit_signals = compile_discovery_exit_signals(preset, prepared_rows)
            elif not custom_query_template:
                from utils.backtesting.accelerated import compile_preset_exit_signals, compile_preset_signals
                entry_signals = compile_preset_signals(preset["id"], prepared_rows)
                if preset.get("exit_condition"):
                    exit_signals = compile_preset_exit_signals(preset["id"], prepared_rows)
            output = run_backtest(
                symbol=symbol, query_text=executable_query,
                start_date=start_date, end_date=end_date, bars=bars,
                initial_capital=settings["initial_capital"], fee_pct=settings["fee_pct"],
                fixed_fee=settings["fixed_fee"], slippage_pct=settings["slippage_pct"],
                charge_model=settings["charge_model"], investor_type=settings["investor_type"],
                apply_cgt=settings["apply_cgt"], dp_charge=settings["dp_charge"],
                position_size_pct=settings["position_size_pct"],
                trailing_stop_pct=effective_trailing_stop_pct,
                max_volume_participation_pct=settings["max_volume_participation_pct"],
                risk_free_rate_pct=settings["risk_free_rate_pct"],
                stop_loss_pct=defaults["stop_loss_pct"],
                take_profit_pct=defaults["take_profit_pct"],
                min_holding_days=effective_min_holding_days,
                max_holding_days=effective_max_holding_days,
                prepared_rows=prepared_rows, compact=True, include_trades=professional,
                entry_signals=entry_signals,
                exit_signals=exit_signals,
            )
            # For each stock + entry strategy, select one protection champion
            # on the locked OOS segment. Losers remain embedded in the cached
            # evidence rather than becoming noisy recommendation rows.
            if (
                professional
                and not custom_query_template
                and entry_signals is not None
                and sum(bool(value) for value in entry_signals) >= 9
                and len(bars) >= 40
            ):
                from utils.backtesting.protection_optimizer import choose_protection_champion
                from utils.backtesting.strategy_discovery import EXIT_RULES, compile_discovery_exit_signals

                split_for_selection = max(1, min(len(bars) - 2, int(len(bars) * .70)))
                exit_signal_cache: Dict[str, List[bool]] = {}

                def evaluate_protection(
                    exit_rule_id: str, exit_condition: str, stop: Dict[str, Any],
                ) -> Dict[str, Any]:
                    candidate = {
                        **preset,
                        "exit_rule_id": exit_rule_id,
                        "exit_condition": exit_condition,
                        "defaults": {
                            **defaults,
                            "stop_loss_pct": stop["stop_loss_pct"],
                            "trailing_stop_pct": stop["trailing_stop_pct"],
                        },
                    }
                    candidate_query = build_preset_query(
                        candidate, symbol,
                        backtest_config={
                            **settings,
                            "stop_loss_pct": stop["stop_loss_pct"],
                            "take_profit_pct": defaults["take_profit_pct"],
                            "min_holding_days": effective_min_holding_days,
                            "max_holding_days": effective_max_holding_days,
                            "trailing_stop_pct": stop["trailing_stop_pct"],
                            "data_source": source,
                        },
                    )
                    candidate_exit = exit_signal_cache.setdefault(
                        exit_rule_id,
                        compile_discovery_exit_signals(
                            {"exit_rule_id": exit_rule_id},
                            prepared_rows,
                        ),
                    )
                    candidate_output = run_backtest(
                        symbol=symbol,
                        query_text=candidate_query,
                        start_date=date.fromisoformat(bars[split_for_selection].day),
                        end_date=end_date,
                        bars=bars[split_for_selection:],
                        prepared_rows=prepared_rows[split_for_selection:],
                        compact=True,
                        include_trades=False,
                        entry_signals=entry_signals[split_for_selection:],
                        exit_signals=candidate_exit[split_for_selection:],
                        initial_capital=settings["initial_capital"],
                        fee_pct=settings["fee_pct"],
                        fixed_fee=settings["fixed_fee"],
                        slippage_pct=settings["slippage_pct"],
                        charge_model=settings["charge_model"],
                        investor_type=settings["investor_type"],
                        apply_cgt=settings["apply_cgt"],
                        dp_charge=settings["dp_charge"],
                        position_size_pct=settings["position_size_pct"],
                        trailing_stop_pct=stop["trailing_stop_pct"],
                        atr_stop_multiple=stop["atr_stop_multiple"],
                        break_even_trigger_pct=stop["break_even_trigger_pct"],
                        max_volume_participation_pct=settings["max_volume_participation_pct"],
                        risk_free_rate_pct=settings["risk_free_rate_pct"],
                        stop_loss_pct=stop["stop_loss_pct"],
                        take_profit_pct=defaults["take_profit_pct"],
                        min_holding_days=effective_min_holding_days,
                        max_holding_days=effective_max_holding_days,
                    )
                    return dict(candidate_output["summary"])

                protection_optimization = choose_protection_champion(
                    EXIT_RULES,
                    evaluate_protection,
                    finalist_exit_count=4,
                )
                champion = protection_optimization["champion"]
                champion_stop = champion["stop"]
                selected_exit_rule_id = champion["exit_rule_id"]
                selected_exit_condition = champion["exit_condition"]
                defaults["stop_loss_pct"] = float(champion_stop["stop_loss_pct"])
                effective_trailing_stop_pct = champion_stop["trailing_stop_pct"]
                selected_atr_stop_multiple = champion_stop["atr_stop_multiple"]
                selected_break_even_trigger_pct = champion_stop["break_even_trigger_pct"]
                selected_preset = {
                    **preset,
                    "exit_rule_id": selected_exit_rule_id,
                    "exit_condition": selected_exit_condition,
                    "defaults": {
                        **defaults,
                        "trailing_stop_pct": effective_trailing_stop_pct,
                    },
                }
                executable_query = build_preset_query(
                    selected_preset, symbol,
                    backtest_config={
                        **settings,
                        "stop_loss_pct": defaults["stop_loss_pct"],
                        "take_profit_pct": defaults["take_profit_pct"],
                        "min_holding_days": effective_min_holding_days,
                        "max_holding_days": effective_max_holding_days,
                        "trailing_stop_pct": effective_trailing_stop_pct,
                        "data_source": source,
                    },
                )
                exit_signals = exit_signal_cache[selected_exit_rule_id]
                output = run_backtest(
                    symbol=symbol, query_text=executable_query,
                    start_date=start_date, end_date=end_date, bars=bars,
                    initial_capital=settings["initial_capital"], fee_pct=settings["fee_pct"],
                    fixed_fee=settings["fixed_fee"], slippage_pct=settings["slippage_pct"],
                    charge_model=settings["charge_model"], investor_type=settings["investor_type"],
                    apply_cgt=settings["apply_cgt"], dp_charge=settings["dp_charge"],
                    position_size_pct=settings["position_size_pct"],
                    trailing_stop_pct=effective_trailing_stop_pct,
                    atr_stop_multiple=selected_atr_stop_multiple,
                    break_even_trigger_pct=selected_break_even_trigger_pct,
                    max_volume_participation_pct=settings["max_volume_participation_pct"],
                    risk_free_rate_pct=settings["risk_free_rate_pct"],
                    stop_loss_pct=defaults["stop_loss_pct"],
                    take_profit_pct=defaults["take_profit_pct"],
                    min_holding_days=effective_min_holding_days,
                    max_holding_days=effective_max_holding_days,
                    prepared_rows=prepared_rows, compact=True, include_trades=professional,
                    entry_signals=entry_signals, exit_signals=exit_signals,
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
                    exit_signals=exit_signals[split:] if exit_signals is not None else None,
                    initial_capital=settings["initial_capital"], fee_pct=settings["fee_pct"],
                    fixed_fee=settings["fixed_fee"], slippage_pct=settings["slippage_pct"],
                    charge_model=settings["charge_model"], investor_type=settings["investor_type"],
                    apply_cgt=settings["apply_cgt"], dp_charge=settings["dp_charge"],
                    position_size_pct=settings["position_size_pct"],
                    trailing_stop_pct=effective_trailing_stop_pct,
                    atr_stop_multiple=selected_atr_stop_multiple,
                    break_even_trigger_pct=selected_break_even_trigger_pct,
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
                "trailing_stop_pct": effective_trailing_stop_pct,
                "atr_stop_multiple": selected_atr_stop_multiple,
                "break_even_trigger_pct": selected_break_even_trigger_pct,
                "min_holding_days": effective_min_holding_days,
                "max_holding_days": effective_max_holding_days, "preset_version": preset.get("version"),
                "preset_source_hash": preset.get("source_hash"), "period": output.get("period"),
                "data_source": output.get("data_source"), "summary": summary,
                "strategy_mode": "custom" if custom_query_template else "preset",
                "strategy_query": executable_query,
                "strategy_query_template": custom_query_template,
                "exit_rule_id": selected_exit_rule_id,
                "exit_condition": selected_exit_condition,
                "risk_strategy": (
                    "atr_volatility" if selected_atr_stop_multiple is not None
                    else "fixed_plus_break_even" if selected_break_even_trigger_pct is not None
                    else "fixed_plus_trailing" if effective_trailing_stop_pct is not None
                    else "fixed"
                ),
                "protection_optimization": protection_optimization,
                "protection_latest_values": {
                    key: prepared_rows[-1].get(key)
                    for key in (
                        "technical_sr_resistance_lower",
                        "technical_sr_resistance_upper",
                        "technical_bollinger_middle_20",
                        "technical_bollinger_upper_20",
                        "technical_fib_range_high_63",
                        "technical_atr_14",
                    )
                },
            },
            "trades": output["trades"] if professional else [],
            **professional_fields, **current_fields,
        })
        if selected_exit_condition:
            from utils.backtesting.strategy_discovery import build_discovery_sell_query
            results[-1]["assumptions"]["sell_strategy_query"] = build_discovery_sell_query({
                **preset,
                "exit_rule_id": selected_exit_rule_id,
                "exit_condition": selected_exit_condition,
            }, symbol)
    return {
        "symbol": symbol, "results": results,
        "market_profile": {
            "ltp": float(bars[-1].close), "latest_volume": float(bars[-1].volume),
            "average_volume_20": round(sum(float(bar.volume or 0) for bar in bars[-20:]) / max(len(bars[-20:]), 1), 2),
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


def _refresh_symbol_signals_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Refresh recent signals while preserving the completed historical backtest."""
    symbol = task["symbol"]
    start_date = task["start_date"]
    end_date = task["end_date"]
    source = task["data_source"]
    refresh_window = max(1, int(task.get("refresh_window_sessions") or 10))
    try:
        bars = (
            fetch_combined_snapshot_bars(symbol, start_date, end_date)
            if source == "combined"
            else fetch_historical_bars(symbol, start_date, end_date)
        )
    except BacktestError as exc:
        return {"symbol": symbol, "signal_refresh": True, "results": [], "error": str(exc)}

    # Indicators need warm-up history even though only the newest sessions are
    # being evaluated. This is local/cache work and does not replay trades.
    analysis_bars = bars[-max(260, refresh_window + 220):]
    prepared_rows = list(_historical_rows(symbol, analysis_bars))
    baselines = {str(item["preset_id"]): dict(item) for item in task.get("baselines") or []}
    updates: List[Dict[str, Any]] = []
    errors: List[str] = []
    for preset in task["presets"]:
        baseline = baselines.get(str(preset["id"]))
        if not baseline:
            errors.append(f'{preset["id"]}: historical baseline was not found')
            continue
        try:
            custom_query = preset.get("custom_query_text")
            if custom_query:
                from utils.backtesting.current_opportunities import evaluate_latest_completed_query
                evidence = evaluate_latest_completed_query(
                    custom_query, symbol, prepared_rows, strategy_name=preset["name"],
                )
            else:
                from utils.backtesting.current_opportunities import evaluate_latest_completed_signal
                evidence = evaluate_latest_completed_signal(preset, symbol, prepared_rows)
            active = bool(evidence.get("active"))
            technical_score = float(prepared_rows[-1].get("technical_signal_score") or 0)
            indicators_complete = all(prepared_rows[-1].get(field) is not None for field in (
                "technical_rsi_14", "technical_macd_histogram", "technical_adx_14",
            ))
            from utils.backtesting.current_opportunities import qualifies_default, reliability_score
            liquidity_score = float(baseline.get("liquidity_score") or 0)
            reliability = reliability_score(
                baseline,
                confidence_score=float(baseline.get("confidence_score") or 0),
                technical_score=technical_score,
                liquidity_score=liquidity_score,
                fresh=True,
                indicators_complete=indicators_complete,
            )
            qualified = qualifies_default(
                baseline, active=active, fresh=True,
                indicators_complete=indicators_complete, liquidity_score=liquidity_score,
            )
            near_trigger = bool(not active and evidence.get("near_trigger"))
            evidence.update({
                "signal_date": bars[-1].day,
                "calculated_from": "incremental_recent_sessions",
                "refresh_window_sessions": refresh_window,
                "data_fresh": True,
                "indicators_complete": indicators_complete,
                "liquidity_score": liquidity_score,
                "reliability": reliability,
                "default_requirements_passed": qualified,
            })
            updates.append({
                "preset_id": preset["id"],
                "current_signal_active": active,
                "current_signal_status": (
                    "strong_buy" if qualified else
                    "buy" if active and reliability["score"] >= 50 else
                    "watch" if active else "near_trigger" if near_trigger else "no_signal"
                ),
                "current_signal_date": bars[-1].day,
                "current_technical_score": technical_score,
                "reliability_score": reliability["score"],
                "current_evidence": evidence,
                "strong_buy_qualified": qualified,
            })
        except Exception as exc:
            errors.append(f'{preset["id"]}: {exc}')

    recent_volumes = [float(bar.volume or 0) for bar in bars[-20:]]
    return {
        "symbol": symbol,
        "signal_refresh": True,
        "results": updates,
        "market_profile": {
            "ltp": float(bars[-1].close),
            "latest_volume": float(bars[-1].volume),
            "average_volume_20": round(sum(recent_volumes) / max(len(recent_volumes), 1), 2),
            "median_volume_20": float(sorted(recent_volumes)[len(recent_volumes) // 2]),
            "average_turnover_20": round(
                sum(float(bar.close) * float(bar.volume or 0) for bar in bars[-20:])
                / max(len(bars[-20:]), 1), 2,
            ),
        },
        "technical_snapshot": {
            "as_of_date": bars[-1].day,
            "indicators": {
                key: value for key, value in prepared_rows[-1].items()
                if key.startswith("technical_")
            },
            "engine_version": ENGINE_VERSION,
            "bars_count": len(bars),
            "history_start": bars[0].day,
            "history_end": bars[-1].day,
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
    workers = min(background_worker_limit(max_workers), cpu_limit)
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
            delay = background_chunk_delay_seconds()
            if delay:
                time.sleep(delay)
    elif tasks:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=workers, mp_context=context, initializer=initialize_background_worker,
        ) as executor:
            futures = {executor.submit(_run_symbol_task, task): task["symbol"] for task in tasks}
            for future in as_completed(futures):
                output = future.result()
                symbol_outputs.append(output)
                combinations += len(output.get("results", []))
                if progress_callback:
                    progress_callback(len(symbol_outputs), len(universe), output["symbol"], combinations, output)
                delay = background_chunk_delay_seconds()
                if delay:
                    time.sleep(delay)

    return build_batch_result(
        symbol_outputs=symbol_outputs, selected_presets=selected_presets,
        data_source=clean_source, symbols_requested=len(universe), workers=workers,
    )
