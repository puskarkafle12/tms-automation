"""Fast persisted recommendation projection derived from normalized backtests."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlalchemy import text

from utils.backtesting.v2_query import query_strong_buys


SIGNAL_PRIORITY = {"strong_buy": 3, "buy": 2, "near_trigger": 1}
RECOMMENDATION_SCORE_VERSION = "risk-adjusted-v2"
SORT_FIELDS = {
    "recommendation_score": "recommendation_score", "win_rate_pct": "win_rate_pct",
    "total_trades": "total_trades", "net_return_pct": "net_return_pct",
    "average_volume_20": "average_volume_20", "symbol": "symbol", "signal_status": "signal_status",
    "current_ltp": "live_ltp", "ltp": "live_ltp", "preset_name": "preset_name",
    "buy_range": "NULLIF(payload->>'buy_zone_low','')::double precision",
    "sell_range": "NULLIF(payload->>'sell_zone_low','')::double precision",
    "current_ltp_estimated_profit_pct": "((NULLIF(payload->>'sell_zone_low','')::double precision / NULLIF(live_ltp,0))-1)*100",
    "current_ltp_estimated_loss_pct": "((live_ltp-NULLIF(payload->>'protective_stop','')::double precision)/NULLIF(live_ltp,0))*100",
    "protective_stop": "NULLIF(payload->>'protective_stop','')::double precision",
    "estimated_profit_pct": "((NULLIF(payload->>'sell_zone_low','')::double precision / NULLIF(payload->>'buy_zone_high','')::double precision)-1)*100",
    "estimated_loss_pct": "((NULLIF(payload->>'buy_zone_high','')::double precision-NULLIF(payload->>'protective_stop','')::double precision)/NULLIF(payload->>'buy_zone_high','')::double precision)*100",
    "average_holding_days": "NULLIF(payload->>'average_holding_days','')::double precision",
    "signal_date": "signal_date", "holding_quantity": "NULLIF(payload->>'holding_quantity','')::double precision",
}


def _trade_range_estimates(item: Dict[str, Any]) -> Dict[str, Any]:
    """Conservative planned upside/downside using the displayed strategy ranges."""
    try:
        entry_high = float(item.get("buy_zone_high") or 0)
        sell_low = float(item.get("sell_zone_low") or 0)
        stop = float(item.get("protective_stop") or 0)
        current_ltp = float(item.get("current_ltp") or item.get("ltp") or 0)
        buy_low = float(item.get("buy_zone_low") or 0)
    except (TypeError, ValueError):
        entry_high = sell_low = stop = current_ltp = buy_low = 0
    profit_pct = ((sell_low / entry_high) - 1) * 100 if entry_high > 0 and sell_low > 0 else None
    loss_pct = ((entry_high - stop) / entry_high) * 100 if entry_high > 0 and stop > 0 else None
    current_profit_pct = ((sell_low / current_ltp) - 1) * 100 if current_ltp > 0 and sell_low > 0 else None
    current_loss_pct = ((current_ltp - stop) / current_ltp) * 100 if current_ltp > 0 and stop > 0 else None
    if current_ltp <= 0 or buy_low <= 0 or entry_high <= 0:
        ltp_position = "unavailable"
    elif current_ltp < buy_low:
        ltp_position = "below_buy_range"
    elif current_ltp <= entry_high:
        ltp_position = "inside_buy_range"
    else:
        ltp_position = "above_buy_range"
    return {
        "estimated_profit_pct": round(profit_pct, 2) if profit_pct is not None else None,
        "estimated_loss_pct": round(max(0, loss_pct), 2) if loss_pct is not None else None,
        "current_ltp_estimated_profit_pct": round(current_profit_pct, 2) if current_profit_pct is not None else None,
        "current_ltp_estimated_loss_pct": round(max(0, current_loss_pct), 2) if current_loss_pct is not None else None,
        "current_ltp_position": ltp_position,
        "estimate_basis": "Conservative: buy at the top of the entry range, sell at the bottom of the target range, or exit at the protective stop.",
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
                    ELSE session_date END)) <> 6
    """)).scalar()
    stored_session = session.execute(text(
        "SELECT MAX(signal_date) FROM market_backtest_recommendations WHERE owner_id=:owner_id"
    ), {"owner_id": owner_id}).scalar()
    stored_score_version = session.execute(text(
        "SELECT payload->>'recommendation_score_version' FROM market_backtest_recommendations "
        "WHERE owner_id=:owner_id ORDER BY refreshed_at DESC LIMIT 1"
    ), {"owner_id": owner_id}).scalar()
    if (stored_session is None
            or stored_score_version != RECOMMENDATION_SCORE_VERSION
            or (fresh_session is not None and stored_session < fresh_session)):
        materialize_recommendations(session, owner_id=owner_id)
        session.commit()
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
    rows = session.execute(text(f"""WITH recommendations AS (
        SELECT market_backtest_recommendations.*,
          (SELECT NULLIF(regexp_replace(COALESCE(c.combined_data->>'ltp',c.combined_data->>'ml_ltp',c.combined_data->>'close',''),
                      '[^0-9.-]','','g'),'')::double precision
           FROM market_screener_cache c WHERE c.symbol=market_backtest_recommendations.symbol) AS live_ltp
        FROM market_backtest_recommendations WHERE {where}
      )
      SELECT payload,refreshed_at,live_ltp AS current_ltp
      FROM recommendations
      ORDER BY {sort_sql} {direction} NULLS LAST,symbol LIMIT :limit OFFSET :offset"""), params).mappings().all()
    items = []
    for row in rows:
        item = dict(row["payload"] or {})
        if row["current_ltp"] is not None:
            item["current_ltp"] = float(row["current_ltp"])
            item["ltp"] = float(row["current_ltp"])
        item.update(_trade_range_estimates(item))
        item["refreshed_at"] = row["refreshed_at"].isoformat()
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": (total + page_size - 1) // page_size, "persisted": True,
            "trading_session": fresh_session.isoformat() if hasattr(fresh_session, "isoformat") else fresh_session}


async def query_sell_recommendations(session, body: Dict[str, Any], *, owner_id: str) -> Dict[str, Any]:
    """Return fresh, tested exit signals only for the owner's live combined holdings."""
    from models.user import User
    from utils.backtesting.current_opportunities import evaluate_latest_completed_query
    from utils.strategy_builder.holdings_preflight import build_holdings_map
    from utils.tms_client_resolver import get_tms_user_for_client

    accounts = session.query(User).filter(User.owner_user_id == int(owner_id)).order_by(User.client_id).all()
    combined: Dict[str, int] = {}
    holders: Dict[str, List[str]] = {}
    account_errors: List[str] = []
    for account in accounts:
        tms_user = None
        try:
            tms_user = await get_tms_user_for_client(account.client_id, session)
            holdings = await build_holdings_map(tms_user)
            for symbol, quantity in holdings.items():
                if quantity <= 0:
                    continue
                combined[symbol] = combined.get(symbol, 0) + int(quantity)
                holders.setdefault(symbol, []).append(account.client_id)
        except Exception as exc:
            account_errors.append(f"{account.client_id}: {exc}")
        finally:
            if tms_user is not None:
                await tms_user.close()
    symbols = sorted(combined)
    page = max(1, int(body.get("page") or 1)); page_size = min(100, max(1, int(body.get("page_size") or 25)))
    if not symbols:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "pages": 0,
                "persisted": True, "side": "sell", "trading_session": None,
                "message": "No sellable combined DP holdings are available.", "account_errors": account_errors[:5]}

    candidates = session.execute(text("""
        WITH candidates AS (
          SELECT r.*, ROW_NUMBER() OVER (
            PARTITION BY r.symbol ORDER BY r.robust_score DESC NULLS LAST,r.total_trades DESC,r.result_id DESC
          ) AS candidate_rank
          FROM backtest_results r JOIN backtest_runs br ON br.run_id=r.run_id
          WHERE br.owner_id=:owner_id AND br.deleted_at IS NULL
            AND r.symbol=ANY(CAST(:symbols AS TEXT[]))
            AND COALESCE(r.assumptions->>'sell_strategy_query','')<>''
        )
        SELECT result_id,run_id,symbol,preset_id,preset_name,category,robust_score,win_rate_pct,total_trades,
               net_return_pct,max_drawdown_pct,average_holding_days,profit_factor,assumptions
        FROM candidates WHERE candidate_rank<=20 ORDER BY symbol,candidate_rank
    """), {"owner_id": owner_id, "symbols": symbols}).mappings().all()
    history_rows = session.execute(text("""
        SELECT d.symbol,d.session_date,d.open_price AS open,d.high_price AS high,
               d.low_price AS low,d.close_price AS close,d.volume,i.indicators
        FROM market_ohlcv_daily d
        JOIN LATERAL (
          SELECT indicators FROM market_indicator_daily x
          WHERE x.symbol=d.symbol AND x.session_date=d.session_date
          ORDER BY x.calculated_at DESC LIMIT 1
        ) i ON TRUE
        WHERE d.adjusted=TRUE AND d.symbol=ANY(CAST(:symbols AS TEXT[])) AND d.session_date<=CURRENT_DATE
          AND d.session_date >= CURRENT_DATE - INTERVAL '3 years'
        ORDER BY d.symbol,d.session_date
    """), {"symbols": symbols}).mappings().all()
    histories: Dict[str, List[Dict[str, Any]]] = {}
    for source in history_rows:
        item = dict(source); indicators = dict(item.pop("indicators") or {})
        item.update(indicators); item.update({"ltp": float(item.get("close") or 0), "date": item["session_date"]})
        histories.setdefault(str(item["symbol"]), []).append(item)

    matches: List[Dict[str, Any]] = []
    matched_symbols = set()
    search = str(body.get("search") or "").strip().lower()
    for source in candidates:
        item = dict(source); symbol = str(item["symbol"])
        if symbol in matched_symbols or (search and search not in symbol.lower() and search not in str(item["preset_name"]).lower()):
            continue
        if float(item.get("win_rate_pct") or 0) < float(body.get("minimum_win_rate") or 0) or int(item.get("total_trades") or 0) < int(body.get("minimum_trades") or 0) or float(item.get("robust_score") or 0) < float(body.get("minimum_score") or 0):
            continue
        query = str((item.get("assumptions") or {}).get("sell_strategy_query") or "").strip()
        rows = histories.get(symbol, [])[-260:]
        if not query or len(rows) < 2:
            continue
        try:
            evidence = evaluate_latest_completed_query(query, symbol, rows, strategy_name=f"{item['preset_name']} sell")
        except Exception:
            continue
        if not evidence.get("active"):
            continue
        latest = rows[-1]
        item.update({
            "current_signal_status": "sell", "signal_date": latest["session_date"],
            "recommendation_score": item.get("robust_score"), "holding_quantity": combined[symbol],
            "holding_accounts": holders.get(symbol, []), "ltp": latest.get("ltp"),
            "sell_strategy_query": query, "current_evidence": evidence,
        })
        matches.append(item); matched_symbols.add(symbol)
    requested_sort = str(body.get("sort_by") or "recommendation_score")
    if requested_sort not in SORT_FIELDS:
        raise ValueError("Unsupported recommendation sort field.")
    aliases = {"signal_status": "current_signal_status", "current_ltp": "ltp", "buy_range": "buy_zone_low",
               "sell_range": "sell_zone_low", "current_ltp_estimated_profit_pct": "estimated_profit_pct",
               "current_ltp_estimated_loss_pct": "estimated_loss_pct"}
    sort_key = aliases.get(requested_sort, requested_sort); reverse = str(body.get("sort_direction") or "desc") != "asc"
    matches.sort(key=lambda row: (row.get(sort_key) is not None, row.get(sort_key) or 0), reverse=reverse)
    total = len(matches); start = (page - 1) * page_size; selected = matches[start:start + page_size]
    latest_session = max((row["signal_date"] for row in matches), default=None)
    return {"items": selected, "total": total, "page": page, "page_size": page_size,
            "pages": (total + page_size - 1) // page_size, "persisted": True, "side": "sell",
            "trading_session": latest_session.isoformat() if hasattr(latest_session, "isoformat") else latest_session,
            "account_errors": account_errors[:5],
            "message": "SELL signals are evaluated from independently tested exit rules and restricted to combined DP holdings."}
