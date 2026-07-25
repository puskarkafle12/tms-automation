"""Validated server-side querying for normalized backtest results."""

from __future__ import annotations

import csv
import io
import json
from math import ceil
from typing import Any, Dict, Iterable, List, Tuple

from sqlalchemy import text

from utils.backtesting.result_retention import (
    RETAINED_RESULT_SQL,
)
from utils.market_status import MARKET_HOURS_LABEL, get_market_hours_status, get_nepal_now


_LIVE_LTP_SQL = """COALESCE(
    NULLIF(regexp_replace(COALESCE(c.combined_data->>'ltp',c.combined_data->>'ml_ltp',c.combined_data->>'close',''),
           '[^0-9.-]','','g'),'')::double precision,s.ltp)"""
_LIVE_VOLUME_SQL = """COALESCE(
    NULLIF(regexp_replace(COALESCE(c.combined_data->>'qty',c.combined_data->>'volume',c.combined_data->>'ml_quantity',''),
           '[^0-9.-]','','g'),'')::double precision,s.latest_volume)"""


RESULT_FIELDS = {
    "result_id": "r.result_id", "run_id": "r.run_id", "symbol": "r.symbol", "preset_id": "r.preset_id",
    "preset_name": "r.preset_name", "preset_family": "r.preset_family", "category": "r.category",
    "bars": "r.bars", "total_trades": "r.total_trades", "wins": "r.wins", "losses": "r.losses",
    "win_rate_pct": "r.win_rate_pct", "win_rate_ci_low": "r.win_rate_ci_low",
    "win_rate_ci_high": "r.win_rate_ci_high", "confidence_score": "r.confidence_score",
    "robust_score": "r.robust_score", "net_return_pct": "r.net_return_pct",
    "max_drawdown_pct": "r.max_drawdown_pct", "sharpe_ratio": "r.sharpe_ratio",
    "sortino_ratio": "r.sortino_ratio", "profit_factor": "r.profit_factor",
    "expectancy_pct": "r.expectancy_pct", "exposure_pct": "r.exposure_pct",
    "oos_trades": "r.oos_trades", "oos_win_rate_pct": "r.oos_win_rate_pct",
    "oos_return_pct": "r.oos_return_pct", "oos_expectancy_pct": "r.oos_expectancy_pct",
    "oos_sharpe_ratio": "r.oos_sharpe_ratio", "oos_max_drawdown_pct": "r.oos_max_drawdown_pct",
    "walk_forward_profitable_pct": "r.walk_forward_profitable_pct", "fdr_q_value": "r.fdr_q_value",
    "data_completeness_pct": "r.data_completeness_pct", "liquidity_score": "r.liquidity_score",
    "sample_quality": "r.sample_quality", "recommendation_status": "r.recommendation_status",
    "security_type": "s.security_type", "sector": "s.sector", "listing_age_days": "s.listing_age_days",
    "ltp": "s.ltp", "latest_volume": "s.latest_volume", "average_volume_20": "s.average_volume_20",
    "median_volume_20": "s.median_volume_20",
    "average_turnover_20": "s.average_turnover_20", "warning_codes": "r.warning_codes",
    "technical_signal": "r.technical_snapshot->>'technical_signal'",
    "technical_signal_score": "NULLIF(r.technical_snapshot->>'technical_signal_score','')::double precision",
    "technical_buy_score": "NULLIF(r.technical_snapshot->>'technical_buy_score','')::double precision",
    "technical_sell_score": "NULLIF(r.technical_snapshot->>'technical_sell_score','')::double precision",
    "current_signal_active": "r.current_signal_active", "current_signal_status": "r.current_signal_status",
    "current_signal_date": "r.current_signal_date", "current_technical_score": "r.current_technical_score",
    "reliability_score": "r.reliability_score", "strong_buy_qualified": "r.strong_buy_qualified",
    "current_evidence": "r.current_evidence",
    "min_holding_days": "NULLIF(r.assumptions->>'min_holding_days','')::double precision",
    "max_holding_days": "NULLIF(r.assumptions->>'max_holding_days','')::double precision",
    "stop_loss_pct": "NULLIF(r.assumptions->>'stop_loss_pct','')::double precision",
    "take_profit_pct": "NULLIF(r.assumptions->>'take_profit_pct','')::double precision",
    "trailing_stop_pct": "NULLIF(r.assumptions->>'trailing_stop_pct','')::double precision",
    "slippage_pct_each_side": "NULLIF(r.assumptions->>'slippage_pct_each_side','')::double precision",
}

# A unique simulation is more specific than stock + preset. Daily end dates and
# calculated summaries are intentionally excluded so a continuing scan replaces
# its older equivalent while materially different risk/execution settings remain.
RESULT_CONFIGURATION_IDENTITY_SQL = "r.configuration_hash"

NUMERIC_FIELDS = {
    key for key in RESULT_FIELDS if key not in {
        "run_id", "symbol", "preset_id", "preset_name", "preset_family", "category", "sample_quality",
        "recommendation_status", "security_type", "sector", "technical_signal", "current_signal_status",
        "current_signal_date", "current_signal_active", "strong_buy_qualified", "warning_codes", "current_evidence",
    }
}
TEXT_FIELDS = set(RESULT_FIELDS) - NUMERIC_FIELDS - {"warning_codes"}
OPERATORS = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "contains": "ILIKE", "is_null": "IS NULL", "not_null": "IS NOT NULL"}


class ResultQueryError(ValueError):
    pass


def latest_completed_market_session(session):
    """Fetch the latest non-Saturday session through the date index."""
    return session.execute(text("""
        SELECT session_date
        FROM market_ohlcv_daily
        WHERE adjusted=TRUE AND session_date<=CURRENT_DATE
          AND EXTRACT(ISODOW FROM session_date)<>6
        ORDER BY session_date DESC
        LIMIT 1
    """)).scalar()


STRONG_BUY_SORT_FIELDS = {
    "symbol": "symbol", "current_signal_status": "current_signal_status",
    "preset_name": "preset_name", "recommendation_score": "recommendation_score",
    "ltp": "ltp", "current_signal_date": "current_signal_date",
    "win_rate_pct": "win_rate_pct", "wins": "wins", "losses": "losses",
    "total_trades": "total_trades", "average_holding_days": "average_holding_days",
    "loss_rate_pct": "loss_rate_pct", "confidence_score": "confidence_score",
    "net_return_pct": "net_return_pct", "net_profit": "net_profit",
    "profit_factor": "profit_factor", "max_drawdown_pct": "max_drawdown_pct",
    "sharpe_ratio": "sharpe_ratio", "reliability_score": "reliability_score",
    "condition_progress_pct": "condition_progress_pct", "latest_volume": "latest_volume",
    "average_volume_20": "average_volume_20",
}

STRONG_BUY_FILTER_TYPES = {
    "symbol": "text", "current_signal_status": "text", "preset_name": "text", "category": "text",
    "sector": "text", "recommendation_score": "number", "ltp": "number", "win_rate_pct": "number",
    "wins": "number", "losses": "number", "total_trades": "number", "average_holding_days": "number",
    "loss_rate_pct": "number", "confidence_score": "number", "net_return_pct": "number",
    "net_profit": "number", "profit_factor": "number", "max_drawdown_pct": "number",
    "sharpe_ratio": "number", "reliability_score": "number", "condition_progress_pct": "number",
    "latest_volume": "number", "average_volume_20": "number", "median_volume_20": "number",
}
STRONG_BUY_FILTER_OPERATORS = {
    "eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "contains": "ILIKE",
}


def compile_strong_buy_sorts(body: Dict[str, Any]) -> Tuple[str, List[Dict[str, str]]]:
    """Compile validated multi-column ordering for the recommendation table."""
    requested = body.get("sorts") or [{
        "field": str(body.get("sort_by") or "recommendation_score"),
        "direction": str(body.get("sort_direction") or "desc"),
    }]
    if not isinstance(requested, list) or len(requested) > 8:
        raise ResultQueryError("Recommendation sorting supports up to eight columns.")
    clauses: List[str] = []
    normalized: List[Dict[str, str]] = []
    seen = set()
    for item in requested:
        if not isinstance(item, dict):
            raise ResultQueryError("Each recommendation sort must contain a field and direction.")
        field = str(item.get("field") or "")
        direction = str(item.get("direction") or "desc").lower()
        if field not in STRONG_BUY_SORT_FIELDS or direction not in {"asc", "desc"}:
            raise ResultQueryError("Unsupported recommendation sort field or direction.")
        if field in seen:
            raise ResultQueryError(f"Recommendation sort field {field!r} was selected more than once.")
        seen.add(field)
        clauses.append(f"{STRONG_BUY_SORT_FIELDS[field]} {direction.upper()} NULLS LAST")
        normalized.append({"field": field, "direction": direction})
    return ",".join(clauses), normalized


def compile_strong_buy_filters(
    requested: Any, params: Dict[str, Any], recommendation_score_sql: str,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Compile the recommendation filter builder into parameterized SQL."""
    filters = requested or []
    if not isinstance(filters, list) or len(filters) > 12:
        raise ResultQueryError("Recommendation filtering supports up to twelve conditions.")
    expressions = {
        "symbol": "r.symbol", "current_signal_status": "r.current_signal_status",
        "preset_name": "r.preset_name", "category": "r.category", "sector": "s.sector",
        "recommendation_score": f"({recommendation_score_sql})", "ltp": _LIVE_LTP_SQL,
        "win_rate_pct": "r.win_rate_pct", "wins": "r.wins", "losses": "r.losses",
        "total_trades": "r.total_trades", "average_holding_days": "r.average_holding_days",
        "loss_rate_pct": "(100-COALESCE(r.win_rate_pct,0))", "confidence_score": "r.confidence_score",
        "net_return_pct": "r.net_return_pct",
        "net_profit": "NULLIF(r.assumptions->'summary'->>'net_profit','')::double precision",
        "profit_factor": "r.profit_factor", "max_drawdown_pct": "r.max_drawdown_pct",
        "sharpe_ratio": "r.sharpe_ratio", "reliability_score": "r.reliability_score",
        "condition_progress_pct": "COALESCE(NULLIF(r.current_evidence->>'condition_progress_pct','')::double precision,0)",
        "latest_volume": _LIVE_VOLUME_SQL, "average_volume_20": "s.average_volume_20",
        "median_volume_20": "s.median_volume_20",
    }
    clauses: List[str] = []
    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(filters):
        if not isinstance(item, dict):
            raise ResultQueryError("Each recommendation filter must contain a field, operator, and value.")
        field = str(item.get("field") or "")
        operator = str(item.get("operator") or "").lower()
        field_type = STRONG_BUY_FILTER_TYPES.get(field)
        if not field_type or operator not in STRONG_BUY_FILTER_OPERATORS:
            raise ResultQueryError("Unsupported recommendation filter field or operator.")
        if operator == "contains" and field_type != "text":
            raise ResultQueryError(f"contains is only valid for text fields ({field}).")
        if field_type == "text" and operator not in {"eq", "neq", "contains"}:
            raise ResultQueryError(f"{operator} is not valid for text field {field}.")
        value = item.get("value")
        if field_type == "number":
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise ResultQueryError(f"{field} requires a numeric value.") from exc
        else:
            value = str(value or "").strip()
            if not value:
                raise ResultQueryError(f"{field} requires a value.")
        param_name = f"advanced_filter_{index}"
        params[param_name] = f"%{value}%" if operator == "contains" else value
        clauses.append(f"{expressions[field]} {STRONG_BUY_FILTER_OPERATORS[operator]} :{param_name}")
        normalized.append({"field": field, "operator": operator, "value": value})
    return " AND ".join(clauses) or "TRUE", normalized


def field_catalog() -> List[Dict[str, Any]]:
    return [{"field": key, "type": "number" if key in NUMERIC_FIELDS else "text", "filterable": key != "warning_codes", "sortable": key != "warning_codes"} for key in RESULT_FIELDS]


def _compile_node(node: Dict[str, Any], params: Dict[str, Any], counter: List[int]) -> str:
    if "conditions" in node:
        joiner = " OR " if str(node.get("join") or "and").lower() == "or" else " AND "
        parts = [_compile_node(child, params, counter) for child in node.get("conditions") or []]
        parts = [part for part in parts if part]
        return f"({joiner.join(parts)})" if parts else ""
    field = str(node.get("field") or "")
    operator = str(node.get("operator") or "eq").lower()
    if field not in RESULT_FIELDS or field == "warning_codes" or operator not in OPERATORS:
        raise ResultQueryError(f"Unsupported result filter: {field or 'missing field'} {operator}.")
    if operator in {"contains"} and field not in TEXT_FIELDS:
        raise ResultQueryError(f"contains is only valid for text fields ({field}).")
    if operator in {"is_null", "not_null"}:
        return f"{RESULT_FIELDS[field]} {OPERATORS[operator]}"
    value = node.get("value")
    if field in NUMERIC_FIELDS:
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ResultQueryError(f"{field} requires a numeric value.") from exc
    else:
        value = str(value or "").strip()
        if not value:
            raise ResultQueryError(f"{field} requires a value.")
    name = f"filter_{counter[0]}"
    counter[0] += 1
    params[name] = f"%{value}%" if operator == "contains" else value
    return f"{RESULT_FIELDS[field]} {OPERATORS[operator]} :{name}"


def compile_filters(filters: Dict[str, Any] | None, *, include_non_equities: bool = False) -> Tuple[str, Dict[str, Any]]:
    params: Dict[str, Any] = {}
    root = filters or {"join": "and", "conditions": []}
    clause = _compile_node(root, params, [0])
    if not include_non_equities:
        ordinary = "s.security_type = 'ordinary_share'"
        clause = f"({clause}) AND {ordinary}" if clause else ordinary
    return clause or "TRUE", params


def compile_result_sorts(body: Dict[str, Any]) -> Tuple[str, str, List[Dict[str, str]]]:
    """Build validated inner/outer ordering for normal and de-duplicated result queries."""
    requested = body.get("sorts") or [{
        "field": str(body.get("sort_by") or "robust_score"),
        "direction": str(body.get("sort_direction") or "desc"),
    }]
    if not isinstance(requested, list) or not requested or len(requested) > 8:
        raise ResultQueryError("Result sorting requires between one and eight columns.")
    inner: List[str] = []
    outer: List[str] = []
    normalized: List[Dict[str, str]] = []
    seen = set()
    for item in requested:
        if not isinstance(item, dict):
            raise ResultQueryError("Each result sort must contain a field and direction.")
        field = str(item.get("field") or "")
        direction = str(item.get("direction") or "desc").lower()
        if field not in RESULT_FIELDS or field == "warning_codes" or direction not in {"asc", "desc"}:
            raise ResultQueryError("Unsupported result sort field or direction.")
        if field in seen:
            raise ResultQueryError(f"Result sort field {field!r} was selected more than once.")
        seen.add(field)
        sql_direction = direction.upper()
        inner.append(f"{RESULT_FIELDS[field]} {sql_direction} NULLS LAST")
        outer.append(f"{field} {sql_direction} NULLS LAST")
        normalized.append({"field": field, "direction": direction})
    if "total_trades" not in seen:
        inner.append("r.total_trades DESC NULLS LAST")
        outer.append("total_trades DESC NULLS LAST")
    if "result_id" not in seen:
        inner.append("r.result_id ASC")
        outer.append("result_id ASC")
    return ",".join(inner), ",".join(outer), normalized


def _with_ipo_trade_floor(where: str) -> str:
    """IPO result tables only rank simulations that produced at least one trade.

    Zero-trade rows all share win_rate=0 and crowd the ranking with noise that
    cannot be interpreted as swing performance.
    """
    floor = "r.total_trades > 0"
    if not where or where == "TRUE":
        return floor
    return f"({where}) AND {floor}"


def _ipo_cache_counts(session, *, run_id: str, owner_id: str) -> Dict[str, int]:
    row = session.execute(text("""
        SELECT COUNT(*)::INTEGER AS cached_total,
               COUNT(*) FILTER (WHERE COALESCE(total_trades, 0) > 0)::INTEGER AS trade_outcomes,
               COUNT(*) FILTER (WHERE COALESCE(total_trades, 0) <= 0)::INTEGER AS zero_trade_outcomes
        FROM backtest_rejected_strategies
        WHERE source_run_id=:run_id
          AND (owner_id=:owner_id OR owner_id IS NULL)
    """), {"run_id": run_id, "owner_id": owner_id}).mappings().one()
    return {
        "cached_total": int(row["cached_total"] or 0),
        "trade_outcomes": int(row["trade_outcomes"] or 0),
        "zero_trade_outcomes": int(row["zero_trade_outcomes"] or 0),
    }


def _query_ipo_cached_results(
    session, run_id: str, body: Dict[str, Any], *, owner_id: str,
) -> Dict[str, Any]:
    """Expose IPO scan outcomes that produced trades, without promoting them.

    IPO research is intentionally sparse: low-evidence outcomes are stored in
    ``backtest_rejected_strategies`` instead of the retained-results table.
    Zero-trade simulations stay in the cache for progress accounting but are
    excluded from the research table by default — a 0% win rate with 0 trades is
    not a meaningful swing result. Pass ``include_zero_trade_simulations`` to
    inspect the raw cache while a sparse IPO is still filling trade evidence.
    """
    page = max(1, int(body.get("page") or 1))
    page_size = min(100, max(1, int(body.get("page_size") or 100)))
    inner_order, _, sorts = compile_result_sorts(body)
    where, params = compile_filters(
        body.get("filters"), include_non_equities=bool(body.get("include_non_equities")),
    )
    include_zero_trades = bool(body.get("include_zero_trade_simulations"))
    if not include_zero_trades:
        where = _with_ipo_trade_floor(where)
    params.update({"run_id": run_id, "owner_id": owner_id, "limit": page_size,
                   "offset": (page - 1) * page_size})
    cache_counts = _ipo_cache_counts(session, run_id=run_id, owner_id=owner_id)
    requested_fields = [
        str(field) for field in body.get("select_fields") or []
        if str(field) in RESULT_FIELDS
    ]
    selected_keys = list(dict.fromkeys(["result_id", "run_id", *requested_fields])) if requested_fields else list(RESULT_FIELDS)
    select = ",".join(f"{RESULT_FIELDS[key]} AS {key}" for key in selected_keys)
    cached_rows = """
        WITH ipo_cached_rows AS (
            SELECT
                (-ROW_NUMBER() OVER (ORDER BY rejected.rejection_key))::BIGINT AS result_id,
                rejected.rejection_key AS cache_key,
                CAST(:run_id AS VARCHAR) AS run_id,
                rejected.symbol, rejected.strategy_id AS preset_id,
                rejected.strategy_name AS preset_name,
                'ipo_cached'::VARCHAR AS preset_family,
                'New IPO cached evidence'::VARCHAR AS category,
                0::INTEGER AS bars,
                rejected.total_trades,
                ROUND(rejected.total_trades * rejected.win_rate_pct / 100.0)::INTEGER AS wins,
                GREATEST(0, rejected.total_trades - ROUND(rejected.total_trades * rejected.win_rate_pct / 100.0)::INTEGER) AS losses,
                rejected.win_rate_pct,
                NULL::DOUBLE PRECISION AS win_rate_ci_low,
                NULL::DOUBLE PRECISION AS win_rate_ci_high,
                0::DOUBLE PRECISION AS confidence_score,
                0::DOUBLE PRECISION AS robust_score,
                NULL::DOUBLE PRECISION AS net_return_pct,
                NULL::DOUBLE PRECISION AS max_drawdown_pct,
                NULL::DOUBLE PRECISION AS sharpe_ratio,
                NULL::DOUBLE PRECISION AS sortino_ratio,
                NULL::DOUBLE PRECISION AS profit_factor,
                NULL::DOUBLE PRECISION AS expectancy_pct,
                NULL::DOUBLE PRECISION AS exposure_pct,
                NULL::DOUBLE PRECISION AS average_holding_days,
                0::INTEGER AS oos_trades,
                NULL::DOUBLE PRECISION AS oos_win_rate_pct,
                NULL::DOUBLE PRECISION AS oos_return_pct,
                NULL::DOUBLE PRECISION AS oos_expectancy_pct,
                NULL::DOUBLE PRECISION AS oos_sharpe_ratio,
                NULL::DOUBLE PRECISION AS oos_max_drawdown_pct,
                NULL::DOUBLE PRECISION AS walk_forward_profitable_pct,
                NULL::DOUBLE PRECISION AS fdr_q_value,
                NULL::DOUBLE PRECISION AS data_completeness_pct,
                NULL::DOUBLE PRECISION AS liquidity_score,
                'cached_low_evidence'::VARCHAR AS sample_quality,
                'cached_not_recommended'::VARCHAR AS recommendation_status,
                jsonb_build_array('Below normal retention; shown only in this IPO research workspace.') AS warning_codes,
                rejected.latest_signal_evidence AS technical_snapshot,
                FALSE AS current_signal_active,
                COALESCE(rejected.latest_signal_status, 'no_signal') AS current_signal_status,
                rejected.latest_signal_date AS current_signal_date,
                0::DOUBLE PRECISION AS current_technical_score,
                0::DOUBLE PRECISION AS reliability_score,
                FALSE AS strong_buy_qualified,
                rejected.latest_signal_evidence AS current_evidence,
                rejected.strategy_definition AS assumptions
            FROM backtest_rejected_strategies rejected
            WHERE rejected.source_run_id=:run_id
              AND (rejected.owner_id=:owner_id OR rejected.owner_id IS NULL)
        )
    """
    base = "FROM ipo_cached_rows r JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol"
    total = int(session.execute(text(f"{cached_rows} SELECT COUNT(*) {base} WHERE {where}"), params).scalar() or 0)
    rows = session.execute(text(
        f"{cached_rows} SELECT {select},r.cache_key {base} WHERE {where} "
        f"ORDER BY {inner_order} LIMIT :limit OFFSET :offset"
    ), params).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        item["warning_codes"] = list(item.get("warning_codes") or [])
        item["cached_evidence"] = True
        items.append(item)
    return {
        "items": items, "page": page, "page_size": page_size, "total": total,
        "pages": ceil(total / page_size) if total else 0, "sorts": sorts,
        "sort_by": sorts[0]["field"], "sort_direction": sorts[0]["direction"],
        "unique_by_symbol": False, "unique_by_strategy": False,
        "selected_columns": selected_keys, "cache_only": True,
        "include_zero_trade_simulations": include_zero_trades,
        **cache_counts,
    }


def query_results(session, run_id: str, body: Dict[str, Any], *, owner_id: str = "local") -> Dict[str, Any]:
    if run_id != "all":
        run_type = session.execute(text("""
            SELECT run_type FROM backtest_runs
            WHERE run_id=:run_id AND owner_id=:owner_id
              AND deleted_at IS NULL AND archived_at IS NULL
        """), {"run_id": run_id, "owner_id": owner_id}).scalar()
        if run_type == "ipo_research":
            return _query_ipo_cached_results(session, run_id, body, owner_id=owner_id)
    page = max(1, int(body.get("page") or 1))
    page_size = min(100, max(1, int(body.get("page_size") or 100)))
    inner_order, outer_order, sorts = compile_result_sorts(body)
    where, params = compile_filters(body.get("filters"), include_non_equities=bool(body.get("include_non_equities")))
    where = f"({where}) AND {RETAINED_RESULT_SQL}"
    params.update({"run_id": run_id, "owner_id": owner_id, "limit": page_size, "offset": (page - 1) * page_size})
    ownership = "br.owner_id=:owner_id AND br.deleted_at IS NULL AND br.archived_at IS NULL"
    scope = "(:run_id='all' OR r.run_id=:run_id)"
    normal_all_runs = "(:run_id<>'all' OR br.run_type<>'ipo_research')"
    base = "FROM backtest_results r JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol JOIN backtest_runs br ON br.run_id=r.run_id"
    requested_fields = [
        str(field) for field in body.get("select_fields") or []
        if str(field) in RESULT_FIELDS
    ]
    selected_keys = list(dict.fromkeys(["result_id", "run_id", *requested_fields])) if requested_fields else list(RESULT_FIELDS)
    select = ",".join(f"{RESULT_FIELDS[key]} AS {key}" for key in selected_keys)
    unique_by_symbol = bool(body.get("unique_by_symbol"))
    unique_by_strategy = bool(body.get("unique_by_strategy"))
    if unique_by_symbol:
        total = int(session.execute(text(f"SELECT COUNT(DISTINCT r.symbol) {base} WHERE {scope} AND {normal_all_runs} AND {ownership} AND {where}"), params).scalar() or 0)
        rows = session.execute(text(
            f"WITH ranked_ids AS (SELECT r.result_id,ROW_NUMBER() OVER (PARTITION BY r.symbol "
            f"ORDER BY {inner_order}) AS selected_rank "
            f"{base} WHERE {scope} AND {normal_all_runs} AND {ownership} AND {where}) "
            f"SELECT {select} {base} JOIN ranked_ids selected ON selected.result_id=r.result_id "
            f"WHERE selected.selected_rank=1 "
            f"ORDER BY {outer_order} LIMIT :limit OFFSET :offset"
        ), params).mappings().all()
    elif unique_by_strategy:
        canonical_base = f"{base} JOIN backtest_canonical_results canonical ON canonical.result_id=r.result_id AND canonical.owner_id=:owner_id"
        explicit_where, _ = compile_filters(body.get("filters"), include_non_equities=True)
        if explicit_where == "TRUE":
            canonical_security = "TRUE" if body.get("include_non_equities") else "canonical.security_type='ordinary_share'"
            total = int(session.execute(text(
                "SELECT COUNT(*) FROM backtest_canonical_results canonical "
                "JOIN backtest_runs br ON br.run_id=canonical.run_id "
                "WHERE canonical.owner_id=:owner_id AND (:run_id='all' OR canonical.run_id=:run_id) "
                f"AND {normal_all_runs} "
                f"AND {canonical_security}"
            ), params).scalar() or 0)
        else:
            total = int(session.execute(text(
                f"SELECT COUNT(*) {canonical_base} WHERE {scope} AND {normal_all_runs} AND {ownership} AND {where}"
            ), params).scalar() or 0)
        rows = session.execute(text(
            f"SELECT {select} {canonical_base} WHERE {scope} AND {normal_all_runs} AND {ownership} AND {where} "
            f"ORDER BY {outer_order} LIMIT :limit OFFSET :offset"
        ), params).mappings().all()
    else:
        total = int(session.execute(text(f"SELECT COUNT(*) {base} WHERE {scope} AND {normal_all_runs} AND {ownership} AND {where}"), params).scalar() or 0)
        rows = session.execute(text(
            f"SELECT {select} {base} WHERE {scope} AND {normal_all_runs} AND {ownership} AND {where} "
            f"ORDER BY {inner_order} LIMIT :limit OFFSET :offset"
        ), params).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        item["warning_codes"] = list(item.get("warning_codes") or [])
        items.append(item)
    return {"items": items, "page": page, "page_size": page_size, "total": total, "pages": ceil(total / page_size) if total else 0, "sorts": sorts, "sort_by": sorts[0]["field"], "sort_direction": sorts[0]["direction"], "unique_by_symbol": unique_by_symbol, "unique_by_strategy": unique_by_strategy, "selected_columns": selected_keys}


def query_result_selections(
    session, run_id: str, body: Dict[str, Any], *, owner_id: str = "local",
) -> List[Dict[str, str]]:
    """Resolve exact run × symbol × strategy rows matching finalized filters."""
    where, params = compile_filters(
        body.get("filters"), include_non_equities=bool(body.get("include_non_equities")),
    )
    where = f"({where}) AND {RETAINED_RESULT_SQL}"
    params.update({"run_id": run_id, "owner_id": owner_id})
    ownership = "br.owner_id=:owner_id AND br.deleted_at IS NULL AND br.archived_at IS NULL"
    scope = "(:run_id='all' OR r.run_id=:run_id)"
    normal_all_runs = "(:run_id<>'all' OR br.run_type<>'ipo_research')"
    base = "FROM backtest_results r JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol JOIN backtest_runs br ON br.run_id=r.run_id"
    if body.get("unique_by_symbol"):
        inner_order, _, _ = compile_result_sorts(body)
        statement = text(
            f"WITH ranked AS (SELECT r.run_id,r.symbol,r.preset_id,ROW_NUMBER() OVER (PARTITION BY r.symbol ORDER BY {inner_order}) AS selected_rank "
            f"{base} WHERE {scope} AND {normal_all_runs} AND {ownership} AND {where}) "
            "SELECT run_id,symbol,preset_id FROM ranked WHERE selected_rank=1 ORDER BY run_id,symbol,preset_id"
        )
    elif body.get("unique_by_strategy"):
        statement = text(
            f"SELECT DISTINCT r.run_id,r.symbol,r.preset_id {base} "
            "JOIN backtest_canonical_results canonical ON canonical.result_id=r.result_id AND canonical.owner_id=:owner_id "
            f"WHERE {scope} AND {normal_all_runs} AND {ownership} AND {where} ORDER BY r.run_id,r.symbol,r.preset_id"
        )
    else:
        statement = text(
            f"SELECT DISTINCT r.run_id,r.symbol,r.preset_id {base} "
            f"WHERE {scope} AND {normal_all_runs} AND {ownership} AND {where} ORDER BY r.run_id,r.symbol,r.preset_id"
        )
    return [
        {"run_id": str(row["run_id"]), "symbol": str(row["symbol"]), "preset_id": str(row["preset_id"])}
        for row in session.execute(statement, params).mappings().all()
    ]


def query_result_symbols(
    session, run_id: str, body: Dict[str, Any], *, owner_id: str = "local",
) -> List[str]:
    return sorted({item["symbol"] for item in query_result_selections(session, run_id, body, owner_id=owner_id)})


def _csv_row_from_result(item: Dict[str, Any]) -> Dict[str, Any]:
    row = {key: item.get(key) for key in RESULT_FIELDS}
    for key, value in list(row.items()):
        if isinstance(value, (dict, list)):
            row[key] = json.dumps(value, separators=(",", ":"), default=str)
    return row


def stream_results_csv(session_factory, run_id: str, body: Dict[str, Any], *, owner_id: str):
    """Stream every matching normalized result without loading the export into memory."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(RESULT_FIELDS), extrasaction="ignore")
    writer.writeheader()
    yield buffer.getvalue(); buffer.seek(0); buffer.truncate(0)
    session = session_factory()
    try:
        run_type = None
        if run_id != "all":
            run_type = session.execute(text("""
                SELECT run_type FROM backtest_runs
                WHERE run_id=:run_id AND owner_id=:owner_id
                  AND deleted_at IS NULL AND archived_at IS NULL
            """), {"run_id": run_id, "owner_id": owner_id}).scalar()
        # IPO outcomes live in the rejection cache, not backtest_results.
        if run_type == "ipo_research":
            page = 1
            page_size = 500
            while True:
                payload = query_results(
                    session, run_id,
                    {**body, "page": page, "page_size": page_size},
                    owner_id=owner_id,
                )
                items = list(payload.get("items") or [])
                if not items:
                    break
                for item in items:
                    writer.writerow(_csv_row_from_result(item))
                    if buffer.tell() >= 64 * 1024:
                        yield buffer.getvalue(); buffer.seek(0); buffer.truncate(0)
                if page >= int(payload.get("pages") or 0):
                    break
                page += 1
            if buffer.tell():
                yield buffer.getvalue()
            return

        inner_order, _, _ = compile_result_sorts(body)
        where, params = compile_filters(
            body.get("filters"), include_non_equities=bool(body.get("include_non_equities")),
        )
        where = f"({where}) AND {RETAINED_RESULT_SQL}"
        params.update({"run_id": run_id, "owner_id": owner_id})
        ownership = "br.owner_id=:owner_id AND br.deleted_at IS NULL AND br.archived_at IS NULL"
        base = (
            "FROM backtest_results r "
            "JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol "
            "JOIN backtest_runs br ON br.run_id=r.run_id"
        )
        select = ",".join(f"{column} AS {key}" for key, column in RESULT_FIELDS.items())
        statement = text(
            f"SELECT {select} {base} WHERE (:run_id='all' OR r.run_id=:run_id) AND {ownership} AND {where} "
            f"ORDER BY {inner_order}"
        )
        for row in session.execute(statement, params).mappings().yield_per(1000):
            writer.writerow(_csv_row_from_result(dict(row)))
            if buffer.tell() >= 64 * 1024:
                yield buffer.getvalue(); buffer.seek(0); buffer.truncate(0)
        if buffer.tell():
            yield buffer.getvalue()
    finally:
        session.close()


def _cached_ipo_result_detail(session, cache_key: str, *, owner_id: str) -> Dict[str, Any]:
    """Return an audit-only result shape for one IPO cache entry.

    This deliberately reads the rejection cache rather than inserting a normal
    backtest result, so opening a chart never promotes it to recommendations.
    """
    row = session.execute(text("""
        SELECT rejected.rejection_key AS cache_key,rejected.source_run_id AS run_id,
               rejected.symbol,rejected.strategy_id AS preset_id,rejected.strategy_name AS preset_name,
               'New IPO cached evidence' AS category,rejected.total_trades,
               ROUND(rejected.total_trades * rejected.win_rate_pct / 100.0)::INTEGER AS wins,
               GREATEST(0,rejected.total_trades-ROUND(rejected.total_trades * rejected.win_rate_pct / 100.0)::INTEGER) AS losses,
               rejected.win_rate_pct,rejected.latest_signal_status AS current_signal_status,
               rejected.latest_signal_date AS current_signal_date,rejected.latest_signal_evidence AS current_evidence,
               rejected.latest_signal_evidence AS technical_snapshot,rejected.trade_samples,
               COALESCE(NULLIF(rejected.strategy_definition,'{}'::jsonb),definition.definition,'{}'::jsonb) AS assumptions,
               run.configuration AS run_configuration,s.ltp,s.latest_volume,s.average_volume_20,s.sector
        FROM backtest_rejected_strategies rejected
        JOIN backtest_runs run ON run.run_id=rejected.source_run_id
        JOIN backtest_run_symbols s ON s.run_id=run.run_id AND s.symbol=rejected.symbol
        LEFT JOIN backtest_strategy_definitions definition ON definition.strategy_hash=rejected.strategy_hash
        WHERE rejected.rejection_key=:cache_key
          AND (rejected.owner_id=:owner_id OR rejected.owner_id IS NULL)
          AND run.owner_id=:owner_id
          AND run.run_type='ipo_research' AND run.deleted_at IS NULL AND run.archived_at IS NULL
    """), {"cache_key": cache_key, "owner_id": owner_id}).mappings().first()
    if not row:
        raise ResultQueryError("Cached IPO research result was not found.")
    output = dict(row)
    assumptions = dict(output.get("assumptions") or {})
    configuration = dict(output.pop("run_configuration") or {})
    assumptions.setdefault("period", {
        "start": configuration.get("start_date"), "end": configuration.get("end_date"),
    })
    assumptions.setdefault("initial_capital", configuration.get("initial_capital") or 100000)
    output.update({
        "assumptions": assumptions, "warning_codes": [
            "Below normal retention; IPO research only and not a recommendation."
        ], "recommendation_status": "cached_not_recommended", "sample_quality": "cached_low_evidence",
        "current_signal_active": False, "current_technical_score": 0.0,
        "reliability_score": 0.0, "strong_buy_qualified": False,
        "net_return_pct": None, "max_drawdown_pct": None, "sharpe_ratio": None,
        "sortino_ratio": None, "profit_factor": None, "expectancy_pct": None,
        "confidence_score": 0.0, "average_holding_days": None,
    })
    return output


def result_detail(session, result_id: int, *, owner_id: str = "local", cache_key: str | None = None) -> Dict[str, Any]:
    if cache_key:
        return _cached_ipo_result_detail(session, cache_key, owner_id=owner_id)
    select = ",".join(f"{column} AS {key}" for key, column in RESULT_FIELDS.items())
    row = session.execute(text(
        f"SELECT {select},r.assumptions,r.technical_snapshot FROM backtest_results r "
        "JOIN backtest_runs br ON br.run_id=r.run_id JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol "
        f"WHERE r.result_id=:result_id AND br.owner_id=:owner_id AND br.deleted_at IS NULL "
        f"AND br.archived_at IS NULL AND {RETAINED_RESULT_SQL}"
    ), {"result_id": result_id, "owner_id": owner_id}).mappings().first()
    if not row:
        raise ResultQueryError("Backtest result was not found.")
    output = dict(row)
    output["warning_codes"] = list(output.get("warning_codes") or [])
    return output


def result_trades(session, result_id: int, *, owner_id: str = "local", cache_key: str | None = None) -> List[Dict[str, Any]]:
    if cache_key:
        detail = _cached_ipo_result_detail(session, cache_key, owner_id=owner_id)
        trades = list(detail.get("trade_samples") or [])
        normalized = []
        for index, raw in enumerate(trades, start=1):
            trade = dict(raw or {})
            return_pct = float(trade.get("return_pct") or 0)
            normalized.append({
                "trade_id": -index, "sequence_no": index, "signal_date": trade.get("signal_date"),
                "entry_date": trade.get("entry_date"), "entry_price": trade.get("entry_price"),
                "exit_date": trade.get("exit_date"), "exit_price": trade.get("exit_price"),
                "holding_days": trade.get("holding_days") or 0, "exit_reason": trade.get("exit_reason") or "saved exit",
                "return_pct": return_pct, "gross_return_pct": return_pct, "pnl": trade.get("pnl") or 0,
                "result": "win" if return_pct >= 0 else "loss", "quantity": 0,
                "broker_commission": 0, "sebon_fee": 0, "dp_charge": 0, "capital_gains_tax": 0,
                "capital_gains_tax_rate_pct": 0, "total_charges": 0,
            })
        return normalized
    rows = session.execute(text(
        "SELECT t.* FROM backtest_trades t JOIN backtest_results r ON r.result_id=t.result_id "
        "JOIN backtest_runs br ON br.run_id=r.run_id WHERE t.result_id=:result_id AND br.owner_id=:owner_id "
        f"AND {RETAINED_RESULT_SQL} ORDER BY t.sequence_no"
    ), {"result_id": result_id, "owner_id": owner_id}).mappings().all()
    return [{**dict(row), "signal_date": row["signal_date"].isoformat() if row["signal_date"] else None,
             "entry_date": row["entry_date"].isoformat(), "exit_date": row["exit_date"].isoformat()} for row in rows]


def query_strong_buys(session, run_id: str, body: Dict[str, Any], *, owner_id: str = "local") -> Dict[str, Any]:
    page = max(1, int(body.get("page") or 1))
    page_size = min(100, max(1, int(body.get("page_size") or 25)))
    order_sql, normalized_sorts = compile_strong_buy_sorts(body)
    fresh_session = latest_completed_market_session(session)
    params = {
        "run_id": run_id, "owner_id": owner_id,
        "min_trades": max(0, int(body.get("minimum_trades", 0))),
        "min_win": max(0, float(body.get("minimum_win_rate", 0))),
        "min_confidence": float(body.get("minimum_confidence", 0)),
        "min_sharpe": float(body.get("minimum_sharpe", -999)), "min_pf": float(body.get("minimum_profit_factor", 0)),
        "max_dd": float(body.get("maximum_drawdown", 100)), "min_return": float(body.get("minimum_return", 0)),
        "min_volume": float(body.get("minimum_volume") or 0), "category": str(body.get("category") or ""),
        "signal": str(body.get("current_signal") or "all"), "latest_date": body.get("latest_signal_date"),
        "limit": page_size, "offset": (page - 1) * page_size, "fresh_session": fresh_session,
    }
    universe = "TRUE" if body.get("include_non_equities") else "s.security_type='ordinary_share'"
    signal_mode = params["signal"]
    signal_requirements = {
        "all": "TRUE",
        "triggered_today": "r.current_signal_active=TRUE AND r.current_signal_status IN ('strong_buy','buy','watch')",
        "near_trigger": "r.current_signal_active=FALSE AND r.current_signal_status='near_trigger'",
        "strong_buy": "r.current_signal_active=TRUE AND r.current_signal_status='strong_buy'",
        "buy": "r.current_signal_active=TRUE AND r.current_signal_status IN ('strong_buy','buy')",
        "watch": "r.current_signal_active=TRUE AND r.current_signal_status='watch'",
        "no_signal": "r.current_signal_active=FALSE AND r.current_signal_status IN ('no_signal','stale')",
    }
    if signal_mode not in signal_requirements:
        raise ResultQueryError("Unsupported current-signal filter.")
    # Default "best pick" ranking: reward validated return and consistency,
    # while explicitly penalizing drawdown. Raw return/win rate alone must not
    # place a fragile strategy at the top of the Buy table.
    recommendation_score = """ROUND((
        GREATEST(0,LEAST(100,COALESCE(r.robust_score,r.reliability_score,0)))*0.35
        + GREATEST(0,LEAST(100,COALESCE(r.net_return_pct,0)))*0.20
        + GREATEST(0,LEAST(100,COALESCE(r.sharpe_ratio,0)*25))*0.15
        + GREATEST(0,100-LEAST(100,COALESCE(r.max_drawdown_pct,100)*2.5))*0.20
        + GREATEST(0,LEAST(100,(COALESCE(r.profit_factor,1)-1)*50))*0.10
    )::numeric,2)::double precision"""
    advanced_where, normalized_filters = compile_strong_buy_filters(body.get("filters"), params, recommendation_score)
    requirements = f"""{signal_requirements[signal_mode]}
        AND {RETAINED_RESULT_SQL}
        AND r.total_trades>=:min_trades AND r.win_rate_pct>=:min_win AND r.confidence_score>=:min_confidence
        AND r.net_return_pct>=:min_return AND (r.profit_factor IS NULL OR r.profit_factor>=:min_pf)
        AND COALESCE(r.sharpe_ratio,-999)>=:min_sharpe AND r.max_drawdown_pct<=:max_dd
        AND COALESCE({_LIVE_VOLUME_SQL},0)>=:min_volume
        AND (:category='' OR r.category=:category)
        AND (:latest_date IS NULL OR r.current_signal_date>=CAST(:latest_date AS DATE))
        AND (:fresh_session IS NULL OR r.current_signal_date=CAST(:fresh_session AS DATE)
             OR (r.current_signal_date=CAST(:fresh_session AS DATE)+1
                 AND EXTRACT(ISODOW FROM r.current_signal_date)=6))
        AND {advanced_where}"""
    columns = f"""r.result_id,r.run_id,r.symbol,r.preset_id,r.preset_name,r.category,r.current_signal_status,
        CASE WHEN :fresh_session IS NOT NULL
                   AND r.current_signal_date=CAST(:fresh_session AS DATE)+1
                   AND EXTRACT(ISODOW FROM r.current_signal_date)=6
             THEN CAST(:fresh_session AS DATE) ELSE r.current_signal_date END AS current_signal_date,
        r.reliability_score,r.current_technical_score,r.win_rate_pct,r.wins,r.losses,
        r.total_trades,r.average_holding_days,r.confidence_score,r.net_return_pct,r.profit_factor,r.max_drawdown_pct,r.sharpe_ratio,
        r.current_evidence,r.assumptions,s.security_type,s.sector,{_LIVE_LTP_SQL} AS ltp,{_LIVE_VOLUME_SQL} AS latest_volume,
        s.average_volume_20,s.median_volume_20,
        NULLIF(r.assumptions->'summary'->>'net_profit','')::double precision AS net_profit,
        100-COALESCE(r.win_rate_pct,0) AS loss_rate_pct,
        COALESCE(NULLIF(r.current_evidence->>'condition_progress_pct','')::double precision,0) AS condition_progress_pct,
        CASE WHEN COALESCE(r.assumptions->>'charge_model','') LIKE 'nepse_equity%' THEN FALSE ELSE TRUE END AS legacy_cost_model,
        COALESCE(c.combined_data->>'company_name',c.combined_data->>'name',c.combined_data->>'companyName',r.symbol) AS company_name"""
    base = f"""FROM backtest_results r JOIN backtest_runs br ON br.run_id=r.run_id
        JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol
        LEFT JOIN market_screener_cache c ON c.symbol=r.symbol
        WHERE (:run_id='all' OR r.run_id=:run_id) AND br.owner_id=:owner_id
          AND (:run_id<>'all' OR br.run_type<>'ipo_research')
          AND br.deleted_at IS NULL AND br.archived_at IS NULL AND {universe} AND {requirements}"""
    cte = f"""WITH candidates AS (SELECT {columns},{recommendation_score} AS recommendation_score,
        ROW_NUMBER() OVER(PARTITION BY r.symbol ORDER BY {recommendation_score} DESC,
            NULLIF(r.assumptions->'summary'->>'net_profit','')::double precision DESC NULLS LAST,
            r.win_rate_pct DESC,r.total_trades DESC,r.result_id) row_no {base})"""
    total = int(session.execute(text(f"{cte} SELECT COUNT(*) FROM candidates WHERE row_no=1"), params).scalar() or 0)
    rows = session.execute(text(
        f"{cte} SELECT * FROM candidates WHERE row_no=1 ORDER BY {order_sql},symbol ASC,result_id ASC LIMIT :limit OFFSET :offset"
    ), params).mappings().all()
    items = []
    for rank, row in enumerate(rows, start=(page - 1) * page_size + 1):
        item = dict(row)
        item.update({"rank": rank, "loss_rate_pct": round(100 - float(item.get("win_rate_pct") or 0), 2),
                     "signal_date": item.pop("current_signal_date"),
                     "recommendation_score_version": "risk-adjusted-v2"})
        item.update(_strategy_planning_range(item))
        item.pop("row_no", None)
        items.append(item)
    nepal_now = get_nepal_now()
    market_status = get_market_hours_status(nepal_now)
    return {"items": items, "page": page, "page_size": page_size, "total": total,
            "pages": ceil(total / page_size) if total else 0,
            "sorts": normalized_sorts,
            "filters": normalized_filters,
            "scope": "all_deduplicated_runs" if run_id == "all" else "single_run",
            "freshness": {"latest_completed_session": fresh_session.isoformat() if fresh_session else None,
                          "status": "fresh_trading_session_only", "trading_calendar": MARKET_HOURS_LABEL,
                          "checked_at_nepal": nepal_now.isoformat(),
                          "is_trading_day_today": market_status["is_trading_day"]},
            "disclaimer": "Backtested historical performance does not guarantee future results."}


def _strategy_planning_range(item: Dict[str, Any]) -> Dict[str, Any]:
    """Create transparent ATR-sized planning zones from the saved strategy risk settings."""
    if str(item.get("current_signal_status") or "") not in {"strong_buy", "buy", "watch", "near_trigger"}:
        return {"buy_zone_low": None, "buy_zone_high": None, "protective_stop": None,
                "sell_zone_low": None, "sell_zone_high": None, "planning_range_basis": None}
    try:
        price = float(item.get("ltp") or 0)
    except (TypeError, ValueError):
        price = 0
    if price <= 0:
        return {"buy_zone_low": None, "buy_zone_high": None, "protective_stop": None,
                "sell_zone_low": None, "sell_zone_high": None, "planning_range_basis": None}
    evidence = dict(item.get("current_evidence") or {})
    assumptions = dict(item.get("assumptions") or {})
    latest = {
        **dict(assumptions.get("protection_latest_values") or {}),
        **dict(evidence.get("latest_values") or {}),
    }
    try:
        atr_pct = float(latest.get("technical_atr_percent") or 2)
    except (TypeError, ValueError):
        atr_pct = 2
    try:
        stop_pct = float(assumptions.get("stop_loss_pct") or 5)
        target_pct = float(assumptions.get("take_profit_pct") or 10)
    except (TypeError, ValueError):
        stop_pct, target_pct = 5, 10
    entry_buffer_pct = max(.4, min(2.5, atr_pct * .25))
    exit_rule_id = str(assumptions.get("exit_rule_id") or "")
    sell_basis = f"Fixed +{target_pct:g}% take-profit"
    sell_low = sell_high = None
    if exit_rule_id == "sr_resistance_rejection_exit":
        sell_low = latest.get("technical_sr_resistance_lower")
        sell_high = latest.get("technical_sr_resistance_upper")
        sell_basis = "Current causal resistance zone"
    elif exit_rule_id == "bollinger_middle_exit":
        sell_low = sell_high = latest.get("technical_bollinger_middle_20")
        sell_basis = "Current Bollinger middle band"
    elif exit_rule_id == "bollinger_upper_rejection_exit":
        sell_low = sell_high = latest.get("technical_bollinger_upper_20")
        sell_basis = "Current Bollinger upper band"
    elif exit_rule_id == "fibonacci_resistance_exit":
        sell_low = sell_high = latest.get("technical_fib_range_high_63")
        sell_basis = "Current past-only Fibonacci range resistance"
    try:
        sell_low = float(sell_low) if sell_low is not None else None
        sell_high = float(sell_high) if sell_high is not None else None
    except (TypeError, ValueError):
        sell_low = sell_high = None
    target_price = price * (1 + target_pct / 100)
    target_buffer_pct = entry_buffer_pct * .5
    if not sell_low or not sell_high:
        sell_low = target_price * (1 - target_buffer_pct / 100)
        sell_high = target_price * (1 + target_buffer_pct / 100)
    protective_stop = price * (1 - stop_pct / 100)
    try:
        atr_multiple = float(assumptions.get("atr_stop_multiple")) if assumptions.get("atr_stop_multiple") is not None else None
        atr_value = float(latest.get("technical_atr_14")) if latest.get("technical_atr_14") is not None else None
        if atr_multiple and atr_value and atr_value > 0:
            protective_stop = price - atr_value * atr_multiple
    except (TypeError, ValueError):
        pass
    return {
        "buy_zone_low": round(price * (1 - entry_buffer_pct / 100), 2),
        "buy_zone_high": round(price * (1 + entry_buffer_pct / 100), 2),
        "protective_stop": round(protective_stop, 2),
        "sell_zone_low": round(min(sell_low, sell_high), 2),
        "sell_zone_high": round(max(sell_low, sell_high), 2),
        "planning_range_basis": {
            "reference_price": round(price, 2), "atr_percent": round(atr_pct, 2),
            "entry_buffer_percent": round(entry_buffer_pct, 2), "stop_loss_percent": stop_pct,
            "take_profit_percent": target_pct,
            "atr_stop_multiple": assumptions.get("atr_stop_multiple"),
            "break_even_trigger_percent": assumptions.get("break_even_trigger_pct"),
            "chosen_sell_rule": exit_rule_id,
            "sell_zone_basis": sell_basis,
            "description": "Planning zone from the selected OOS sell rule when it has a price level; otherwise the saved take-profit target is used. Actual next-open fills can differ.",
        },
    }
