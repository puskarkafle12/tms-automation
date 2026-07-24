"""PostgreSQL-leased v2 backtest worker and normalized result persistence."""

from __future__ import annotations

import json
import hashlib
import multiprocessing
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text

from utils.backtesting.batch import (
    _refresh_symbol_signals_task, _run_symbol_task, background_worker_limit, get_backtest_universe,
    initialize_background_worker,
)
from utils.backtesting.jobs import _symbol_metadata
from utils.backtesting.presets import get_backtest_presets
from utils.backtesting.professional import ROBUST_SCORE_VERSION, assign_robust_scores
from utils.backtesting.result_artifacts import load_symbol_artifacts, store_symbol_artifacts
from utils.backtesting.result_retention import (
    MIN_REVALIDATION_TRADES,
    MIN_REVALIDATION_WIN_RATE_PCT,
    is_retained_result,
)
from utils.backtesting.strategy_discovery import discovery_space_size, generate_discovery_presets
from utils.technical_indicators import ENGINE_VERSION
from utils.strategy_builder.strategy_parser import (
    StrategyQueryError,
    format_expression,
    format_strategy_query,
    parse_strategy_query,
)


BACKTEST_ENGINE_VERSION = "nepse-daily-v3-protection-champion"
ACTIVE_RUN_SQL = "deleted_at IS NULL AND archived_at IS NULL"
ARCHIVE_RETENTION_DAYS = 30
_WORKER_LOCK = threading.Lock()
_WORKER_STARTED = False
_WORKER_PROCESS: Optional[subprocess.Popen] = None
_REFRESH_WORKER_PROCESS: Optional[subprocess.Popen] = None
_WORKER_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
NEPAL_TZ = ZoneInfo("Asia/Kathmandu")
DAILY_REFRESH_HOURS = (10, 16)
RECOMMENDATION_REFRESH_SLOTS = ((10, 0), (12, 30), (15, 0), (16, 0))
_LAST_DAILY_REFRESH_SLOT: Optional[str] = None
_LAST_RECOMMENDATION_REFRESH_SLOT: Optional[str] = None
_LAST_ARCHIVE_PURGE_AT: Optional[float] = None
_LAST_REVALIDATION_ATTEMPT_AT: Optional[float] = None


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
    selected_min_holding = int(config.get("min_holding_days") if config.get("min_holding_days") is not None else 5)
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
            "max_holding_days": int(backtest.max_holding_days if backtest else config.get("max_holding_days") or 60),
        },
    }


def _session():
    from database import SessionLocal
    return SessionLocal()


def _result_configuration_hash(symbol: str, row: Dict[str, Any]) -> str:
    assumptions = dict(row.get("assumptions") or {})
    period = dict(assumptions.get("period") or {})
    def as_database_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    keys = (
        "preset_source_hash", "preset_version", "strategy_query", "sell_strategy_query",
        "strategy_query_template", "strategy_mode", "entry", "intraday_priority",
        "exit_rule_id", "exit_condition", "min_holding_days", "max_holding_days",
        "risk_strategy",
        "stop_loss_pct", "take_profit_pct", "trailing_stop_pct",
        "atr_stop_multiple", "break_even_trigger_pct", "charge_model",
        "investor_type", "capital_gains_tax_enabled", "fee_pct_each_side",
        "fixed_fee_each_order", "dp_charge_each_sell", "slippage_pct_each_side",
        "position_size_pct", "max_volume_participation_pct", "initial_capital",
        "brokerage_schedule", "risk_free_rate_pct",
    )
    values = [
        "simulation-identity-v2", symbol, as_database_text(row.get("preset_id")),
        as_database_text(row.get("evaluation_split") or "full"),
        BACKTEST_ENGINE_VERSION, ENGINE_VERSION,
        *(as_database_text(assumptions.get(key)) for key in keys),
        as_database_text(period.get("start")), as_database_text(assumptions.get("data_source")),
    ]
    return hashlib.md5("|".join(values).encode("utf-8")).hexdigest()


def _reuse_completed_shared_run(
    session, *, source_run_id: str, owner_id: str, scan_key: str,
    config: Dict[str, Any], snapshot_id: str,
) -> str:
    """Copy an identical normalized artifact into an owner-private workspace."""
    run_id = uuid.uuid4().hex
    source = session.execute(text("SELECT * FROM backtest_runs WHERE run_id=:run_id"), {"run_id": source_run_id}).mappings().one()
    session.execute(text("""
        INSERT INTO backtest_runs (
            run_id,owner_id,scan_key,name,notes,run_type,status,configuration,strategy_version,
            engine_version,indicator_engine_version,data_snapshot_id,symbols_completed,symbols_total,
            combinations_completed,progress_pct,current_symbol,created_at,started_at,finished_at,last_refresh_at,updated_at
        ) VALUES (
            :run_id,:owner_id,:scan_key,:name,:notes,:run_type,'completed',CAST(:configuration AS JSONB),:strategy_version,
            :engine_version,:indicator_version,:snapshot_id,:symbols_total,:symbols_total,
            :combinations,100,NULL,NOW(),NOW(),NOW(),NOW(),NOW()
        )
    """), {
        "run_id": run_id, "owner_id": owner_id, "scan_key": scan_key,
        "name": str(config.get("name") or "Cached NEPSE research")[:200], "notes": config.get("notes"),
        "run_type": config.get("run_type") or source["run_type"], "configuration": json.dumps(config),
        "strategy_version": source["strategy_version"], "engine_version": source["engine_version"],
        "indicator_version": source["indicator_engine_version"], "snapshot_id": snapshot_id,
        "symbols_total": int(source["symbols_total"] or 0), "combinations": int(source["combinations_completed"] or 0),
    })
    session.execute(text("""
        INSERT INTO backtest_run_symbols (
            run_id,symbol,security_type,sector,listing_age_days,ltp,latest_volume,average_volume_20,
            median_volume_20,average_turnover_20,status,bars_count,combinations_completed,error,
            started_at,completed_at,last_tested_session
        ) SELECT :new_run,symbol,security_type,sector,listing_age_days,ltp,latest_volume,average_volume_20,
                 median_volume_20,average_turnover_20,status,bars_count,combinations_completed,error,
                 NOW(),NOW(),last_tested_session
          FROM backtest_run_symbols WHERE run_id=:source_run
    """), {"new_run": run_id, "source_run": source_run_id})
    result_columns = [str(column) for column in session.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name='backtest_results'
          AND column_name NOT IN ('result_id','run_id') ORDER BY ordinal_position
    """)).scalars().all()]
    columns_sql = ",".join(result_columns)
    session.execute(text(
        f"INSERT INTO backtest_results (run_id,{columns_sql}) "
        f"SELECT :new_run,{columns_sql} FROM backtest_results "
        f"WHERE run_id=:source_run AND ((total_trades>=16 AND win_rate_pct>=50) "
        f"OR (total_trades>=9 AND win_rate_pct>=60))"
    ), {"new_run": run_id, "source_run": source_run_id})
    trade_columns = [str(column) for column in session.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name='backtest_trades'
          AND column_name NOT IN ('trade_id','result_id') ORDER BY ordinal_position
    """)).scalars().all()]
    trade_sql = ",".join(f"t.{column}" for column in trade_columns)
    session.execute(text(f"""
        INSERT INTO backtest_trades (result_id,{','.join(trade_columns)})
        SELECT destination.result_id,{trade_sql}
        FROM backtest_trades t
        JOIN backtest_results source ON source.result_id=t.result_id AND source.run_id=:source_run
        JOIN backtest_results destination ON destination.run_id=:new_run
             AND destination.symbol=source.symbol AND destination.preset_id=source.preset_id
             AND destination.evaluation_split=source.evaluation_split
    """), {"source_run": source_run_id, "new_run": run_id})
    session.execute(text("""
        INSERT INTO backtest_portfolio_results (run_id,preset_id,preset_name,summary,equity_curve,allocation_config,created_at)
        SELECT :new_run,preset_id,preset_name,summary,equity_curve,allocation_config,NOW()
        FROM backtest_portfolio_results WHERE run_id=:source_run
    """), {"new_run": run_id, "source_run": source_run_id})
    session.execute(text("""
        INSERT INTO backtest_canonical_results
            (owner_id,configuration_hash,result_id,run_id,symbol,security_type,data_session,updated_at)
        SELECT :owner_id,r.configuration_hash,r.result_id,r.run_id,r.symbol,s.security_type,
               r.current_signal_date,NOW()
        FROM backtest_results r
        JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol
        WHERE r.run_id=:run_id AND r.configuration_hash IS NOT NULL
          AND ((r.total_trades>=16 AND r.win_rate_pct>=50)
               OR (r.total_trades>=9 AND r.win_rate_pct>=60))
        ON CONFLICT (owner_id,configuration_hash) DO UPDATE SET
            result_id=EXCLUDED.result_id,
            run_id=EXCLUDED.run_id,
            symbol=EXCLUDED.symbol,
            security_type=EXCLUDED.security_type,
            data_session=EXCLUDED.data_session,
            updated_at=NOW()
        WHERE backtest_canonical_results.data_session IS NULL
           OR EXCLUDED.data_session>backtest_canonical_results.data_session
           OR (EXCLUDED.data_session=backtest_canonical_results.data_session
               AND EXCLUDED.result_id>backtest_canonical_results.result_id)
    """), {"owner_id": owner_id, "run_id": run_id})
    return run_id


def create_run(configuration: Dict[str, Any], *, owner_id: str = "local") -> Dict[str, Any]:
    config = dict(configuration)
    start = date.fromisoformat(str(config["start_date"]))
    end = date.fromisoformat(str(config["end_date"]))
    config["start_date"] = start.isoformat()
    config["end_date"] = end.isoformat()
    custom_query = str(config.get("custom_query_text") or "").strip()
    strategy_mode = str(config.get("strategy_mode") or "presets")
    if strategy_mode == "custom" and not custom_query:
        raise ValueError("Custom strategy mode requires a complete Strategy Language query.")
    if strategy_mode == "discovery":
        base_ids = config.get("discovery_base_ids") or config.get("preset_ids") or [item["id"] for item in get_backtest_presets()]
        selected = generate_discovery_presets(
            budget=int(config.get("discovery_budget") or 1000),
            seed=int(config.get("discovery_seed") or 20260718), base_ids=base_ids,
            min_holding_days=int(config.get("min_holding_days") if config.get("min_holding_days") is not None else 5),
            max_holding_days=int(config.get("max_holding_days") or 60),
        )
        config["strategy_mode"] = "discovery"
        config["discovery_base_ids"] = list(dict.fromkeys(base_ids))
        config["discovery_budget"] = len(selected)
        config["discovery_space_size"] = discovery_space_size(len(config["discovery_base_ids"]))
        config["preset_ids"] = []
    elif custom_query:
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
    # Ask for spare-core parallelism; background_worker_limit() still caps to
    # BACKTEST_MAX_WORKERS and always reserves CPU for API/dashboard traffic.
    config.setdefault("max_workers", 3)
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
    config.setdefault("min_holding_days", 5)
    config.setdefault("max_holding_days", 90)
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
        # Serialize creation of one owner's logical scan. This closes the race
        # between the lookup above and the partial unique index insert below.
        session.execute(text(
            "SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"
        ), {"identity": f"backtest-create:{owner_id}:{scan_key}"})
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
               WHERE owner_id=:owner_id AND scan_key=:scan_key AND deleted_at IS NULL AND archived_at IS NULL
               FOR UPDATE"""
        ), {"owner_id": owner_id, "scan_key": scan_key}).mappings().first()
        if not existing:
            # Adopt an exact pre-scan-key workspace instead of creating the first
            # post-upgrade duplicate. Missing/new strategy IDs intentionally make
            # a different identity.
            legacy_rows = session.execute(text(
                """SELECT run_id,status,configuration FROM backtest_runs
                   WHERE owner_id=:owner_id AND scan_key IS NULL AND deleted_at IS NULL AND archived_at IS NULL
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
        if not existing:
            shared = session.execute(text("""
                SELECT run_id,data_snapshot_id FROM backtest_runs
                WHERE owner_id<>:owner_id AND scan_key=:scan_key AND status='completed'
                  AND deleted_at IS NULL AND archived_at IS NULL AND data_snapshot_id IS NOT NULL
                  AND configuration->>'end_date'=:end_date
                  AND engine_version=:engine_version AND indicator_engine_version=:indicator_version
                ORDER BY finished_at DESC NULLS LAST LIMIT 1
            """), {
                "owner_id": owner_id, "scan_key": scan_key, "end_date": end.isoformat(),
                "engine_version": BACKTEST_ENGINE_VERSION, "indicator_version": ENGINE_VERSION,
            }).mappings().first()
            if shared:
                reused_run_id = _reuse_completed_shared_run(
                    session, source_run_id=str(shared["run_id"]), owner_id=owner_id,
                    scan_key=scan_key, config=config, snapshot_id=str(shared["data_snapshot_id"]),
                )
                session.commit()
                return get_run(reused_run_id, owner_id=owner_id)
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
    for key in ("created_at", "started_at", "finished_at", "updated_at", "heartbeat_at", "archived_at", "deleted_at", "last_refresh_at"):
        output[key] = output[key].isoformat() if output.get(key) else None
    output.pop("lease_owner", None)
    output.pop("lease_expires_at", None)
    output["has_results"] = int(output.get("combinations_completed") or 0) > 0
    archived_at = row.get("archived_at")
    if archived_at is not None:
        when = archived_at if getattr(archived_at, "tzinfo", None) else archived_at.replace(tzinfo=timezone.utc)
        expires = when + timedelta(days=ARCHIVE_RETENTION_DAYS)
        remaining = max(0, int((expires - datetime.now(timezone.utc)).total_seconds() // 86400))
        output["archive_expires_at"] = expires.isoformat()
        output["archive_days_remaining"] = remaining
    return output


def get_run(run_id: str, *, owner_id: str = "local") -> Dict[str, Any]:
    session = _session()
    try:
        row = session.execute(text(
            """SELECT * FROM backtest_runs
               WHERE run_id = :run_id AND owner_id = :owner_id AND deleted_at IS NULL AND archived_at IS NULL"""
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
            """SELECT * FROM backtest_runs WHERE owner_id=:owner_id AND deleted_at IS NULL AND archived_at IS NULL
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
        canonical_total = int(session.execute(text(
            """SELECT COUNT(*) FROM backtest_canonical_results canonical
               JOIN backtest_runs br ON br.run_id=canonical.run_id
               WHERE canonical.owner_id=:owner_id AND br.deleted_at IS NULL AND br.archived_at IS NULL"""
        ), {"owner_id": owner_id}).scalar() or 0)
        return {
            "items": unique[offset:offset + page_size], "page": page,
            "page_size": page_size, "total": total,
            "unique_configuration_total": canonical_total,
        }
    finally:
        session.close()


def _claim_next_run(*, refresh_only: bool = False) -> Optional[str]:
    session = _session()
    try:
        refresh_filter = (
            "AND COALESCE((configuration->>'incremental_refresh_active')::boolean,FALSE)=TRUE"
            if refresh_only
            else "AND COALESCE((configuration->>'incremental_refresh_active')::boolean,FALSE)=FALSE"
        )
        row = session.execute(text(
            f"""SELECT run_id FROM backtest_runs
               WHERE deleted_at IS NULL AND archived_at IS NULL AND cancel_requested = FALSE AND pause_requested = FALSE
                 AND (status = 'queued' OR (status = 'running' AND lease_expires_at < NOW()))
                 {refresh_filter}
               ORDER BY COALESCE(heartbeat_at,created_at),created_at
               FOR UPDATE SKIP LOCKED LIMIT 1"""
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


def _persist_symbol_output(
    run_id: str, output: Dict[str, Any], *, config: Dict[str, Any],
    presets: List[Dict[str, Any]], cache_results: bool = True,
) -> None:
    symbol = str(output["symbol"])
    session = _session()
    try:
        owner_id = str(session.execute(text(
            "SELECT owner_id FROM backtest_runs WHERE run_id=:run_id"
        ), {"run_id": run_id}).scalar_one())
        security_type = session.execute(text(
            "SELECT security_type FROM backtest_run_symbols WHERE run_id=:run_id AND symbol=:symbol"
        ), {"run_id": run_id, "symbol": symbol}).scalar()
        session.execute(text("DELETE FROM backtest_results WHERE run_id=:run_id AND symbol=:symbol"), {"run_id": run_id, "symbol": symbol})
        partial_rows = [dict(item) for item in (output.get("results") or [])]
        assign_robust_scores(partial_rows)
        if cache_results:
            store_symbol_artifacts(
                session, output={**output, "results": partial_rows}, presets=presets,
                config=config, engine_version=BACKTEST_ENGINE_VERSION,
                indicator_version=ENGINE_VERSION, owner_id=owner_id, source_run_id=run_id,
            )
        partial_rows = [row for row in partial_rows if is_retained_result(row)]
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
                    warning_codes,technical_snapshot,assumptions,configuration_hash)
                   VALUES (:run_id,:symbol,:preset_id,:preset_name,:preset_family,:category,'full',:bars,
                    :total_trades,:wins,:losses,:win_rate_pct,:win_rate_ci_low,:win_rate_ci_high,
                    :confidence_score,:robust_score,:net_return_pct,:max_drawdown_pct,:sharpe_ratio,
                    :sortino_ratio,:profit_factor,:expectancy_pct,:alpha_vs_benchmark_pct,:exposure_pct,
                    :average_holding_days,:oos_trades,:oos_win_rate_pct,:oos_return_pct,:oos_expectancy_pct,
                    :oos_sharpe_ratio,:oos_max_drawdown_pct,:walk_forward_profitable_pct,:p_value,:fdr_q_value,
                    :data_completeness_pct,:liquidity_score,:sample_quality,:recommendation_status,
                    :current_signal_active,:current_signal_status,:current_signal_date,:current_technical_score,
                    :reliability_score,:strong_buy_qualified,CAST(:current_evidence AS JSONB),
                    CAST(:warning_codes AS JSONB),CAST(:technical_snapshot AS JSONB),CAST(:assumptions AS JSONB),:configuration_hash)
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
                "configuration_hash": _result_configuration_hash(symbol, row),
                "warning_codes": json.dumps(row.get("warning_codes") or []),
                "current_evidence": json.dumps(row.get("current_evidence") or {}),
                "technical_snapshot": json.dumps({key: row.get(key) for key in ("technical_signal","technical_signal_score","technical_buy_score","technical_sell_score")}),
                "assumptions": json.dumps(row.get("assumptions") or {}),
            }).scalar_one()
            session.execute(text("""
                INSERT INTO backtest_canonical_results
                    (owner_id,configuration_hash,result_id,run_id,symbol,security_type,data_session,updated_at)
                VALUES (:owner_id,:configuration_hash,:result_id,:run_id,:symbol,:security_type,:data_session,NOW())
                ON CONFLICT (owner_id,configuration_hash) DO UPDATE SET
                    result_id=EXCLUDED.result_id,run_id=EXCLUDED.run_id,symbol=EXCLUDED.symbol,
                    security_type=EXCLUDED.security_type,data_session=EXCLUDED.data_session,updated_at=NOW()
                WHERE backtest_canonical_results.data_session IS NULL
                   OR EXCLUDED.data_session>backtest_canonical_results.data_session
                   OR (EXCLUDED.data_session=backtest_canonical_results.data_session
                       AND EXCLUDED.result_id>backtest_canonical_results.result_id)
            """), {
                "owner_id": owner_id,
                "run_id": run_id,
                "symbol": symbol,
                "security_type": security_type,
                "configuration_hash": _result_configuration_hash(symbol, row),
                "result_id": result_id,
                "data_session": row.get("current_signal_date"),
            })
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
            "count": len(partial_rows), "error": output.get("error"),
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


def _complete_unchanged_symbol(run_id: str, symbol: str) -> None:
    """Checkpoint an incremental cache hit without rewriting its results."""
    session = _session()
    try:
        session.execute(text(
            """UPDATE backtest_run_symbols
               SET status='completed',error=NULL,completed_at=NOW()
               WHERE run_id=:run_id AND symbol=:symbol"""
        ), {"run_id": run_id, "symbol": symbol})
        session.execute(text(
            """UPDATE backtest_runs
               SET symbols_completed=(
                     SELECT COUNT(*) FROM backtest_run_symbols
                     WHERE run_id=:run_id AND status IN ('completed','failed')
                   ),
                   current_symbol=:symbol,
                   progress_pct=ROUND((
                     100.0*(SELECT COUNT(*) FROM backtest_run_symbols
                            WHERE run_id=:run_id AND status IN ('completed','failed'))
                     / NULLIF(symbols_total,0)
                   )::numeric,1)::double precision,
                   heartbeat_at=NOW(),lease_expires_at=NOW()+INTERVAL '45 seconds',
                   updated_at=NOW()
               WHERE run_id=:run_id"""
        ), {"run_id": run_id, "symbol": symbol})
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _persist_signal_refresh(run_id: str, output: Dict[str, Any]) -> None:
    """Update recent signal fields without replacing historical metrics or trades."""
    symbol = str(output["symbol"])
    session = _session()
    try:
        technical_snapshot = dict(output.get("technical_snapshot") or {})
        for item in output.get("results") or []:
            session.execute(text("""
                UPDATE backtest_results
                SET current_signal_active=:current_signal_active,
                    current_signal_status=:current_signal_status,
                    current_signal_date=:current_signal_date,
                    current_technical_score=:current_technical_score,
                    reliability_score=:reliability_score,
                    current_evidence=CAST(:current_evidence AS JSONB),
                    strong_buy_qualified=:strong_buy_qualified,
                    technical_snapshot=CAST(:technical_snapshot AS JSONB)
                WHERE run_id=:run_id AND symbol=:symbol AND preset_id=:preset_id
            """), {
                **item,
                "run_id": run_id,
                "symbol": symbol,
                "current_evidence": json.dumps(item.get("current_evidence") or {}, default=str),
                "technical_snapshot": json.dumps(technical_snapshot, default=str),
            })
        profile = dict(output.get("market_profile") or {})
        status = "failed" if output.get("error") and not output.get("results") else "completed"
        session.execute(text("""
            UPDATE backtest_run_symbols
            SET status=:status,error=:error,completed_at=NOW(),
                bars_count=:bars,last_tested_session=:last_tested_session,
                ltp=COALESCE(:ltp,ltp),latest_volume=COALESCE(:latest_volume,latest_volume),
                average_volume_20=:average_volume_20,
                median_volume_20=:median_volume_20,
                average_turnover_20=:average_turnover_20
            WHERE run_id=:run_id AND symbol=:symbol
        """), {
            "status": status,
            "error": output.get("error"),
            "bars": int(technical_snapshot.get("bars_count") or 0),
            "last_tested_session": technical_snapshot.get("as_of_date"),
            "ltp": profile.get("ltp"),
            "latest_volume": profile.get("latest_volume"),
            "average_volume_20": profile.get("average_volume_20"),
            "median_volume_20": profile.get("median_volume_20"),
            "average_turnover_20": profile.get("average_turnover_20"),
            "run_id": run_id,
            "symbol": symbol,
        })
        session.execute(text("""
            UPDATE backtest_runs
            SET symbols_completed=(
                    SELECT COUNT(*) FROM backtest_run_symbols
                    WHERE run_id=:run_id AND status IN ('completed','failed')
                ),
                current_symbol=:symbol,
                progress_pct=ROUND((
                    100.0*(SELECT COUNT(*) FROM backtest_run_symbols
                           WHERE run_id=:run_id AND status IN ('completed','failed'))
                    / NULLIF(symbols_total,0)
                )::numeric,1)::double precision,
                heartbeat_at=NOW(),lease_expires_at=NOW()+INTERVAL '45 seconds',
                updated_at=NOW()
            WHERE run_id=:run_id
        """), {"run_id": run_id, "symbol": symbol})
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
        run_row = session.execute(text(
            "SELECT configuration,owner_id FROM backtest_runs WHERE run_id=:run_id"
        ), {"run_id": run_id}).mappings().one()
        configuration = dict(run_row["configuration"] or {})
        from utils.backtesting.portfolio import build_portfolios_for_run
        build_portfolios_for_run(session, run_id, configuration)
        session.commit()
        from utils.backtesting.recommendations import materialize_recommendations
        materialize_recommendations(session, owner_id=str(run_row["owner_id"]))
        session.commit()
    finally:
        session.close()


def run_claimed_run(run_id: str) -> None:
    session = _session()
    try:
        row = session.execute(text(
            "SELECT configuration,owner_id FROM backtest_runs WHERE run_id=:run_id"
        ), {"run_id": run_id}).mappings().one()
        config = dict(row["configuration"] or {})
        owner_id = str(row["owner_id"])
        symbol_rows = session.execute(text(
            """SELECT symbol,last_tested_session
               FROM backtest_run_symbols
               WHERE run_id=:run_id AND status='queued'
               ORDER BY symbol"""
        ), {"run_id": run_id}).mappings().all()
        try:
            turn_size = max(1, min(4, int(os.getenv("BACKTEST_ROUND_ROBIN_STOCKS_PER_TURN", "1"))))
        except ValueError:
            turn_size = 1
        symbol_rows = symbol_rows[:turn_size]
        symbols = [str(item["symbol"]) for item in symbol_rows]
        last_tested_by_symbol = {
            str(item["symbol"]): item["last_tested_session"] for item in symbol_rows
        }
    finally:
        session.close()
    if config.get("strategy_mode") == "custom" and config.get("custom_strategy"):
        presets = [dict(config["custom_strategy"])]
    elif config.get("strategy_mode") == "discovery":
        presets = generate_discovery_presets(
            budget=int(config.get("discovery_budget") or 1000),
            seed=int(config.get("discovery_seed") or 20260718),
            base_ids=config.get("discovery_base_ids") or [],
            min_holding_days=int(config.get("min_holding_days") if config.get("min_holding_days") is not None else 5),
            max_holding_days=int(config.get("max_holding_days") or 60),
        )
        # A parser/compiler failure may have checkpointed a symbol with only a
        # fraction of the requested discovery candidates. Requeue those
        # checkpoints and reuse their valid artifacts instead of accepting an
        # incomplete stock as finished.
        repair_session = _session()
        try:
            repair_session.execute(text(
                """UPDATE backtest_run_symbols
                   SET status='queued',completed_at=NULL,error=NULL
                   WHERE run_id=:run_id AND status='completed'
                     AND combinations_completed < :expected"""
            ), {"run_id": run_id, "expected": len(presets)})
            symbols = repair_session.execute(text(
                "SELECT symbol FROM backtest_run_symbols WHERE run_id=:run_id AND status NOT IN ('completed') ORDER BY symbol"
            ), {"run_id": run_id}).scalars().all()
            repair_session.commit()
        except Exception:
            repair_session.rollback()
            raise
        finally:
            repair_session.close()
    else:
        presets = [item for item in get_backtest_presets() if item["id"] in set(config.get("preset_ids") or [])]
    incremental_refresh = bool(
        config.get("incremental_refresh_active")
        or config.get("refresh_window_sessions")
        or config.get("refresh_discover_new_data")
    )
    if config.get("refresh_discover_new_data"):
        # Probe only the missing tail before consulting result artifacts. The
        # history fetcher keeps one overlap session for upstream corrections,
        # while unchanged symbols retain the same artifact key and finish from
        # cache without replaying any strategy.
        from utils.backtesting.service import fetch_historical_bars

        refresh_workers = min(
            8,
            max(1, int(os.getenv("BACKTEST_REFRESH_FETCH_WORKERS", "4"))),
        )

        def refresh_tail(symbol: str) -> None:
            if str(config.get("data_source") or "merolagani") == "merolagani":
                fetch_historical_bars(
                    str(symbol),
                    date.fromisoformat(config["start_date"]),
                    date.fromisoformat(config["end_date"]),
                    force_tail_refresh=True,
                )

        with ThreadPoolExecutor(
            max_workers=refresh_workers,
            thread_name_prefix="backtest-tail-refresh",
        ) as refresh_executor:
            refresh_futures = {
                refresh_executor.submit(refresh_tail, str(symbol)): str(symbol)
                for symbol in symbols
            }
            for completed_count, future in enumerate(as_completed(refresh_futures), start=1):
                try:
                    future.result()
                except Exception:
                    # The normal symbol task retries failed fetches and records a
                    # per-symbol error without aborting the rest of the workspace.
                    pass
                if completed_count == 1 or completed_count % 10 == 0:
                    _control_state(run_id)
        config["refresh_discover_new_data"] = False
        refresh_session = _session()
        try:
            refresh_session.execute(text(
                """UPDATE backtest_runs
                   SET configuration=CAST(:configuration AS JSONB),started_at=NOW(),
                       heartbeat_at=NOW(),lease_expires_at=NOW()+INTERVAL '45 seconds',
                       updated_at=NOW()
                   WHERE run_id=:run_id"""
            ), {"run_id": run_id, "configuration": json.dumps(config)})
            refresh_session.commit()
        finally:
            refresh_session.close()
    settings = {
        "initial_capital": float(config.get("initial_capital") or 100000),
        "charge_model": str(config.get("charge_model") or "nepse_equity"),
        "investor_type": str(config.get("investor_type") or "individual"),
        "apply_cgt": bool(config.get("apply_cgt", True)),
        "dp_charge": float(config.get("dp_charge") if config.get("dp_charge") is not None else 25),
        "fee_pct": float(config.get("fee_pct") or .4), "fixed_fee": float(config.get("fixed_fee") or 0),
        "slippage_pct": float(config.get("slippage_pct") or .1),
        "position_size_pct": float(config.get("position_size_pct") or 100),
        "min_holding_days": int(config.get("min_holding_days") if config.get("min_holding_days") is not None else 5),
        "max_holding_days": int(config["max_holding_days"]) if config.get("max_holding_days") is not None else None,
        "trailing_stop_pct": config.get("trailing_stop_pct"),
        "max_volume_participation_pct": float(config.get("max_volume_participation_pct") or 10),
        "risk_free_rate_pct": float(config.get("risk_free_rate_pct") or 4), "professional": True,
    }
    tasks: List[Dict[str, Any]] = []
    cached_by_symbol: Dict[str, Dict[str, Any]] = {}
    cache_session = _session()
    try:
        refresh_strategies = dict(config.get("refresh_strategies") or {})
        for symbol in symbols:
            selected_preset_ids = {str(value) for value in refresh_strategies.get(str(symbol), [])}
            target_presets = (
                [preset for preset in presets if str(preset["id"]) in selected_preset_ids]
                if incremental_refresh and refresh_strategies else presets
            )
            cached = load_symbol_artifacts(
                cache_session, symbol=str(symbol), presets=target_presets, config=config,
                engine_version=BACKTEST_ENGINE_VERSION, indicator_version=ENGINE_VERSION,
                owner_id=owner_id, source_run_id=run_id,
            )
            cached_by_symbol[str(symbol)] = cached
            missing = list(cached["missing"])
            cached_session = cached.get("data_session")
            last_tested = last_tested_by_symbol.get(str(symbol))
            if incremental_refresh:
                if cached_session and (not last_tested or cached_session > last_tested):
                    baselines = [dict(item) for item in cache_session.execute(text("""
                        SELECT preset_id,total_trades,win_rate_pct,net_return_pct,profit_factor,
                               sharpe_ratio,max_drawdown_pct,confidence_score,liquidity_score
                        FROM backtest_results
                        WHERE run_id=:run_id AND symbol=:symbol
                    """), {"run_id": run_id, "symbol": str(symbol)}).mappings().all()]
                    baseline_ids = {str(item["preset_id"]) for item in baselines}
                    if target_presets and all(str(preset["id"]) in baseline_ids for preset in target_presets):
                        tasks.append({
                            "symbol": symbol,
                            "start_date": date.fromisoformat(config["start_date"]),
                            "end_date": date.fromisoformat(config["end_date"]),
                            "data_source": config.get("data_source") or "merolagani",
                            "presets": target_presets,
                            "baselines": [item for item in baselines if str(item["preset_id"]) in {str(preset["id"]) for preset in target_presets}],
                            "refresh_window_sessions": int(config.get("refresh_window_sessions") or 10),
                            "signal_refresh": True,
                        })
                        continue
                # Incremental refresh never replays historical trades. If there
                # is no complete baseline/new cache context, preserve the old
                # checkpoint and leave full evaluation to an explicit new run.
                cached["preserve_baseline"] = True
                continue
            if missing:
                tasks.append({
                    "symbol": symbol, "start_date": date.fromisoformat(config["start_date"]),
                    "end_date": date.fromisoformat(config["end_date"]),
                    "data_source": config.get("data_source") or "merolagani",
                    "presets": missing, "settings": settings,
                })
        cache_session.commit()
    except Exception:
        cache_session.rollback()
        raise
    finally:
        cache_session.close()
    # Always allow the current deployment worker cap, even when an older run
    # stored max_workers=1. Reserved CPUs still protect API/dashboard traffic.
    workers = (
        1 if incremental_refresh
        else background_worker_limit(max(int(config.get("max_workers") or 1), 3))
    )
    signal_refresh_symbols = {
        str(task["symbol"]) for task in tasks if task.get("signal_refresh")
    }
    results_changed = False
    signals_changed = False
    try:
        # Complete cache-only symbols immediately so partial tables update without
        # waiting for the process pool or recomputing any historical combination.
        cache_only_outputs: List[tuple[str, Dict[str, Any], bool]] = []
        for symbol in symbols:
            if str(symbol) in signal_refresh_symbols:
                continue
            cached = cached_by_symbol[str(symbol)]
            cached_session = cached.get("data_session")
            last_tested = last_tested_by_symbol.get(str(symbol))
            unchanged = bool(
                incremental_refresh and (
                    cached.get("preserve_baseline")
                    or (last_tested and (not cached_session or cached_session <= last_tested))
                )
            )
            if cached["missing"] and not unchanged:
                continue
            cache_only_outputs.append((str(symbol), cached, unchanged))

        def persist_cached(item: tuple[str, Dict[str, Any], bool]) -> bool:
            symbol, cached, unchanged = item
            if unchanged:
                _complete_unchanged_symbol(run_id, symbol)
                return False
            _persist_symbol_output(
                run_id, {
                    "symbol": symbol, "results": cached["results"],
                    "market_profile": cached["market_profile"],
                    "technical_snapshot": cached["technical_snapshot"], "error": None,
                }, config=config, presets=[], cache_results=False,
            )
            return True

        if cache_only_outputs:
            # DB/checkpoint writes are I/O bound; a small thread pool finishes
            # unchanged stocks quickly without adding strategy CPU load.
            cache_workers = min(4, max(1, len(cache_only_outputs)))
            with ThreadPoolExecutor(max_workers=cache_workers, thread_name_prefix="backtest-cache") as cache_executor:
                for changed in cache_executor.map(persist_cached, cache_only_outputs):
                    if changed:
                        results_changed = True
        if tasks:
            context = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=workers, mp_context=context, initializer=initialize_background_worker,
            ) as executor:
                futures = {
                    executor.submit(
                        _refresh_symbol_signals_task if task.get("signal_refresh") else _run_symbol_task,
                        task,
                    ): task
                    for task in tasks
                }
                for future in as_completed(futures):
                    control = _control_state(run_id)
                    if control["cancel"] or control["pause"]:
                        for pending in futures:
                            pending.cancel()
                        break
                    try:
                        output = future.result()
                    except Exception as exc:
                        task = futures[future]
                        output = {
                            "symbol": task["symbol"],
                            "signal_refresh": bool(task.get("signal_refresh")),
                            "results": [],
                            "error": str(exc),
                        }
                    if output.get("signal_refresh"):
                        _persist_signal_refresh(run_id, output)
                        signals_changed = signals_changed or bool(output.get("results"))
                        continue
                    cached = cached_by_symbol[str(output["symbol"])]
                    computed = [dict(item) for item in (output.get("results") or [])]
                    merged = {
                        **output,
                        "results": [*cached["results"], *computed],
                        "market_profile": output.get("market_profile") or cached["market_profile"],
                        "technical_snapshot": output.get("technical_snapshot") or cached["technical_snapshot"],
                    }
                    _persist_symbol_output(
                        run_id, merged, config=config, presets=list(cached["missing"]),
                        cache_results=bool(computed),
                    )
                    results_changed = True
        control = _control_state(run_id)
        session = _session()
        try:
            config["round_robin_results_changed"] = bool(
                config.get("round_robin_results_changed") or results_changed
            )
            config["round_robin_signals_changed"] = bool(
                config.get("round_robin_signals_changed") or signals_changed
            )
            remaining = int(session.execute(text("""
                SELECT COUNT(*) FROM backtest_run_symbols
                WHERE run_id=:run_id AND status='queued'
            """), {"run_id": run_id}).scalar() or 0)
            if control["cancel"]:
                status = "cancelled"
            elif control["pause"]:
                status = "paused"
            elif remaining:
                # Release the lease after a small stock quantum. Ordering by the
                # prior heartbeat gives every queued workspace a round-robin turn.
                status = "queued"
            else:
                if not incremental_refresh or config["round_robin_results_changed"]:
                    _finalize_scores(run_id)
                elif config["round_robin_signals_changed"]:
                    from utils.backtesting.recommendations import materialize_recommendations
                    refresh_results_session = _session()
                    try:
                        owner_id = str(refresh_results_session.execute(text(
                            "SELECT owner_id FROM backtest_runs WHERE run_id=:run_id"
                        ), {"run_id": run_id}).scalar_one())
                        materialize_recommendations(refresh_results_session, owner_id=owner_id)
                        refresh_results_session.commit()
                    finally:
                        refresh_results_session.close()
                status = "completed"
            if status == "completed" and incremental_refresh:
                config["incremental_refresh_active"] = False
                config["refresh_discover_new_data"] = False
                config.pop("refresh_window_sessions", None)
                config.pop("refresh_symbols", None)
                config.pop("refresh_strategies", None)
            if status == "completed":
                config.pop("round_robin_results_changed", None)
                config.pop("round_robin_signals_changed", None)
            session.execute(text(
                """UPDATE backtest_runs SET status=:status,progress_pct=CASE WHEN :status='completed' THEN 100 ELSE progress_pct END,
                          current_symbol=CASE WHEN :status='queued' THEN current_symbol ELSE NULL END,
                          finished_at=CASE WHEN :status IN ('completed','cancelled') THEN NOW() ELSE finished_at END,
                          last_refresh_at=CASE WHEN :status='completed' THEN NOW() ELSE last_refresh_at END,
                          configuration=CAST(:configuration AS JSONB),
                          lease_owner=NULL,lease_expires_at=NULL,updated_at=NOW()
                   WHERE run_id=:run_id"""
            ), {"status": status, "run_id": run_id, "configuration": json.dumps(config)})
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


def _queue_incremental_refresh(
    session,
    *,
    run_id: str,
    config: Dict[str, Any],
    refresh_slot: Optional[str] = None,
    symbols: Optional[List[str]] = None,
    strategies: Optional[Dict[str, List[str]]] = None,
) -> None:
    """Queue one workspace to discover new tails and reuse unchanged artifacts."""
    today = datetime.now(NEPAL_TZ).date()
    configured_end = date.fromisoformat(str(config.get("end_date") or today.isoformat()))
    config["end_date"] = max(configured_end, today).isoformat()
    config["refresh_discover_new_data"] = True
    config["incremental_refresh_active"] = True
    config["refresh_window_sessions"] = 10
    if refresh_slot:
        config["last_refresh_slot"] = refresh_slot
    normalized_strategies = {
        str(symbol).strip().upper(): sorted({str(preset_id) for preset_id in preset_ids if str(preset_id)})
        for symbol, preset_ids in (strategies or {}).items() if str(symbol).strip()
    }
    normalized_strategies = {symbol: preset_ids for symbol, preset_ids in normalized_strategies.items() if preset_ids}
    selected = sorted({
        str(symbol).strip().upper()
        for symbol in [*(symbols or []), *normalized_strategies]
        if str(symbol).strip()
    })
    if selected:
        available = set(session.execute(text(
            "SELECT symbol FROM backtest_run_symbols WHERE run_id=:run_id AND symbol=ANY(CAST(:symbols AS TEXT[]))"
        ), {"run_id": run_id, "symbols": selected}).scalars().all())
        selected = [symbol for symbol in selected if symbol in available]
        if not selected:
            raise ValueError("No filtered symbols belong to this backtest workspace.")
        config["refresh_symbols"] = selected
        if normalized_strategies:
            config["refresh_strategies"] = {
                symbol: normalized_strategies[symbol]
                for symbol in selected if symbol in normalized_strategies
            }
        else:
            config.pop("refresh_strategies", None)
    else:
        config.pop("refresh_symbols", None)
        config.pop("refresh_strategies", None)
    session.execute(text(
        """UPDATE backtest_run_symbols
           SET status='queued',error=NULL,completed_at=NULL
           WHERE run_id=:run_id AND (:refresh_all OR symbol=ANY(CAST(:symbols AS TEXT[])))"""
    ), {"run_id": run_id, "refresh_all": not selected, "symbols": selected})
    session.execute(text(
        """UPDATE backtest_runs
           SET status='queued',configuration=CAST(:configuration AS JSONB),
               symbols_completed=(SELECT COUNT(*) FROM backtest_run_symbols WHERE run_id=:run_id AND status IN ('completed','failed')),
               symbols_total=(SELECT COUNT(*) FROM backtest_run_symbols WHERE run_id=:run_id),
               progress_pct=ROUND((100.0*(SELECT COUNT(*) FROM backtest_run_symbols WHERE run_id=:run_id AND status IN ('completed','failed'))/NULLIF((SELECT COUNT(*) FROM backtest_run_symbols WHERE run_id=:run_id),0))::numeric,1)::double precision,
               current_symbol=NULL,cancel_requested=FALSE,
               pause_requested=FALSE,error_summary=NULL,started_at=NULL,finished_at=NULL,
               heartbeat_at=NULL,lease_owner=NULL,lease_expires_at=NULL,updated_at=NOW()
           WHERE run_id=:run_id"""
    ), {"run_id": run_id, "configuration": json.dumps(config)})


def refresh_run_incrementally(
    run_id: str, *, owner_id: str = "local", symbols: Optional[List[str]] = None,
    strategies: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Request a fast refresh that replays only symbols whose data changed."""
    session = _session()
    try:
        row = session.execute(text(
            """SELECT run_id,status,configuration
               FROM backtest_runs
               WHERE run_id=:run_id AND owner_id=:owner_id AND deleted_at IS NULL AND archived_at IS NULL
               FOR UPDATE"""
        ), {"run_id": run_id, "owner_id": owner_id}).mappings().first()
        if not row:
            raise ValueError("Backtest workspace was not found.")
        config = dict(row["configuration"] or {})
        incoming_strategies = {
            str(symbol).strip().upper(): sorted({str(preset_id) for preset_id in preset_ids if str(preset_id)})
            for symbol, preset_ids in (strategies or {}).items() if str(symbol).strip()
        }
        incoming_strategies = {
            symbol: preset_ids for symbol, preset_ids in incoming_strategies.items() if preset_ids
        }
        if row["status"] in {"queued", "running", "paused"}:
            # Reuse the same workspace card. Merge filtered strategies into the
            # active refresh instead of spawning another run entry.
            if incoming_strategies and bool(config.get("incremental_refresh_active")):
                existing = {
                    str(symbol).strip().upper(): sorted({str(preset_id) for preset_id in (preset_ids or []) if str(preset_id)})
                    for symbol, preset_ids in dict(config.get("refresh_strategies") or {}).items()
                }
                merged = dict(existing)
                for symbol, preset_ids in incoming_strategies.items():
                    merged[symbol] = sorted(set(merged.get(symbol, [])) | set(preset_ids))
                selected = sorted(merged)
                config["refresh_strategies"] = merged
                config["refresh_symbols"] = selected
                config["refresh_discover_new_data"] = True
                config["incremental_refresh_active"] = True
                config["refresh_window_sessions"] = int(config.get("refresh_window_sessions") or 10)
                session.execute(text("""
                    UPDATE backtest_run_symbols
                    SET status='queued',error=NULL,completed_at=NULL
                    WHERE run_id=:run_id AND symbol=ANY(CAST(:symbols AS TEXT[]))
                """), {"run_id": run_id, "symbols": selected})
                session.execute(text("""
                    UPDATE backtest_runs
                    SET configuration=CAST(:configuration AS JSONB),updated_at=NOW()
                    WHERE run_id=:run_id
                """), {"run_id": run_id, "configuration": json.dumps(config)})
                session.commit()
                return get_run(run_id, owner_id=owner_id)
            session.rollback()
            return get_run(run_id, owner_id=owner_id)
        _queue_incremental_refresh(
            session,
            run_id=run_id,
            config=config,
            refresh_slot=f"manual:{datetime.now(NEPAL_TZ).isoformat(timespec='seconds')}",
            symbols=symbols,
            strategies=strategies,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return get_run(run_id, owner_id=owner_id)


def refresh_runs_incrementally_for_selections(
    selections: List[Dict[str, str]], *, owner_id: str = "local",
    preferred_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Queue exact filtered strategies on one reusable workspace card."""
    requested: Dict[str, Dict[str, List[str]]] = {}
    for item in selections:
        run_id = str(item.get("run_id") or "")
        symbol = str(item.get("symbol") or "").strip().upper()
        preset_id = str(item.get("preset_id") or "")
        if not run_id or not symbol or not preset_id:
            continue
        requested.setdefault(run_id, {}).setdefault(symbol, []).append(preset_id)
    if not requested:
        raise ValueError("The finalized filters do not match any strategies.")
    session = _session()
    try:
        rows = session.execute(text("""
            SELECT run_id,scan_key,status,updated_at
            FROM backtest_runs
            WHERE owner_id=:owner_id AND deleted_at IS NULL AND archived_at IS NULL
              AND run_id=ANY(CAST(:run_ids AS TEXT[]))
            ORDER BY updated_at DESC
        """), {"owner_id": owner_id, "run_ids": list(requested)}).mappings().all()
        preferred = str(preferred_run_id or "")
        preferred_row = None
        if preferred:
            preferred_row = session.execute(text("""
                SELECT run_id,scan_key,status,updated_at FROM backtest_runs
                WHERE owner_id=:owner_id AND deleted_at IS NULL AND archived_at IS NULL
                  AND run_id=:run_id
            """), {"owner_id": owner_id, "run_id": preferred}).mappings().first()
        # Prefer the currently selected workspace so the same refresh never opens
        # another run card. Otherwise keep one workspace per scan identity.
        chosen: Dict[str, str] = {}
        if preferred_row is not None:
            key = str(preferred_row["scan_key"] or preferred_row["run_id"])
            chosen[key] = str(preferred_row["run_id"])
        for row in rows:
            key = str(row["scan_key"] or row["run_id"])
            if key in chosen:
                continue
            if str(row["status"]) in {"queued", "running", "paused"}:
                chosen[key] = str(row["run_id"])
        for row in rows:
            key = str(row["scan_key"] or row["run_id"])
            if key not in chosen and str(row["status"]) in {"completed", "cancelled", "failed"}:
                chosen[key] = str(row["run_id"])
        # Remap every filtered strategy onto the chosen workspace for that scan.
        chosen_ids = set(chosen.values())
        run_meta = {str(row["run_id"]): str(row["scan_key"] or row["run_id"]) for row in rows}
        if preferred_row is not None:
            run_meta[str(preferred_row["run_id"])] = str(preferred_row["scan_key"] or preferred_row["run_id"])
        grouped: Dict[str, Dict[str, List[str]]] = {}
        for source_run, strategy_map in requested.items():
            target = chosen.get(run_meta.get(source_run, source_run))
            if not target:
                continue
            dest = grouped.setdefault(target, {})
            for symbol, preset_ids in strategy_map.items():
                dest.setdefault(symbol, []).extend(preset_ids)
        # If the preferred workspace can host the symbols, collapse everything there.
        if preferred_row is not None:
            preferred_id = str(preferred_row["run_id"])
            available = set(session.execute(text("""
                SELECT symbol FROM backtest_run_symbols WHERE run_id=:run_id
            """), {"run_id": preferred_id}).scalars().all())
            collapsed: Dict[str, List[str]] = {}
            for strategy_map in requested.values():
                for symbol, preset_ids in strategy_map.items():
                    if symbol in available:
                        collapsed.setdefault(symbol, []).extend(preset_ids)
            if collapsed:
                grouped = {preferred_id: collapsed}
    finally:
        session.close()
    if not grouped:
        raise ValueError("No filtered strategies belong to an existing workspace.")
    queued: List[str] = []
    already_active: List[str] = []
    for candidate, strategy_map in grouped.items():
        before = get_run(candidate, owner_id=owner_id)
        was_active = before.get("status") in {"queued", "running", "paused"}
        scoped = refresh_run_incrementally(
            candidate, owner_id=owner_id, strategies=strategy_map,
        )
        if scoped.get("status") in {"queued", "running"}:
            queued.append(candidate)
            if was_active:
                already_active.append(candidate)
    symbols = sorted({symbol for mapping in grouped.values() for symbol in mapping})
    strategy_count = sum(len(set(ids)) for mapping in grouped.values() for ids in mapping.values())
    return {
        "symbols": symbols, "symbol_count": len(symbols), "strategy_count": strategy_count,
        "runs_queued": len(queued), "run_ids": queued, "reused_runs": already_active,
        "created_new_run": False,
    }


def refresh_runs_incrementally_for_symbols(
    symbols: List[str], *, owner_id: str = "local",
) -> Dict[str, Any]:
    """Queue recent-data refreshes only in completed workspaces containing filtered symbols."""
    selected = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    if not selected:
        raise ValueError("The finalized filters do not match any symbols.")
    session = _session()
    try:
        run_ids = [str(value) for value in session.execute(text("""
            SELECT DISTINCT br.run_id
            FROM backtest_runs br
            JOIN backtest_run_symbols s ON s.run_id=br.run_id
            WHERE br.owner_id=:owner_id AND br.deleted_at IS NULL AND br.archived_at IS NULL
              AND br.status IN ('completed','cancelled','failed')
              AND s.symbol=ANY(CAST(:symbols AS TEXT[]))
            ORDER BY br.run_id
        """), {"owner_id": owner_id, "symbols": selected}).scalars().all()]
    finally:
        session.close()
    queued = []
    for candidate in run_ids:
        scoped = refresh_run_incrementally(candidate, owner_id=owner_id, symbols=selected)
        if scoped.get("status") in {"queued", "running"}:
            queued.append(candidate)
    return {"symbols": selected, "symbol_count": len(selected), "runs_queued": len(queued), "run_ids": queued}


def _queue_scheduled_refreshes() -> int:
    """Resume continuing scans pre-market and after close when newer data exists."""
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
            """SELECT DISTINCT ON (COALESCE(scan_key,run_id))
                      run_id,owner_id,COALESCE(scan_key,run_id) AS scan_group,configuration,status
               FROM backtest_runs
               WHERE deleted_at IS NULL AND archived_at IS NULL AND COALESCE((configuration->>'auto_refresh')::boolean,TRUE)=TRUE
               ORDER BY COALESCE(scan_key,run_id),updated_at DESC"""
        )).mappings().all()
        metadata = _symbol_metadata(session)
        for row in rows:
            if row["status"] in {"queued", "running", "paused"}:
                continue
            config = dict(row["configuration"] or {})
            if config.get("last_refresh_slot") == slot:
                continue
            retained_rows = session.execute(text("""
                SELECT canonical.symbol,r.preset_id
                FROM backtest_canonical_results canonical
                JOIN backtest_results r ON r.result_id=canonical.result_id
                JOIN backtest_runs source_run ON source_run.run_id=canonical.run_id
                WHERE canonical.owner_id=:owner_id
                  AND COALESCE(source_run.scan_key,source_run.run_id)=:scan_group
            """), {
                "owner_id": str(row["owner_id"]),
                "scan_group": str(row["scan_group"]),
            }).mappings().all()
            retained_strategies: Dict[str, List[str]] = {}
            for retained in retained_rows:
                retained_strategies.setdefault(str(retained["symbol"]), []).append(str(retained["preset_id"]))
            if not retained_strategies:
                continue
            metadata_updates = [
                {"run_id": row["run_id"], "symbol": symbol, "ltp": item.get("ltp"),
                 "latest_volume": item.get("latest_volume")}
                for symbol, item in metadata.items() if symbol in retained_strategies
            ]
            if metadata_updates:
                session.execute(text(
                    """UPDATE backtest_run_symbols
                       SET ltp=COALESCE(:ltp,ltp),
                           latest_volume=COALESCE(:latest_volume,latest_volume)
                       WHERE run_id=:run_id AND symbol=:symbol"""
                ), metadata_updates)
            _queue_incremental_refresh(
                session,
                run_id=str(row["run_id"]),
                config=config,
                refresh_slot=slot,
                strategies=retained_strategies,
            )
            queued += 1
        session.commit()
        return queued
    except Exception:
        session.rollback()
        return 0
    finally:
        session.close()


def _refresh_scheduled_recommendations() -> int:
    """Refresh owner-private recommendation projections around the NEPSE session."""
    global _LAST_RECOMMENDATION_REFRESH_SLOT
    if os.getenv("BACKTEST_DAILY_REFRESH_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return 0
    now = datetime.now(NEPAL_TZ)
    from utils.market_status import get_market_hours_status
    if not get_market_hours_status(now)["is_trading_day"]:
        return 0
    available = [(hour, minute) for hour, minute in RECOMMENDATION_REFRESH_SLOTS if (hour, minute) <= (now.hour, now.minute)]
    if not available:
        return 0
    hour, minute = available[-1]
    slot = f"{now.date().isoformat()}T{hour:02d}:{minute:02d}+05:45"
    if slot == _LAST_RECOMMENDATION_REFRESH_SLOT:
        return 0
    _LAST_RECOMMENDATION_REFRESH_SLOT = slot
    session = _session()
    refreshed = 0
    try:
        owner_ids = session.execute(text(
            "SELECT DISTINCT owner_id FROM backtest_runs WHERE deleted_at IS NULL AND archived_at IS NULL"
        )).scalars().all()
        from utils.backtesting.recommendations import materialize_recommendations
        for owner_id in owner_ids:
            materialize_recommendations(session, owner_id=str(owner_id))
            refreshed += 1
        session.commit()
        return refreshed
    except Exception:
        session.rollback()
        return 0
    finally:
        session.close()


def _revalidation_enabled_now() -> bool:
    if os.getenv("BACKTEST_REVALIDATION_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return False
    now = datetime.now(NEPAL_TZ)
    try:
        start_hour = max(0, min(23, int(os.getenv("BACKTEST_REVALIDATION_START_HOUR_NEPAL", "0"))))
        end_hour = max(1, min(24, int(os.getenv("BACKTEST_REVALIDATION_END_HOUR_NEPAL", "24"))))
        max_load_ratio = max(.1, float(os.getenv("BACKTEST_REVALIDATION_MAX_LOAD_RATIO", ".75")))
    except ValueError:
        start_hour, end_hour, max_load_ratio = 0, 24, .75
    if not start_hour <= now.hour < end_hour:
        return False
    try:
        if os.getloadavg()[0] / max(1, os.cpu_count() or 1) > max_load_ratio:
            return False
    except (AttributeError, OSError):
        pass
    return True


def _claim_due_revalidation() -> Optional[Dict[str, Any]]:
    """Lease one due borderline strategy only while all normal queues are idle."""
    if not _revalidation_enabled_now():
        return None
    try:
        minimum_new_sessions = max(1, int(os.getenv("BACKTEST_REVALIDATION_MIN_NEW_SESSIONS", "10")))
        lease_minutes = max(5, int(os.getenv("BACKTEST_REVALIDATION_LEASE_MINUTES", "30")))
        daily_limit = max(1, int(os.getenv("BACKTEST_REVALIDATION_DAILY_LIMIT", "3")))
    except ValueError:
        minimum_new_sessions, lease_minutes, daily_limit = 10, 30, 3
    session = _session()
    try:
        session.execute(text("""
            UPDATE backtest_rejected_strategies
            SET revalidation_state='frozen',lease_owner=NULL,lease_expires_at=NULL,
                last_recheck_error=COALESCE(last_recheck_error,'Expired revalidation lease recovered.')
            WHERE revalidation_state='leased' AND lease_expires_at<NOW()
        """))
        busy = session.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM backtest_runs
                WHERE deleted_at IS NULL AND archived_at IS NULL
                  AND status IN ('queued','running')
            )
        """)).scalar()
        if busy:
            session.rollback()
            return None
        revalidated_today = int(session.execute(text("""
            SELECT COUNT(*)
            FROM backtest_rejected_strategies
            WHERE last_revalidated_at >= (
                date_trunc('day',NOW() AT TIME ZONE 'Asia/Kathmandu')
                AT TIME ZONE 'Asia/Kathmandu'
            )
        """)).scalar() or 0)
        if revalidated_today >= daily_limit:
            session.rollback()
            return None
        row = session.execute(text("""
            WITH due AS (
                SELECT rejection_key,symbol,last_tested_session
                FROM backtest_rejected_strategies
                WHERE revalidation_state='frozen' AND next_recheck_at<=NOW()
                  AND total_trades>=:min_trades AND win_rate_pct>=:min_win
                  AND source_run_id IS NOT NULL AND owner_id IS NOT NULL
                  AND (lease_expires_at IS NULL OR lease_expires_at<NOW())
                ORDER BY win_rate_pct DESC,total_trades DESC,last_seen_at,rejection_key
                FOR UPDATE SKIP LOCKED
                LIMIT 25
            ), eligible AS (
                SELECT due.rejection_key
                FROM due
                WHERE (
                    SELECT COUNT(DISTINCT d.session_date)
                    FROM market_ohlcv_daily d
                    WHERE d.symbol=due.symbol AND d.adjusted=TRUE
                      AND (due.last_tested_session IS NULL OR d.session_date>due.last_tested_session)
                      AND d.session_date<=CURRENT_DATE
                )>=:minimum_new_sessions
                LIMIT 1
            )
            UPDATE backtest_rejected_strategies rejected
            SET revalidation_state='leased',lease_owner=:owner,
                lease_expires_at=NOW()+(:lease_minutes*INTERVAL '1 minute'),
                last_recheck_error=NULL
            FROM eligible
            WHERE rejected.rejection_key=eligible.rejection_key
            RETURNING rejected.*
        """), {
            "min_trades": MIN_REVALIDATION_TRADES,
            "min_win": MIN_REVALIDATION_WIN_RATE_PCT,
            "minimum_new_sessions": minimum_new_sessions,
            "lease_minutes": lease_minutes,
            "owner": _WORKER_ID,
        }).mappings().first()
        session.commit()
        return dict(row) if row else None
    except Exception:
        session.rollback()
        return None
    finally:
        session.close()


def _revalidation_preset(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    strategy_id = str(row.get("strategy_id") or "")
    catalog = {str(item["id"]): dict(item) for item in get_backtest_presets()}
    if strategy_id in catalog:
        return catalog[strategy_id]
    definition = row.get("strategy_definition") or {}
    if isinstance(definition, str):
        definition = json.loads(definition)
    if not definition:
        session = _session()
        try:
            definition = session.execute(text("""
                SELECT definition FROM backtest_strategy_definitions
                WHERE strategy_hash=:strategy_hash
            """), {"strategy_hash": str(row.get("strategy_hash") or "")}).scalar() or {}
        finally:
            session.close()
        if isinstance(definition, str):
            definition = json.loads(definition)
    if isinstance(definition, dict) and definition.get("id"):
        return dict(definition)
    return None


def _existing_symbol_results(session, run_id: str, symbol: str) -> List[Dict[str, Any]]:
    rows = session.execute(text("""
        SELECT r.* FROM backtest_results r
        WHERE r.run_id=:run_id AND r.symbol=:symbol
        ORDER BY r.result_id
    """), {"run_id": run_id, "symbol": symbol}).mappings().all()
    results: List[Dict[str, Any]] = []
    for mapped in rows:
        result = dict(mapped)
        trades = session.execute(text(
            "SELECT * FROM backtest_trades WHERE result_id=:result_id ORDER BY sequence_no"
        ), {"result_id": result["result_id"]}).mappings().all()
        for key in (
            "result_id", "run_id", "evaluation_split", "created_at",
            "configuration_hash", "configuration_identity_version",
        ):
            result.pop(key, None)
        technical = result.pop("technical_snapshot", None) or {}
        if isinstance(technical, str):
            technical = json.loads(technical)
        if isinstance(technical, dict):
            result.update(technical)
        result["trades"] = [
            {key: value for key, value in dict(trade).items() if key not in {"trade_id", "result_id"}}
            for trade in trades
        ]
        results.append(result)
    return results


def _finish_revalidation(
    rejection_key: str, *, signal: Optional[Dict[str, Any]], error: Optional[str],
    duration_seconds: float,
) -> None:
    try:
        interval_days = max(1, int(os.getenv("BACKTEST_REVALIDATION_INTERVAL_DAYS", "30")))
    except ValueError:
        interval_days = 30
    session = _session()
    try:
        session.execute(text("""
            UPDATE backtest_rejected_strategies
            SET revalidation_state='frozen',recheck_count=recheck_count+1,
                last_revalidated_at=NOW(),
                next_recheck_at=NOW()+(:interval_days*INTERVAL '1 day'),
                latest_signal_status=COALESCE(:signal_status,latest_signal_status),
                latest_signal_date=COALESCE(:signal_date,latest_signal_date),
                latest_signal_evidence=CASE WHEN :signal_evidence IS NULL
                    THEN latest_signal_evidence ELSE CAST(:signal_evidence AS JSONB) END,
                last_tested_session=COALESCE(:signal_date,last_tested_session),
                last_recheck_error=:error,last_recheck_duration_seconds=:duration,
                lease_owner=NULL,lease_expires_at=NULL,last_seen_at=NOW()
            WHERE rejection_key=:key AND lease_owner=:owner
        """), {
            "key": rejection_key, "owner": _WORKER_ID,
            "interval_days": interval_days, "error": str(error)[:2000] if error else None,
            "duration": duration_seconds,
            "signal_status": signal.get("current_signal_status") if signal else None,
            "signal_date": signal.get("current_signal_date") if signal else None,
            "signal_evidence": json.dumps(signal.get("current_evidence") or {}, default=str) if signal else None,
        })
        session.commit()
    finally:
        session.close()


def _run_one_due_revalidation() -> bool:
    row = _claim_due_revalidation()
    if not row:
        return False
    started = time.monotonic()
    signal: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    try:
        preset = _revalidation_preset(row)
        if not preset:
            raise ValueError("Saved strategy definition is not executable.")
        run_id = str(row["source_run_id"])
        symbol = str(row["symbol"])
        session = _session()
        try:
            run = session.execute(text("""
                SELECT configuration FROM backtest_runs
                WHERE run_id=:run_id AND owner_id=:owner_id
                  AND deleted_at IS NULL AND archived_at IS NULL
            """), {"run_id": run_id, "owner_id": str(row["owner_id"])}).mappings().first()
            if not run:
                raise ValueError("Source backtest workspace is unavailable.")
            config = dict(run["configuration"] or {})
        finally:
            session.close()
        end_date = datetime.now(NEPAL_TZ).date()
        from utils.backtesting.service import fetch_historical_bars
        if str(config.get("data_source") or "merolagani") == "merolagani":
            fetch_historical_bars(
                symbol, date.fromisoformat(str(config["start_date"])), end_date,
                force_tail_refresh=True,
            )
        # Monthly checks only evaluate unseen BUY-signal sessions. Every third
        # check expands the recent window to roughly one quarter, but never
        # replays the original historical trade simulation.
        quarterly = (int(row.get("recheck_count") or 0) + 1) % 3 == 0
        output = _refresh_symbol_signals_task({
            "symbol": symbol, "start_date": date.fromisoformat(str(config["start_date"])),
            "end_date": end_date, "data_source": config.get("data_source") or "merolagani",
            "presets": [preset],
            "baselines": [{
                "preset_id": str(row["strategy_id"]),
                "total_trades": int(row.get("total_trades") or 0),
                "win_rate_pct": float(row.get("win_rate_pct") or 0),
                "confidence_score": 0,
                "liquidity_score": 0,
            }],
            "refresh_window_sessions": 65 if quarterly else 10,
        })
        if output.get("error") and not output.get("results"):
            raise ValueError(str(output["error"]))
        signal = next(
            (dict(item) for item in output.get("results") or [] if str(item.get("preset_id")) == str(row["strategy_id"])),
            None,
        )
        if signal is None:
            raise ValueError("Incremental validation produced no matching signal result.")
    except Exception as exc:
        error = str(exc)
    _finish_revalidation(
        str(row["rejection_key"]), signal=signal, error=error,
        duration_seconds=max(0, time.monotonic() - started),
    )
    return True


def worker_loop(*, refresh_only: bool = False) -> None:
    global _LAST_REVALIDATION_ATTEMPT_AT
    while True:
        if not refresh_only:
            purge_expired_archives()
            _queue_scheduled_refreshes()
            _refresh_scheduled_recommendations()
        run_id = _claim_next_run(refresh_only=refresh_only)
        if run_id:
            run_claimed_run(run_id)
        else:
            ran_revalidation = False
            now = time.monotonic()
            if (
                not refresh_only
                and (_LAST_REVALIDATION_ATTEMPT_AT is None or now - _LAST_REVALIDATION_ATTEMPT_AT >= 10)
            ):
                _LAST_REVALIDATION_ATTEMPT_AT = now
                ran_revalidation = _run_one_due_revalidation()
            time.sleep(10 if ran_revalidation else 2)


def start_worker() -> bool:
    global _WORKER_PROCESS, _REFRESH_WORKER_PROCESS, _WORKER_STARTED
    with _WORKER_LOCK:
        if _WORKER_PROCESS is not None and _WORKER_PROCESS.poll() is None:
            return False
        environment = dict(os.environ)
        environment["BACKTEST_V2"] = "false"
        _WORKER_PROCESS = subprocess.Popen(
            [sys.executable, "-m", "utils.backtesting.v2_worker"],
            env=environment,
        )
        refresh_environment = dict(environment)
        refresh_environment["BACKTEST_REFRESH_ONLY"] = "true"
        _REFRESH_WORKER_PROCESS = subprocess.Popen(
            [sys.executable, "-m", "utils.backtesting.v2_worker"],
            env=refresh_environment,
        )
        _WORKER_STARTED = True
    return True


def stop_worker() -> bool:
    global _WORKER_PROCESS, _REFRESH_WORKER_PROCESS, _WORKER_STARTED
    with _WORKER_LOCK:
        processes = [_WORKER_PROCESS, _REFRESH_WORKER_PROCESS]
        _WORKER_PROCESS = None
        _REFRESH_WORKER_PROCESS = None
        _WORKER_STARTED = False
    stopped = False
    for process in processes:
        if process is None or process.poll() is not None:
            continue
        stopped = True
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    return stopped



def _rebuild_canonical_for_owner(session, owner_id: str) -> None:
    """Drop inactive run pointers and re-seed active unique configurations."""
    session.execute(text("""
        DELETE FROM backtest_canonical_results canonical
        WHERE canonical.owner_id=:owner_id
          AND NOT EXISTS (
              SELECT 1 FROM backtest_results r
              JOIN backtest_runs br ON br.run_id=r.run_id
              WHERE r.result_id=canonical.result_id
                AND br.deleted_at IS NULL AND br.archived_at IS NULL
                AND ((r.total_trades>=16 AND r.win_rate_pct>=50)
                     OR (r.total_trades>=9 AND r.win_rate_pct>=60))
          )
    """), {"owner_id": owner_id})
    session.execute(text("""
        INSERT INTO backtest_canonical_results
            (owner_id,configuration_hash,result_id,run_id,symbol,security_type,data_session,updated_at)
        SELECT DISTINCT ON (br.owner_id,r.configuration_hash)
               br.owner_id,r.configuration_hash,r.result_id,r.run_id,r.symbol,s.security_type,
               r.current_signal_date,NOW()
        FROM backtest_results r
        JOIN backtest_runs br ON br.run_id=r.run_id
        JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol
        WHERE br.owner_id=:owner_id AND br.deleted_at IS NULL AND br.archived_at IS NULL
          AND r.configuration_hash IS NOT NULL
          AND ((r.total_trades>=16 AND r.win_rate_pct>=50)
               OR (r.total_trades>=9 AND r.win_rate_pct>=60))
        ORDER BY br.owner_id,r.configuration_hash,r.current_signal_date DESC NULLS LAST,r.result_id DESC
        ON CONFLICT (owner_id,configuration_hash) DO UPDATE SET
            result_id=EXCLUDED.result_id,run_id=EXCLUDED.run_id,symbol=EXCLUDED.symbol,
            security_type=EXCLUDED.security_type,data_session=EXCLUDED.data_session,updated_at=NOW()
        WHERE EXCLUDED.data_session IS NOT NULL
           AND (backtest_canonical_results.data_session IS NULL
                OR EXCLUDED.data_session>backtest_canonical_results.data_session
                OR (EXCLUDED.data_session=backtest_canonical_results.data_session
                    AND EXCLUDED.result_id>backtest_canonical_results.result_id))
    """), {"owner_id": owner_id})


def list_archived_runs(*, owner_id: str = "local") -> Dict[str, Any]:
    session = _session()
    try:
        rows = session.execute(text("""
            SELECT * FROM backtest_runs
            WHERE owner_id=:owner_id AND deleted_at IS NULL AND archived_at IS NOT NULL
            ORDER BY archived_at DESC, updated_at DESC
        """), {"owner_id": owner_id}).mappings().all()
        items = [_public_run(dict(row)) for row in rows]
        return {"items": items, "total": len(items), "retention_days": ARCHIVE_RETENTION_DAYS}
    finally:
        session.close()


def archive_run(run_id: str, *, owner_id: str = "local") -> Dict[str, Any]:
    """Hide a workspace from active scans/results; keep it recoverable for 30 days."""
    session = _session()
    try:
        row = session.execute(text("""
            SELECT run_id,status FROM backtest_runs
            WHERE run_id=:run_id AND owner_id=:owner_id AND deleted_at IS NULL AND archived_at IS NULL
            FOR UPDATE
        """), {"run_id": run_id, "owner_id": owner_id}).mappings().first()
        if not row:
            raise ValueError("Backtest workspace was not found.")
        if row["status"] in {"queued", "running", "paused"}:
            session.execute(text("""
                UPDATE backtest_runs
                SET cancel_requested=TRUE, status='cancelled', current_symbol=NULL,
                    finished_at=COALESCE(finished_at,NOW()), updated_at=NOW()
                WHERE run_id=:run_id AND owner_id=:owner_id
            """), {"run_id": run_id, "owner_id": owner_id})
        session.execute(text("""
            UPDATE backtest_runs
            SET archived_at=NOW(), updated_at=NOW(),
                cancel_requested=TRUE, pause_requested=FALSE,
                lease_owner=NULL, lease_expires_at=NULL
            WHERE run_id=:run_id AND owner_id=:owner_id
        """), {"run_id": run_id, "owner_id": owner_id})
        _rebuild_canonical_for_owner(session, owner_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return list_archived_runs(owner_id=owner_id)


def restore_archived_run(run_id: str, *, owner_id: str = "local") -> Dict[str, Any]:
    session = _session()
    try:
        changed = session.execute(text("""
            UPDATE backtest_runs
            SET archived_at=NULL, updated_at=NOW()
            WHERE run_id=:run_id AND owner_id=:owner_id
              AND deleted_at IS NULL AND archived_at IS NOT NULL
        """), {"run_id": run_id, "owner_id": owner_id}).rowcount
        if not changed:
            raise ValueError("Archived workspace was not found.")
        _rebuild_canonical_for_owner(session, owner_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return list_archived_runs(owner_id=owner_id)


def permanently_delete_run(run_id: str, *, owner_id: str = "local") -> Dict[str, Any]:
    """Hard-delete an archived workspace and all of its stored results."""
    session = _session()
    try:
        row = session.execute(text("""
            SELECT run_id FROM backtest_runs
            WHERE run_id=:run_id AND owner_id=:owner_id
              AND deleted_at IS NULL AND archived_at IS NOT NULL
            FOR UPDATE
        """), {"run_id": run_id, "owner_id": owner_id}).mappings().first()
        if not row:
            raise ValueError("Only archived workspaces can be permanently deleted.")
        session.execute(text(
            "DELETE FROM backtest_canonical_results WHERE run_id=:run_id AND owner_id=:owner_id"
        ), {"run_id": run_id, "owner_id": owner_id})
        session.execute(text(
            "DELETE FROM backtest_runs WHERE run_id=:run_id AND owner_id=:owner_id"
        ), {"run_id": run_id, "owner_id": owner_id})
        _rebuild_canonical_for_owner(session, owner_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return list_archived_runs(owner_id=owner_id)


def purge_expired_archives(*, retention_days: int = ARCHIVE_RETENTION_DAYS) -> int:
    """Permanently remove archived workspaces older than the retention window."""
    global _LAST_ARCHIVE_PURGE_AT
    now = time.time()
    if _LAST_ARCHIVE_PURGE_AT and now - _LAST_ARCHIVE_PURGE_AT < 3600:
        return 0
    _LAST_ARCHIVE_PURGE_AT = now
    session = _session()
    deleted = 0
    try:
        rows = session.execute(text("""
            SELECT run_id, owner_id FROM backtest_runs
            WHERE deleted_at IS NULL AND archived_at IS NOT NULL
              AND archived_at < NOW() - (:days * INTERVAL '1 day')
        """), {"days": int(retention_days)}).mappings().all()
        for row in rows:
            session.execute(text(
                "DELETE FROM backtest_canonical_results WHERE run_id=:run_id AND owner_id=:owner_id"
            ), {"run_id": row["run_id"], "owner_id": row["owner_id"]})
            session.execute(text(
                "DELETE FROM backtest_runs WHERE run_id=:run_id AND owner_id=:owner_id"
            ), {"run_id": row["run_id"], "owner_id": row["owner_id"]})
            deleted += 1
        if deleted:
            for owner_id in sorted({str(row["owner_id"]) for row in rows}):
                _rebuild_canonical_for_owner(session, owner_id)
        session.commit()
        return deleted
    except Exception:
        session.rollback()
        return 0
    finally:
        session.close()


def set_run_control(run_id: str, action: str, *, owner_id: str = "local") -> Dict[str, Any]:
    if action not in {"cancel", "pause", "resume"}:
        raise ValueError("Unsupported run control action.")
    session = _session()
    try:
        if action == "cancel":
            statement = """UPDATE backtest_runs
                           SET cancel_requested=TRUE,status='cancelled',current_symbol=NULL,
                               finished_at=COALESCE(finished_at,NOW()),updated_at=NOW()
                           WHERE run_id=:run_id AND owner_id=:owner_id
                             AND status IN ('queued','running','paused')"""
        elif action == "pause":
            statement = """UPDATE backtest_runs
                           SET pause_requested=TRUE,status='paused',updated_at=NOW()
                           WHERE run_id=:run_id AND owner_id=:owner_id
                             AND status IN ('queued','running')"""
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
