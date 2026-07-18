#!/usr/bin/env python3
"""Run production lifecycle code against real read-only TMS data without sending orders."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal
from main import _create_paired_lifecycle_sell, _materialize_lifecycle_schedule
from models.logged_in_user import LoggedInUsers
from models.scheduled_order import ScheduledOrder
from schemas.schemas import OrderCreateRequest
from utils.monitor_order import (
    _evaluate_strategy,
    _prepare_lifecycle_buy_monitor,
    _prepare_lifecycle_sell_monitor,
    _record_lifecycle_buy_submission,
    submit_scheduled_order_to_tms,
)
from utils.strategy_builder.strategy_parser import parse_strategy_query
from utils.tms_client_resolver import get_tms_user_for_client


def _require_safe_mode() -> None:
    if os.getenv("ENVIRONMENT", "").strip().lower() != "test":
        raise SystemExit("Refusing dry run: ENVIRONMENT must be test.")
    if os.getenv("LIFECYCLE_DRY_RUN", "").strip() != "1":
        raise SystemExit("Refusing dry run: set LIFECYCLE_DRY_RUN=1 explicitly.")


def _query(symbol: str, index: int, ltp: float) -> str:
    stop, target, maximum = [
        (4, 8, 20),
        (5, 12, 45),
        (6, 15, 60),
        (8, 21, 90),
        (7, 18, 30),
    ][index % 5]
    trigger = ltp * 1.01
    return f"""
STRATEGY_VERSION 1
SIDE LIFECYCLE
POSITION_LIFECYCLE {{
  MIN_HOLDING_DAYS 5
  MAX_HOLDING_DAYS {maximum}
  SELL_ACTIVATION BUY_FILLED_AND_SETTLED
  REENTRY AFTER_POSITION_CLOSED
}}
POSITION_EXIT {{
  SELL ALL_AVAILABLE WHEN profit_percent <= -{stop}
  SELL ALL_AVAILABLE WHEN profit_percent >= {target}
}}
RULE "Runtime dry-run {index + 1}" FOR SYMBOL "{symbol}" {{
  WHEN ltp <= {trigger:.4f}
  ORDER QUANTITY 10
  TRIGGER LEVEL
  EXECUTE ONCE PER SYMBOL
}}
"""


@dataclass
class RecordingBroker:
    """Delegates no writes: broker order submissions are recorded in memory only."""

    symbol: str
    price: float
    holding_qty: int = 0
    traded_qty: int = 0
    orders: list[dict] = field(default_factory=list)

    async def order(self, price, qty, *, security, order_type):
        self.orders.append({
            "price": float(price), "qty": int(qty), "side": str(order_type),
            "security_id": security.get("id"),
        })
        return {"status": 200, "message": "DRY_RUN_RECORDED"}

    async def get_latest_order_timing_for_symbol(self, *_args, **_kwargs):
        return {"exchange_order_id": "DRY-RUN-ORDER", "order_status": "OPEN"}

    async def get_normalized_daily_order_book(self):
        return [{
            "symbol": self.symbol,
            "buyOrSell": 1,
            "exchangeOrderId": "DRY-RUN-ORDER",
            "orderQuantity": 10,
            "totalTradedQuantity": self.traded_qty,
            "displayActiveStatus": "ALL_TRADED" if self.traded_qty >= 10 else "PARTIALLY_TRADED",
        }]

    async def get_user_stock_details(self):
        if self.holding_qty <= 0:
            return []
        return [{
            "scrip": self.symbol,
            "symbolName": self.symbol,
            "currentBalance": self.holding_qty,
        }]


async def _run_case(db, *, real_tms, client_id: str, symbol: str, variant: int) -> dict:
    security = await real_tms.get_security_id(symbol)
    if not security:
        return {"symbol": symbol, "variant": variant + 1, "status": "skipped", "reason": "security not found"}
    quote = await real_tms.get_stock_details_async(security["id"], max_retries=1)
    ltp = float((quote or {}).get("ltp") or 0)
    if ltp <= 0:
        return {"symbol": symbol, "variant": variant + 1, "status": "skipped", "reason": "quote unavailable"}

    query = _query(symbol, variant, ltp)
    plan = parse_strategy_query(query)
    request = OrderCreateRequest(
        client_id=client_id,
        script_name=symbol,
        security_details=security,
        price=0,
        qty=10,
        order_type="buy",
        status="Monitoring",
        strategy_type="Custom Query Buy",
        strategy_config={
            "query_text": query,
            "compiled_plan": plan.model_dump(),
            "execution_mode": "live",
        },
    )
    _materialize_lifecycle_schedule(request)
    buy_order = ScheduledOrder(request)
    db.add(buy_order)
    db.flush()
    with patch("main._find_duplicate_scheduled_order", return_value=None), patch(
        "main._persist_order_field_references", new=AsyncMock(),
    ):
        sell_order = await _create_paired_lifecycle_sell(
            db, buy_order, request, owner_user_id=1,
        )
    assert sell_order is not None
    db.flush()

    live_quote = dict(quote or {})
    live_quote.setdefault("high", max(ltp, float(live_quote.get("high") or 0)))
    live_quote.setdefault("topBuy", [{"price": ltp, "quantity": 10}])
    live_quote.setdefault("topSell", [{"price": ltp, "quantity": 10}])
    decision, reason = _evaluate_strategy(buy_order, ltp, live_quote, scan_count=1)
    if not decision or decision.get("action") != "execute":
        raise AssertionError(f"BUY did not execute for {symbol}: {reason or decision}")

    broker = RecordingBroker(symbol=symbol, price=ltp)
    submitted = await submit_scheduled_order_to_tms(
        buy_order,
        decision,
        high_price=float(live_quote.get("high") or ltp),
        fallback_qty=10,
        security_details=security,
        order_type="buy",
        tms_user=broker,
        execution_gate={"can_execute": True, "message": "isolated dry-run gate"},
    )
    assert submitted.submitted, submitted.blocked_reason
    await _record_lifecycle_buy_submission(
        buy_order, broker, submitted_price=ltp, submitted_quantity=10,
    )

    broker.traded_qty = 5
    ready, partial_message = await _prepare_lifecycle_buy_monitor(buy_order, broker)
    assert ready is False and "5/10" in partial_message
    broker.traded_qty = 10
    ready, fill_message = await _prepare_lifecycle_buy_monitor(buy_order, broker)
    assert ready is False and "fill confirmed" in fill_message

    with patch("utils.monitor_order._linear_holding_sessions", return_value=4):
        ready, day4_message = await _prepare_lifecycle_sell_monitor(sell_order, broker)
    assert ready is False and "4/5" in day4_message
    with patch("utils.monitor_order._linear_holding_sessions", return_value=5):
        ready, settlement_message = await _prepare_lifecycle_sell_monitor(sell_order, broker)
    assert ready is False and "sellable holding" in settlement_message
    broker.holding_qty = 10
    with patch("utils.monitor_order._linear_holding_sessions", return_value=5):
        ready, activation_message = await _prepare_lifecycle_sell_monitor(sell_order, broker)
    assert ready, activation_message

    target_pct = float([8, 12, 15, 21, 18][variant % 5])
    sell_ltp = ltp * (1 + (target_pct + 0.5) / 100)
    sell_quote = {
        **live_quote,
        "ltp": sell_ltp,
        "high": sell_ltp,
        "topBuy": [{"price": sell_ltp, "quantity": 10}],
        "topSell": [{"price": sell_ltp + 0.1, "quantity": 10}],
    }
    with patch("utils.monitor_order._linear_holding_sessions", return_value=5):
        sell_decision, reason = _evaluate_strategy(sell_order, sell_ltp, sell_quote, scan_count=2)
    if not sell_decision or sell_decision.get("action") != "execute":
        raise AssertionError(f"SELL did not execute for {symbol}: {reason or sell_decision}")
    with patch("utils.monitor_order._linear_holding_sessions", return_value=5):
        sold = await submit_scheduled_order_to_tms(
            sell_order,
            sell_decision,
            high_price=sell_ltp,
            fallback_qty=10,
            security_details=security,
            order_type="sell",
            tms_user=broker,
            execution_gate={"can_execute": True, "message": "isolated dry-run gate"},
        )
    assert sold.submitted, sold.blocked_reason
    assert [item["side"] for item in broker.orders] == ["buy", "sell"]
    return {
        "symbol": symbol,
        "variant": variant + 1,
        "status": "passed",
        "quote_ltp": ltp,
        "buy_recorded": broker.orders[0],
        "sell_recorded": broker.orders[1],
        "partial_fill_gate": partial_message,
        "day4_gate": day4_message,
        "settlement_gate": settlement_message,
    }


async def main() -> int:
    _require_safe_mode()
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-id", default="")
    parser.add_argument("--symbols", default="MLBBL,NABIL,CZBIL")
    parser.add_argument("--variants", type=int, default=5)
    args = parser.parse_args()
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    db = SessionLocal()
    try:
        client_id = args.client_id.strip()
        if not client_id:
            row = db.query(LoggedInUsers).filter(LoggedInUsers.status == "logged_in").order_by(LoggedInUsers.client_id).first()
            if not row:
                raise SystemExit("No logged-in TMS account is available for read-only quote verification.")
            client_id = row.client_id
        real_tms = await get_tms_user_for_client(client_id, db, allow_full_login=False)
        results = []
        for symbol in symbols:
            for variant in range(max(1, min(args.variants, 10))):
                nested = db.begin_nested()
                try:
                    results.append(await _run_case(
                        db, real_tms=real_tms, client_id=client_id,
                        symbol=symbol, variant=variant,
                    ))
                finally:
                    nested.rollback()
                    db.expire_all()
        passed = sum(item["status"] == "passed" for item in results)
        skipped = len(results) - passed
        print({"safe_dry_run": True, "passed": passed, "skipped": skipped, "results": results})
        return 0 if passed and not skipped else 2
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
