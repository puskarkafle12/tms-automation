"""Validated server-side querying for normalized backtest results."""

from __future__ import annotations

from math import ceil
from typing import Any, Dict, Iterable, List, Tuple

from sqlalchemy import text


RESULT_FIELDS = {
    "result_id": "r.result_id", "symbol": "r.symbol", "preset_id": "r.preset_id",
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
    "ltp": "s.ltp", "latest_volume": "s.latest_volume", "median_volume_20": "s.median_volume_20",
    "average_turnover_20": "s.average_turnover_20", "warning_codes": "r.warning_codes",
    "technical_signal": "r.technical_snapshot->>'technical_signal'",
    "technical_signal_score": "NULLIF(r.technical_snapshot->>'technical_signal_score','')::double precision",
    "technical_buy_score": "NULLIF(r.technical_snapshot->>'technical_buy_score','')::double precision",
    "technical_sell_score": "NULLIF(r.technical_snapshot->>'technical_sell_score','')::double precision",
    "current_signal_active": "r.current_signal_active", "current_signal_status": "r.current_signal_status",
    "current_signal_date": "r.current_signal_date", "current_technical_score": "r.current_technical_score",
    "reliability_score": "r.reliability_score", "strong_buy_qualified": "r.strong_buy_qualified",
    "current_evidence": "r.current_evidence",
}

NUMERIC_FIELDS = {
    key for key in RESULT_FIELDS if key not in {
        "symbol", "preset_id", "preset_name", "preset_family", "category", "sample_quality",
        "recommendation_status", "security_type", "sector", "technical_signal", "current_signal_status",
        "current_signal_date", "current_signal_active", "strong_buy_qualified", "warning_codes", "current_evidence",
    }
}
TEXT_FIELDS = set(RESULT_FIELDS) - NUMERIC_FIELDS - {"warning_codes"}
OPERATORS = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "contains": "ILIKE", "is_null": "IS NULL", "not_null": "IS NOT NULL"}


class ResultQueryError(ValueError):
    pass


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


def query_results(session, run_id: str, body: Dict[str, Any], *, owner_id: str = "local") -> Dict[str, Any]:
    page = max(1, int(body.get("page") or 1))
    page_size = min(100, max(1, int(body.get("page_size") or 100)))
    sort_by = str(body.get("sort_by") or "robust_score")
    if sort_by not in RESULT_FIELDS or sort_by == "warning_codes":
        raise ResultQueryError(f"Unsupported sort field: {sort_by}.")
    direction = "ASC" if str(body.get("sort_direction") or "desc").lower() == "asc" else "DESC"
    where, params = compile_filters(body.get("filters"), include_non_equities=bool(body.get("include_non_equities")))
    params.update({"run_id": run_id, "owner_id": owner_id, "limit": page_size, "offset": (page - 1) * page_size})
    ownership = "EXISTS (SELECT 1 FROM backtest_runs br WHERE br.run_id=r.run_id AND br.owner_id=:owner_id AND br.deleted_at IS NULL)"
    base = "FROM backtest_results r JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol"
    total = int(session.execute(text(f"SELECT COUNT(*) {base} WHERE r.run_id=:run_id AND {ownership} AND {where}"), params).scalar() or 0)
    select = ",".join(f"{column} AS {key}" for key, column in RESULT_FIELDS.items())
    rows = session.execute(text(
        f"SELECT {select} {base} WHERE r.run_id=:run_id AND {ownership} AND {where} "
        f"ORDER BY {RESULT_FIELDS[sort_by]} {direction} NULLS LAST,r.total_trades DESC,r.result_id ASC LIMIT :limit OFFSET :offset"
    ), params).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        item["warning_codes"] = list(item.get("warning_codes") or [])
        items.append(item)
    return {"items": items, "page": page, "page_size": page_size, "total": total, "pages": ceil(total / page_size) if total else 0, "sort_by": sort_by, "sort_direction": direction.lower()}


def result_detail(session, result_id: int, *, owner_id: str = "local") -> Dict[str, Any]:
    select = ",".join(f"{column} AS {key}" for key, column in RESULT_FIELDS.items())
    row = session.execute(text(
        f"SELECT {select},r.assumptions,r.technical_snapshot,r.run_id FROM backtest_results r "
        "JOIN backtest_runs br ON br.run_id=r.run_id JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol "
        "WHERE r.result_id=:result_id AND br.owner_id=:owner_id AND br.deleted_at IS NULL"
    ), {"result_id": result_id, "owner_id": owner_id}).mappings().first()
    if not row:
        raise ResultQueryError("Backtest result was not found.")
    output = dict(row)
    output["warning_codes"] = list(output.get("warning_codes") or [])
    return output


def result_trades(session, result_id: int, *, owner_id: str = "local") -> List[Dict[str, Any]]:
    rows = session.execute(text(
        "SELECT t.* FROM backtest_trades t JOIN backtest_results r ON r.result_id=t.result_id "
        "JOIN backtest_runs br ON br.run_id=r.run_id WHERE t.result_id=:result_id AND br.owner_id=:owner_id "
        "ORDER BY t.sequence_no"
    ), {"result_id": result_id, "owner_id": owner_id}).mappings().all()
    return [{**dict(row), "signal_date": row["signal_date"].isoformat() if row["signal_date"] else None,
             "entry_date": row["entry_date"].isoformat(), "exit_date": row["exit_date"].isoformat()} for row in rows]


def query_strong_buys(session, run_id: str, body: Dict[str, Any], *, owner_id: str = "local") -> Dict[str, Any]:
    page = max(1, int(body.get("page") or 1))
    page_size = min(100, max(1, int(body.get("page_size") or 25)))
    sort_fields = {
        "recommendation_score": "recommendation_score",
        "reliability_score": "reliability_score", "win_rate_pct": "win_rate_pct",
        "net_return_pct": "net_return_pct", "total_trades": "total_trades",
        "profit_factor": "profit_factor", "sharpe_ratio": "sharpe_ratio",
        "max_drawdown_pct": "max_drawdown_pct", "current_signal_date": "current_signal_date",
    }
    sort_by = str(body.get("sort_by") or "recommendation_score")
    if sort_by not in sort_fields:
        raise ResultQueryError("Unsupported Strong Buy sort field.")
    direction = "ASC" if str(body.get("sort_direction") or "desc").lower() == "asc" else "DESC"
    params = {
        "run_id": run_id, "owner_id": owner_id, "min_trades": int(body.get("minimum_trades", 5)),
        "min_win": float(body.get("minimum_win_rate", 0)), "min_confidence": float(body.get("minimum_confidence", 0)),
        "min_sharpe": float(body.get("minimum_sharpe", -999)), "min_pf": float(body.get("minimum_profit_factor", 0)),
        "max_dd": float(body.get("maximum_drawdown", 100)), "min_return": float(body.get("minimum_return", 0)),
        "min_volume": float(body.get("minimum_volume") or 0), "category": str(body.get("category") or ""),
        "signal": str(body.get("current_signal") or "all"), "latest_date": body.get("latest_signal_date"),
        "limit": page_size, "offset": (page - 1) * page_size,
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
    requirements = f"""{signal_requirements[signal_mode]}
        AND r.total_trades>=:min_trades AND r.win_rate_pct>=:min_win AND r.confidence_score>=:min_confidence
        AND r.net_return_pct>=:min_return AND (r.profit_factor IS NULL OR r.profit_factor>=:min_pf)
        AND COALESCE(r.sharpe_ratio,-999)>=:min_sharpe AND r.max_drawdown_pct<=:max_dd
        AND COALESCE(s.latest_volume,0)>=:min_volume
        AND (:category='' OR r.category=:category)
        AND (:latest_date IS NULL OR r.current_signal_date>=CAST(:latest_date AS DATE))"""
    recommendation_score = """ROUND((
        COALESCE(r.win_rate_pct,0)*0.45
        + GREATEST(0,LEAST(100,COALESCE(r.net_return_pct,0)))*0.30
        + GREATEST(0,LEAST(100,COALESCE(r.total_trades,0)*2))*0.15
        + GREATEST(0,LEAST(100,COALESCE(r.reliability_score,0)))*0.10
    )::numeric,2)::double precision"""
    columns = """r.result_id,r.symbol,r.preset_id,r.preset_name,r.category,r.current_signal_status,
        r.current_signal_date,r.reliability_score,r.current_technical_score,r.win_rate_pct,r.wins,r.losses,
        r.total_trades,r.average_holding_days,r.confidence_score,r.net_return_pct,r.profit_factor,r.max_drawdown_pct,r.sharpe_ratio,
        r.current_evidence,r.assumptions,s.security_type,s.sector,s.ltp,s.latest_volume,s.median_volume_20,
        NULLIF(r.assumptions->'summary'->>'net_profit','')::double precision AS net_profit,
        CASE WHEN COALESCE(r.assumptions->>'charge_model','') LIKE 'nepse_equity%' THEN FALSE ELSE TRUE END AS legacy_cost_model,
        COALESCE(c.combined_data->>'company_name',c.combined_data->>'name',c.combined_data->>'companyName',r.symbol) AS company_name"""
    base = f"""FROM backtest_results r JOIN backtest_runs br ON br.run_id=r.run_id
        JOIN backtest_run_symbols s ON s.run_id=r.run_id AND s.symbol=r.symbol
        LEFT JOIN market_screener_cache c ON c.symbol=r.symbol
        WHERE r.run_id=:run_id AND br.owner_id=:owner_id AND br.deleted_at IS NULL AND {universe} AND {requirements}"""
    cte = f"""WITH candidates AS (SELECT {columns},{recommendation_score} AS recommendation_score,
        ROW_NUMBER() OVER(PARTITION BY r.symbol ORDER BY {recommendation_score} DESC,
            NULLIF(r.assumptions->'summary'->>'net_profit','')::double precision DESC NULLS LAST,
            r.win_rate_pct DESC,r.total_trades DESC,r.result_id) row_no {base})"""
    total = int(session.execute(text(f"{cte} SELECT COUNT(*) FROM candidates WHERE row_no=1"), params).scalar() or 0)
    rows = session.execute(text(
        f"{cte} SELECT * FROM candidates WHERE row_no=1 ORDER BY {sort_fields[sort_by]} {direction} NULLS LAST,symbol LIMIT :limit OFFSET :offset"
    ), params).mappings().all()
    items = []
    for rank, row in enumerate(rows, start=(page - 1) * page_size + 1):
        item = dict(row)
        item.update({"rank": rank, "loss_rate_pct": round(100 - float(item.get("win_rate_pct") or 0), 2),
                     "signal_date": item.pop("current_signal_date")})
        item.pop("row_no", None)
        items.append(item)
    return {"items": items, "page": page, "page_size": page_size, "total": total,
            "pages": ceil(total / page_size) if total else 0,
            "disclaimer": "Backtested historical performance does not guarantee future results."}
