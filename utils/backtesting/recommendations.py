"""Fast persisted recommendation projection derived from normalized backtests."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlalchemy import text

from utils.backtesting.v2_query import query_strong_buys


SIGNAL_PRIORITY = {"strong_buy": 3, "buy": 2, "near_trigger": 1}
SORT_FIELDS = {
    "recommendation_score": "recommendation_score", "win_rate_pct": "win_rate_pct",
    "total_trades": "total_trades", "net_return_pct": "net_return_pct",
    "average_volume_20": "average_volume_20", "symbol": "symbol", "signal_status": "signal_status",
}


def _all_candidates(session, mode: str, owner_id: str) -> List[Dict[str, Any]]:
    page, items = 1, []
    while True:
        payload = query_strong_buys(session, "all", {
            "page": page, "page_size": 100, "minimum_trades": 5, "minimum_return": 0,
            "current_signal": mode, "include_non_equities": False,
        }, owner_id=owner_id)
        items.extend(payload["items"])
        if page >= payload["pages"]:
            return items
        page += 1


def materialize_recommendations(session, *, owner_id: str = "local") -> Dict[str, Any]:
    """Upsert one preferred actionable or near-trigger strategy per ordinary share."""
    preferred: Dict[str, Dict[str, Any]] = {}
    for mode in ("buy", "near_trigger"):
        for item in _all_candidates(session, mode, owner_id):
            symbol = str(item["symbol"])
            existing = preferred.get(symbol)
            candidate_key = (SIGNAL_PRIORITY.get(str(item.get("current_signal_status")), 0), float(item.get("recommendation_score") or 0))
            existing_key = (SIGNAL_PRIORITY.get(str(existing.get("current_signal_status")), 0), float(existing.get("recommendation_score") or 0)) if existing else (-1, -1)
            if candidate_key > existing_key:
                preferred[symbol] = item
    statement = text("""
        INSERT INTO market_backtest_recommendations (
            owner_id,symbol,result_id,run_id,preset_id,preset_name,signal_status,signal_date,
            recommendation_score,win_rate_pct,total_trades,net_return_pct,average_volume_20,payload,refreshed_at
        ) VALUES (
            :owner_id,:symbol,:result_id,:run_id,:preset_id,:preset_name,:signal_status,:signal_date,
            :score,:win_rate,:trades,:net_return,:average_volume,CAST(:payload AS JSONB),NOW()
        ) ON CONFLICT (owner_id,symbol) DO UPDATE SET
            result_id=EXCLUDED.result_id,run_id=EXCLUDED.run_id,preset_id=EXCLUDED.preset_id,
            preset_name=EXCLUDED.preset_name,signal_status=EXCLUDED.signal_status,
            signal_date=EXCLUDED.signal_date,recommendation_score=EXCLUDED.recommendation_score,
            win_rate_pct=EXCLUDED.win_rate_pct,total_trades=EXCLUDED.total_trades,
            net_return_pct=EXCLUDED.net_return_pct,average_volume_20=EXCLUDED.average_volume_20,
            payload=EXCLUDED.payload,refreshed_at=NOW()
    """)
    rows = [{
        "owner_id": owner_id, "symbol": item["symbol"], "result_id": item["result_id"],
        "run_id": item["run_id"], "preset_id": item["preset_id"], "preset_name": item["preset_name"],
        "signal_status": item["current_signal_status"], "signal_date": item["signal_date"],
        "score": item["recommendation_score"], "win_rate": item["win_rate_pct"],
        "trades": item["total_trades"], "net_return": item["net_return_pct"],
        "average_volume": item.get("average_volume_20"), "payload": json.dumps(item, default=str),
    } for item in preferred.values()]
    if rows:
        session.execute(statement, rows)
    return {"materialized": len(rows)}


def query_recommendations(session, body: Dict[str, Any], *, owner_id: str = "local") -> Dict[str, Any]:
    if not session.execute(text(
        "SELECT 1 FROM market_backtest_recommendations WHERE owner_id=:owner_id LIMIT 1"
    ), {"owner_id": owner_id}).scalar():
        materialize_recommendations(session, owner_id=owner_id)
        session.commit()
    page = max(1, int(body.get("page") or 1))
    page_size = min(100, max(1, int(body.get("page_size") or 25)))
    signal = str(body.get("signal") or "actionable")
    signal_sql = {
        "actionable": "signal_status IN ('strong_buy','buy')", "strong_buy": "signal_status='strong_buy'",
        "buy": "signal_status='buy'", "near_trigger": "signal_status='near_trigger'", "all": "TRUE",
    }.get(signal)
    if not signal_sql:
        raise ValueError("Unsupported recommendation signal filter.")
    sort_by = str(body.get("sort_by") or "recommendation_score")
    sort_sql = SORT_FIELDS.get(sort_by)
    if not sort_sql:
        raise ValueError("Unsupported recommendation sort field.")
    direction = "ASC" if str(body.get("sort_direction") or "desc").lower() == "asc" else "DESC"
    fresh_session = body.get("signal_date") or session.execute(text("""
        SELECT MAX(CASE WHEN source_timestamp IS NOT NULL
                       THEN (to_timestamp(source_timestamp) AT TIME ZONE 'UTC')::date
                       ELSE session_date END)
        FROM market_ohlcv_daily
        WHERE adjusted=TRUE
          AND (CASE WHEN source_timestamp IS NOT NULL
                    THEN (to_timestamp(source_timestamp) AT TIME ZONE 'UTC')::date
                    ELSE session_date END)<=CURRENT_DATE
          AND EXTRACT(ISODOW FROM (CASE WHEN source_timestamp IS NOT NULL
                    THEN (to_timestamp(source_timestamp) AT TIME ZONE 'UTC')::date
                    ELSE session_date END)) BETWEEN 1 AND 5
    """)).scalar()
    params = {
        "owner_id": owner_id, "fresh": fresh_session,
        "min_win": float(body.get("minimum_win_rate") or 0), "min_trades": int(body.get("minimum_trades") or 0),
        "min_score": float(body.get("minimum_score") or 0), "search": f"%{str(body.get('search') or '').strip()}%",
        "limit": page_size, "offset": (page - 1) * page_size,
    }
    where = f"""owner_id=:owner_id AND {signal_sql}
        AND (:fresh IS NULL OR signal_date=CAST(:fresh AS DATE)
             OR (signal_date=CAST(:fresh AS DATE)+1 AND EXTRACT(ISODOW FROM signal_date)=6))
        AND win_rate_pct>=:min_win AND total_trades>=:min_trades AND recommendation_score>=:min_score
        AND (:search='%%' OR symbol ILIKE :search OR preset_name ILIKE :search)"""
    total = int(session.execute(text(f"SELECT COUNT(*) FROM market_backtest_recommendations WHERE {where}"), params).scalar() or 0)
    rows = session.execute(text(f"""SELECT payload,refreshed_at FROM market_backtest_recommendations
        WHERE {where} ORDER BY {sort_sql} {direction} NULLS LAST,symbol LIMIT :limit OFFSET :offset"""), params).mappings().all()
    items = []
    for row in rows:
        item = dict(row["payload"] or {})
        item["refreshed_at"] = row["refreshed_at"].isoformat()
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": (total + page_size - 1) // page_size, "persisted": True,
            "trading_session": fresh_session.isoformat() if hasattr(fresh_session, "isoformat") else fresh_session}
