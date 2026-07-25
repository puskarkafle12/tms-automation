"""Owner-neutral, versioned stock × strategy backtest artifact cache."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import bindparam, text

from utils.backtesting.result_retention import (
    RETENTION_POLICY_VERSION,
    is_revalidation_candidate,
    is_retained_result,
    retention_failure_reason,
)


HISTORY_SOURCE_BY_RUN_SOURCE = {
    "merolagani": "merolagani_adjusted",
}


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def strategy_hash(preset: Dict[str, Any]) -> str:
    return _digest({
        "id": preset.get("id"), "version": preset.get("version"),
        "source_hash": preset.get("source_hash"),
        "defaults": preset.get("defaults"), "condition": preset.get("condition"),
        "custom_query_text": preset.get("custom_query_text"),
    })


def settings_hash(
    config: Dict[str, Any], preset: Dict[str, Any], *,
    engine_version: str, indicator_version: str,
) -> str:
    defaults = dict(preset.get("defaults") or {})
    use_preset_holding = bool(config.get("use_preset_holding_days"))
    min_days = int(
        max(
            int(config.get("min_holding_days") or 0),
            int(defaults.get("min_holding_days") or 0),
        )
        if use_preset_holding
        else config.get("min_holding_days") or defaults.get("min_holding_days") or 0
    )
    max_days = int(
        defaults.get("max_holding_days") or 20
        if use_preset_holding
        else config.get("max_holding_days") or defaults.get("max_holding_days") or 20
    )
    identity = {
        "engine_version": engine_version, "indicator_version": indicator_version,
        "data_source": config.get("data_source") or "merolagani",
        "initial_capital": float(config.get("initial_capital") or 100000),
        "charge_model": config.get("charge_model") or "nepse_equity",
        "investor_type": config.get("investor_type") or "individual",
        "apply_cgt": bool(config.get("apply_cgt", True)),
        "dp_charge": float(config.get("dp_charge") if config.get("dp_charge") is not None else 25),
        "fee_pct": float(config.get("fee_pct") or .4),
        "fixed_fee": float(config.get("fixed_fee") or 0),
        "slippage_pct": float(config.get("slippage_pct") or .1),
        "position_size_pct": float(config.get("position_size_pct") or 100),
        "min_holding_days": min_days, "max_holding_days": max_days,
        "trailing_stop_pct": config.get("trailing_stop_pct"),
        "max_volume_participation_pct": float(config.get("max_volume_participation_pct") or 10),
        "risk_free_rate_pct": float(config.get("risk_free_rate_pct") or 4),
        "stop_loss_pct": float(defaults.get("stop_loss_pct") or 5),
        "take_profit_pct": float(defaults.get("take_profit_pct") or 10),
        "exit_rule_id": preset.get("exit_rule_id"), "exit_condition": preset.get("exit_condition"),
        "professional": True,
    }
    return _digest(identity)


def artifact_key(
    *, symbol: str, preset: Dict[str, Any], config: Dict[str, Any],
    data_session: date, data_hash: str, engine_version: str, indicator_version: str,
) -> str:
    return _digest({
        "symbol": symbol.strip().upper(), "strategy_hash": strategy_hash(preset),
        "settings_hash": settings_hash(config, preset, engine_version=engine_version, indicator_version=indicator_version),
        "start_date": str(config.get("start_date")), "data_session": data_session.isoformat(),
        "data_hash": data_hash,
    })


def rejection_key(
    *, symbol: str, preset: Dict[str, Any], config: Dict[str, Any],
    engine_version: str, indicator_version: str,
) -> str:
    """Identify a failed strategy independently of changing market-data sessions."""
    return _digest({
        "symbol": symbol.strip().upper(),
        "strategy_hash": strategy_hash(preset),
        "settings_hash": settings_hash(
            config, preset, engine_version=engine_version, indicator_version=indicator_version,
        ),
        "engine_version": engine_version,
        "indicator_version": indicator_version,
    })


def store_strategy_definitions(session, presets: Sequence[Dict[str, Any]]) -> int:
    """Persist immutable strategy JSON once instead of once for every stock."""
    unique = {strategy_hash(preset): preset for preset in presets}
    if not unique:
        return 0
    existing = {
        str(row["strategy_hash"])
        for row in session.execute(text("""
            SELECT strategy_hash FROM backtest_strategy_definitions
            WHERE strategy_hash IN :hashes
        """).bindparams(bindparam("hashes", expanding=True)), {
            "hashes": list(unique),
        }).mappings().all()
    }
    pending = []
    for hashed, preset in unique.items():
        if hashed in existing:
            continue
        pending.append({
            "strategy_hash": hashed,
            "strategy_id": str(preset.get("id") or hashed),
            "strategy_name": str(preset.get("name") or preset.get("id") or hashed),
            "definition": json.dumps(preset, default=str),
        })
    if not pending:
        return 0
    session.execute(text("""
        INSERT INTO backtest_strategy_definitions
            (strategy_hash,strategy_id,strategy_name,definition)
        VALUES (:strategy_hash,:strategy_id,:strategy_name,CAST(:definition AS JSONB))
        ON CONFLICT (strategy_hash) DO NOTHING
    """), pending)
    return len(pending)


def cache_context(
    session, *, symbol: str, start_date: date, end_date: date, data_source: str,
) -> Optional[Tuple[date, str]]:
    source = HISTORY_SOURCE_BY_RUN_SOURCE.get(str(data_source or "merolagani"))
    if not source:
        return None
    state = session.execute(text("""
        SELECT requested_start,requested_end,history_end,status,data_hash
        FROM market_history_cache_state
        WHERE symbol=:symbol AND source=:source AND adjusted=TRUE
    """), {"symbol": symbol, "source": source}).mappings().first()
    if not state or state["status"] != "ready" or not state["data_hash"] or not state["history_end"]:
        return None
    if state["requested_start"] and state["requested_start"] > start_date:
        return None
    if state["requested_end"] and state["requested_end"] < end_date:
        return None
    data_session = min(state["history_end"], end_date)
    return data_session, str(state["data_hash"])


def _public_result(row: Dict[str, Any], trades: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    result = dict(row)
    for key in ("result_id", "run_id", "evaluation_split", "created_at", "configuration", "last_tested_session"):
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
    return result


def _upsert_artifact(
    session, *, key: str, symbol: str, preset: Dict[str, Any], config: Dict[str, Any],
    data_session: date, data_hash: str, engine_version: str, indicator_version: str,
    result: Dict[str, Any], market_profile: Dict[str, Any], technical_snapshot: Dict[str, Any],
) -> None:
    session.execute(text("""
        INSERT INTO backtest_result_artifacts (
            artifact_key,symbol,strategy_id,strategy_hash,settings_hash,data_source,start_date,
            data_session,data_hash,engine_version,indicator_engine_version,result_payload,
            market_profile,technical_snapshot,created_at,updated_at,last_used_at,use_count
        ) VALUES (
            :artifact_key,:symbol,:strategy_id,:strategy_hash,:settings_hash,:data_source,:start_date,
            :data_session,:data_hash,:engine_version,:indicator_version,CAST(:result AS JSONB),
            CAST(:profile AS JSONB),CAST(:technical AS JSONB),NOW(),NOW(),NOW(),0
        ) ON CONFLICT (artifact_key) DO UPDATE SET
            result_payload=EXCLUDED.result_payload,market_profile=EXCLUDED.market_profile,
            technical_snapshot=EXCLUDED.technical_snapshot,updated_at=NOW()
    """), {
        "artifact_key": key, "symbol": symbol, "strategy_id": preset.get("id"),
        "strategy_hash": strategy_hash(preset),
        "settings_hash": settings_hash(config, preset, engine_version=engine_version, indicator_version=indicator_version),
        "data_source": config.get("data_source") or "merolagani", "start_date": config.get("start_date"),
        "data_session": data_session, "data_hash": data_hash, "engine_version": engine_version,
        "indicator_version": indicator_version,
        "result": json.dumps(result, default=str), "profile": json.dumps(market_profile, default=str),
        "technical": json.dumps(technical_snapshot, default=str),
    })


def _legacy_artifacts(
    session, *, symbol: str, missing: Sequence[Dict[str, Any]], config: Dict[str, Any],
    data_session: date, data_hash: str, engine_version: str, indicator_version: str,
) -> Dict[str, Dict[str, Any]]:
    if not missing:
        return {}
    preset_ids = [str(item["id"]) for item in missing]
    rows = session.execute(text("""
        SELECT r.*,br.configuration,s.last_tested_session
        FROM backtest_results r
        JOIN backtest_runs br ON br.run_id=r.run_id
        JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol
        WHERE r.symbol=:symbol AND r.preset_id IN :preset_ids
          AND s.last_tested_session=:data_session AND br.status='completed'
          AND br.deleted_at IS NULL AND br.archived_at IS NULL AND br.engine_version=:engine_version
          AND br.indicator_engine_version=:indicator_version
        ORDER BY br.finished_at DESC NULLS LAST,r.result_id DESC
    """).bindparams(bindparam("preset_ids", expanding=True)), {
        "symbol": symbol, "preset_ids": preset_ids, "data_session": data_session,
        "engine_version": engine_version, "indicator_version": indicator_version,
    }).mappings().all()
    desired = {str(preset["id"]): preset for preset in missing}
    selected: Dict[str, Dict[str, Any]] = {}
    for mapped in rows:
        row = dict(mapped)
        preset = desired.get(str(row["preset_id"]))
        if not preset or str(row["preset_id"]) in selected:
            continue
        assumptions = row.get("assumptions") or {}
        if isinstance(assumptions, str):
            assumptions = json.loads(assumptions)
        recorded_hash = str(assumptions.get("preset_source_hash") or "")
        if recorded_hash and recorded_hash != str(preset.get("source_hash") or ""):
            continue
        candidate_config = dict(row.get("configuration") or {})
        desired_key = artifact_key(
            symbol=symbol, preset=preset, config=config, data_session=data_session, data_hash=data_hash,
            engine_version=engine_version, indicator_version=indicator_version,
        )
        candidate_key = artifact_key(
            symbol=symbol, preset=preset, config=candidate_config, data_session=data_session, data_hash=data_hash,
            engine_version=engine_version, indicator_version=indicator_version,
        )
        if desired_key != candidate_key:
            continue
        trades = session.execute(text(
            "SELECT * FROM backtest_trades WHERE result_id=:result_id ORDER BY sequence_no"
        ), {"result_id": row["result_id"]}).mappings().all()
        selected[str(preset["id"])] = _public_result(row, [dict(item) for item in trades])
    return selected


def _market_context(session, *, symbol: str, data_session: date) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Recover display/indicator metadata when importing a pre-artifact result."""
    technical_row = session.execute(text("""
        SELECT as_of_date,indicators,engine_version,bars_count,history_start,history_end,
               latest_volume,average_volume_20,median_volume_20,average_turnover_20
        FROM market_technical_indicators
        WHERE symbol=:symbol AND as_of_date=:data_session
    """), {"symbol": symbol, "data_session": data_session}).mappings().first()
    market_row = session.execute(text("""
        SELECT close_price,volume FROM market_ohlcv_daily
        WHERE symbol=:symbol AND adjusted=TRUE AND session_date=:data_session
        ORDER BY fetched_at DESC LIMIT 1
    """), {"symbol": symbol, "data_session": data_session}).mappings().first()
    if not technical_row:
        profile = {
            "ltp": float(market_row["close_price"]) if market_row and market_row["close_price"] is not None else None,
            "latest_volume": float(market_row["volume"]) if market_row and market_row["volume"] is not None else None,
        }
        return profile, {"as_of_date": data_session.isoformat(), "history_end": data_session.isoformat()}
    indicators = technical_row["indicators"] or {}
    if isinstance(indicators, str):
        indicators = json.loads(indicators)
    profile = {
        "ltp": float(market_row["close_price"]) if market_row and market_row["close_price"] is not None else None,
        "latest_volume": technical_row["latest_volume"],
        "average_volume_20": technical_row["average_volume_20"],
        "median_volume_20": technical_row["median_volume_20"],
        "average_turnover_20": technical_row["average_turnover_20"],
    }
    technical = {
        "as_of_date": technical_row["as_of_date"].isoformat(),
        "indicators": dict(indicators), "engine_version": technical_row["engine_version"],
        "bars_count": int(technical_row["bars_count"] or 0),
        "history_start": technical_row["history_start"].isoformat() if technical_row["history_start"] else None,
        "history_end": technical_row["history_end"].isoformat() if technical_row["history_end"] else data_session.isoformat(),
    }
    return profile, technical


def _rejected_preset_ids(
    session, *, symbol: str, presets: Sequence[Dict[str, Any]], config: Dict[str, Any],
    engine_version: str, indicator_version: str,
    owner_id: Optional[str] = None, source_run_id: Optional[str] = None,
) -> set[str]:
    """Return still-disqualified identities under the current adaptive policy."""
    identities = {
        (
            strategy_hash(preset),
            settings_hash(
                config, preset, engine_version=engine_version, indicator_version=indicator_version,
            ),
        ): preset
        for preset in presets
    }
    if not identities:
        return set()
    rows = session.execute(text("""
        SELECT rejection_key,strategy_hash,settings_hash,total_trades,win_rate_pct
        FROM backtest_rejected_strategies
        WHERE symbol=:symbol AND engine_version=:engine_version
          AND indicator_engine_version=:indicator_version
          AND (strategy_hash,settings_hash) IN :identities
    """).bindparams(bindparam("identities", expanding=True)), {
        "symbol": symbol, "engine_version": engine_version, "indicator_version": indicator_version,
        "identities": list(identities),
    }).mappings().all()
    rejected_rows = [
        row for row in rows
        if (str(row["strategy_hash"]), str(row["settings_hash"])) in identities
        and not is_retained_result(row)
    ]
    if rejected_rows:
        store_strategy_definitions(session, [
            identities[(str(row["strategy_hash"]), str(row["settings_hash"]))]
            for row in rejected_rows
        ])
        session.execute(text("""
            UPDATE backtest_rejected_strategies
            SET skip_count=skip_count+1,last_seen_at=NOW(),
                owner_id=COALESCE(owner_id,:owner_id),
                source_run_id=COALESCE(source_run_id,:source_run_id),
                last_tested_session=COALESCE(
                    last_tested_session,
                    (SELECT last_tested_session FROM backtest_run_symbols
                     WHERE run_id=:source_run_id AND symbol=:symbol)
                )
            WHERE rejection_key=:key
        """), [{
            "key": str(row["rejection_key"]),
            "symbol": symbol,
            "owner_id": owner_id,
            "source_run_id": source_run_id,
        } for row in rejected_rows])
    return {
        str(identities[(str(row["strategy_hash"]), str(row["settings_hash"]))]["id"])
        for row in rejected_rows
    }


def load_symbol_artifacts(
    session, *, symbol: str, presets: Sequence[Dict[str, Any]], config: Dict[str, Any],
    engine_version: str, indicator_version: str,
    owner_id: Optional[str] = None, source_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    if not presets:
        return {"results": [], "missing": [], "market_profile": {}, "technical_snapshot": {},
                "hits": 0, "rejected_hits": 0}
    rejected_ids = _rejected_preset_ids(
        session, symbol=symbol, presets=presets, config=config,
        engine_version=engine_version, indicator_version=indicator_version,
        owner_id=owner_id, source_run_id=source_run_id,
    )
    start = date.fromisoformat(str(config["start_date"])); end = date.fromisoformat(str(config["end_date"]))
    context = cache_context(session, symbol=symbol, start_date=start, end_date=end, data_source=str(config.get("data_source") or "merolagani"))
    if not context:
        return {
            "results": [],
            "missing": [preset for preset in presets if str(preset["id"]) not in rejected_ids],
            "market_profile": {}, "technical_snapshot": {}, "hits": 0,
            "rejected_hits": len(rejected_ids),
        }
    data_session, data_hash = context
    keyed = {
        artifact_key(symbol=symbol, preset=preset, config=config, data_session=data_session, data_hash=data_hash,
                     engine_version=engine_version, indicator_version=indicator_version): preset
        for preset in presets
    }
    rows = session.execute(text("""
        SELECT artifact_key,result_payload,market_profile,technical_snapshot
        FROM backtest_result_artifacts WHERE artifact_key IN :keys
    """).bindparams(bindparam("keys", expanding=True)), {"keys": list(keyed)}).mappings().all()
    found: Dict[str, Dict[str, Any]] = {}
    profile: Dict[str, Any] = {}; technical: Dict[str, Any] = {}
    for row in rows:
        preset = keyed[str(row["artifact_key"])]
        payload = row["result_payload"] if isinstance(row["result_payload"], dict) else json.loads(row["result_payload"])
        if not is_retained_result(payload):
            rejected_ids.add(str(preset["id"]))
            continue
        found[str(preset["id"])] = dict(payload)
        profile = dict(row["market_profile"] or profile); technical = dict(row["technical_snapshot"] or technical)
    missing = [
        preset for preset in presets
        if str(preset["id"]) not in found and str(preset["id"]) not in rejected_ids
    ]
    legacy = _legacy_artifacts(
        session, symbol=symbol, missing=missing, config=config, data_session=data_session, data_hash=data_hash,
        engine_version=engine_version, indicator_version=indicator_version,
    )
    if legacy:
        if not profile or not technical:
            recovered_profile, recovered_technical = _market_context(
                session, symbol=symbol, data_session=data_session,
            )
            profile = profile or recovered_profile
            technical = technical or recovered_technical
        for preset in missing:
            result = legacy.get(str(preset["id"]))
            if not result:
                continue
            if not is_retained_result(result):
                rejected_ids.add(str(preset["id"]))
                continue
            key = artifact_key(symbol=symbol, preset=preset, config=config, data_session=data_session, data_hash=data_hash,
                               engine_version=engine_version, indicator_version=indicator_version)
            _upsert_artifact(
                session, key=key, symbol=symbol, preset=preset, config=config, data_session=data_session,
                data_hash=data_hash, engine_version=engine_version, indicator_version=indicator_version,
                result=result, market_profile=profile, technical_snapshot=technical,
            )
            found[str(preset["id"])] = result
        missing = [
            preset for preset in presets
            if str(preset["id"]) not in found and str(preset["id"]) not in rejected_ids
        ]
    used_keys = [key for key, preset in keyed.items() if str(preset["id"]) in found]
    if used_keys:
        session.execute(text("""
            UPDATE backtest_result_artifacts SET use_count=use_count+1,last_used_at=NOW()
            WHERE artifact_key IN :keys
        """).bindparams(bindparam("keys", expanding=True)), {"keys": used_keys})
    return {
        "results": [found[str(preset["id"])] for preset in presets if str(preset["id"]) in found],
        "missing": missing, "market_profile": profile, "technical_snapshot": technical,
        "hits": len(found), "rejected_hits": len(rejected_ids),
        "data_session": data_session, "data_hash": data_hash,
    }


def store_symbol_artifacts(
    session, *, output: Dict[str, Any], presets: Sequence[Dict[str, Any]], config: Dict[str, Any],
    engine_version: str, indicator_version: str,
    owner_id: Optional[str] = None, source_run_id: Optional[str] = None,
) -> int:
    symbol = str(output.get("symbol") or "").strip().upper()
    if not symbol:
        return 0
    by_id = {str(item["id"]): item for item in presets}
    rejected: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    retained: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for raw in output.get("results") or []:
        result = dict(raw)
        preset = by_id.get(str(result.get("preset_id")))
        if not preset:
            continue
        (retained if is_retained_result(result) else rejected).append((result, preset))
    if rejected:
        store_strategy_definitions(session, [preset for _, preset in rejected])
        profile = dict(output.get("market_profile") or {})
        stock_name = str(profile.get("company_name") or profile.get("name") or "").strip()
        if not stock_name:
            stock_name = str(session.execute(text("""
                SELECT COALESCE(
                    combined_data->>'company_name',combined_data->>'name',
                    combined_data->>'companyName',:symbol
                )
                FROM market_screener_cache WHERE symbol=:symbol
            """), {"symbol": symbol}).scalar() or symbol)
        try:
            recheck_days = max(1, int(os.getenv("BACKTEST_REVALIDATION_INTERVAL_DAYS", "30")))
        except ValueError:
            recheck_days = 30
        technical = dict(output.get("technical_snapshot") or {})
        session.execute(text("""
            INSERT INTO backtest_rejected_strategies (
                rejection_key,symbol,stock_name,strategy_id,strategy_name,strategy_hash,
                settings_hash,engine_version,indicator_engine_version,total_trades,win_rate_pct,
                rejection_reason,policy_version,strategy_definition,owner_id,source_run_id,
                last_tested_session,next_recheck_at,revalidation_state,trade_samples
            ) VALUES (
                :key,:symbol,:stock_name,:strategy_id,:strategy_name,:strategy_hash,
                :settings_hash,:engine_version,:indicator_version,:total_trades,:win_rate_pct,
                :rejection_reason,:policy_version,CAST(:strategy_definition AS JSONB),:owner_id,
                :source_run_id,:last_tested_session,:next_recheck_at,:revalidation_state,
                CAST(:trade_samples AS JSONB)
            ) ON CONFLICT (
                symbol,strategy_hash,settings_hash,engine_version,indicator_engine_version
            ) DO UPDATE SET
                stock_name=EXCLUDED.stock_name,strategy_name=EXCLUDED.strategy_name,
                total_trades=EXCLUDED.total_trades,win_rate_pct=EXCLUDED.win_rate_pct,
                rejection_reason=EXCLUDED.rejection_reason,policy_version=EXCLUDED.policy_version,
                strategy_definition=CASE
                    WHEN backtest_rejected_strategies.strategy_definition='{}'::jsonb
                    THEN EXCLUDED.strategy_definition
                    ELSE backtest_rejected_strategies.strategy_definition
                END,
                owner_id=COALESCE(EXCLUDED.owner_id,backtest_rejected_strategies.owner_id),
                source_run_id=COALESCE(EXCLUDED.source_run_id,backtest_rejected_strategies.source_run_id),
                last_tested_session=COALESCE(EXCLUDED.last_tested_session,backtest_rejected_strategies.last_tested_session),
                next_recheck_at=EXCLUDED.next_recheck_at,
                revalidation_state=EXCLUDED.revalidation_state,last_seen_at=NOW(),
                trade_samples=EXCLUDED.trade_samples,
                last_recheck_error=NULL
        """), [{
            "key": rejection_key(
                symbol=symbol, preset=preset, config=config,
                engine_version=engine_version, indicator_version=indicator_version,
            ),
            "symbol": symbol, "stock_name": stock_name,
            "strategy_id": preset.get("id"),
            "strategy_name": result.get("preset_name") or preset.get("name") or preset.get("id"),
            "strategy_hash": strategy_hash(preset),
            "settings_hash": settings_hash(
                config, preset, engine_version=engine_version, indicator_version=indicator_version,
            ),
            "engine_version": engine_version, "indicator_version": indicator_version,
            "total_trades": int(result.get("total_trades") or 0),
            "win_rate_pct": float(result.get("win_rate_pct") or 0),
            "rejection_reason": retention_failure_reason(result),
            "policy_version": RETENTION_POLICY_VERSION,
            "strategy_definition": "{}",
            "owner_id": owner_id, "source_run_id": source_run_id,
            "last_tested_session": technical.get("as_of_date"),
            "next_recheck_at": (
                datetime.now(timezone.utc) + timedelta(days=recheck_days)
                if is_revalidation_candidate(result) else None
            ),
            "revalidation_state": "frozen" if is_revalidation_candidate(result) else "ineligible",
            "trade_samples": json.dumps([
                {
                    key: trade.get(key) for key in (
                        "signal_date", "entry_date", "exit_date", "holding_days",
                        "exit_reason", "return_pct", "pnl",
                    )
                }
                for trade in list(result.get("trades") or [])
            ], default=str),
        } for result, preset in rejected])
    technical = dict(output.get("technical_snapshot") or {})
    if not retained or not technical.get("as_of_date"):
        return 0
    context = cache_context(
        session, symbol=symbol, start_date=date.fromisoformat(str(config["start_date"])),
        end_date=date.fromisoformat(str(config["end_date"])),
        data_source=str(config.get("data_source") or "merolagani"),
    )
    if not context:
        return 0
    data_session, data_hash = context
    stored = 0
    for result, preset in retained:
        key = artifact_key(symbol=symbol, preset=preset, config=config, data_session=data_session, data_hash=data_hash,
                           engine_version=engine_version, indicator_version=indicator_version)
        _upsert_artifact(
            session, key=key, symbol=symbol, preset=preset, config=config, data_session=data_session,
            data_hash=data_hash, engine_version=engine_version, indicator_version=indicator_version,
            result=result, market_profile=dict(output.get("market_profile") or {}), technical_snapshot=technical,
        )
        stored += 1
        session.execute(text("""
            UPDATE backtest_rejected_strategies
            SET total_trades=:total_trades,win_rate_pct=:win_rate_pct,
                revalidation_state='promoted',promoted_at=NOW(),next_recheck_at=NULL,
                last_seen_at=NOW()
            WHERE symbol=:symbol AND strategy_hash=:strategy_hash
              AND settings_hash=:settings_hash AND engine_version=:engine_version
              AND indicator_engine_version=:indicator_version
        """), {
            "symbol": symbol, "strategy_hash": strategy_hash(preset),
            "settings_hash": settings_hash(
                config, preset, engine_version=engine_version, indicator_version=indicator_version,
            ),
            "engine_version": engine_version, "indicator_version": indicator_version,
            "total_trades": int(result.get("total_trades") or 0),
            "win_rate_pct": float(result.get("win_rate_pct") or 0),
        })
    return stored
