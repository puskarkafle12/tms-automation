"""Opt-in live broker smoke test for the monitored custom-query execution path.

This test can place a real order. It is skipped unless all required LIVE_* env vars
are set, including an explicit confirmation token.
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

from database import SessionLocal
from utils.market_status import is_market_hours_open, parse_session_check_response
from utils.monitor_order import _evaluate_strategy, submit_scheduled_order_to_tms
from utils.strategy_builder.strategy_parser import parse_strategy_query
from utils.tms_client_resolver import get_tms_user_for_client


LIVE_CONFIRMATION = "I_UNDERSTAND_THIS_PLACES_A_REAL_ORDER"


def _env(name: str) -> str:
    return str(os.getenv(name) or "").strip()


def _required_env(name: str) -> str:
    value = _env(name)
    if not value:
        raise unittest.SkipTest(f"{name} is required for live broker execution test.")
    return value


def _live_depth_query(*, symbol: str, side: str, qty: int) -> str:
    side_upper = side.upper()
    if side_upper == "BUY":
        return f"""
STRATEGY_VERSION 1
SIDE BUY
RULE "Live Depth Buy" FOR SYMBOL "{symbol}" {{
    ELIGIBILITY market_depth_available = TRUE
    SIGNAL top_sell_quantity >= {qty} AND best_ask > 0
    ORDER PARTIAL_TOP_SELL {qty} PRICE TOP_SELL
    EXECUTE ONCE
}}
"""
    return f"""
STRATEGY_VERSION 1
SIDE SELL
RULE "Live Depth Sell" FOR SYMBOL "{symbol}" {{
    ELIGIBILITY market_depth_available = TRUE
    SIGNAL top_buy_quantity >= {qty} AND best_bid > 0
    ORDER PARTIAL_TOP_BUY {qty} PRICE TOP_BUY
    EXECUTE ONCE
}}
"""


def _make_live_order(*, client_id: str, symbol: str, side: str, qty: int, security: dict, query: str):
    compiled = parse_strategy_query(query).model_dump()
    order_type = side.lower()
    return SimpleNamespace(
        order_id=int(_env("LIVE_BROKER_TEST_ORDER_ID") or 999001),
        client_id=client_id,
        script_name=symbol,
        symbol=symbol,
        strategy_type=f"Custom Query {side.title()}",
        order_type=order_type,
        side=order_type,
        qty=qty,
        remaining_quantity=qty,
        price=0,
        status="Monitoring",
        security_details=security,
        strategy_config={
            "compiled_plan": compiled,
            "query_text": query.strip(),
            "execution_mode": "live",
            "target_state": {},
        },
        scan_price_history=[],
        scan_volume_history=[],
        stop_loss_price=None,
        stop_limit_price=None,
        book_profit_price=None,
        profit_target_price=None,
        trailing_drop_percent=3.0,
        stable_band_percent=0.2,
        minimum_wait_minutes=5,
        activation_price=None,
        protected_price=None,
        average_buy_price=None,
        partial_legs=[],
        executed_legs=[],
        target_reached=False,
        target_reached_at=None,
        highest_tracked_price=None,
        expiry_time=None,
        expiry_action=None,
        max_allowed_slippage_percent=1.0,
        emergency_execution=False,
        below_stop_loss_check_count=0,
        last_checked_ltp=None,
    )


@unittest.skipUnless(_env("LIVE_BROKER_EXECUTION") == "1", "set LIVE_BROKER_EXECUTION=1 to run")
class LiveBrokerExecutionTest(unittest.IsolatedAsyncioTestCase):
    async def test_live_monitor_depth_query_places_real_broker_order(self):
        if _env("LIVE_BROKER_CONFIRMATION") != LIVE_CONFIRMATION:
            raise unittest.SkipTest(
                f"Set LIVE_BROKER_CONFIRMATION={LIVE_CONFIRMATION} to allow real order placement."
            )

        client_id = _required_env("LIVE_BROKER_CLIENT_ID")
        symbol = _required_env("LIVE_BROKER_SYMBOL").upper()
        side = (_required_env("LIVE_BROKER_SIDE") or "").upper()
        if side not in {"BUY", "SELL"}:
            raise unittest.SkipTest("LIVE_BROKER_SIDE must be BUY or SELL.")
        qty = int(_required_env("LIVE_BROKER_QTY"))
        if qty <= 0:
            raise unittest.SkipTest("LIVE_BROKER_QTY must be positive.")

        if not is_market_hours_open():
            raise unittest.SkipTest("Market hours are closed; live broker execution test skipped.")

        db = SessionLocal()
        try:
            tms_user = await get_tms_user_for_client(client_id, db)
            session_payload = await tms_user.check_exchange_session()
            parsed_session = parse_session_check_response(session_payload)
            if not parsed_session["session_active"]:
                raise unittest.SkipTest(f"TMS exchange session inactive: {parsed_session['session_message']}")

            security = await tms_user.get_security_id(symbol)
            if not security:
                self.fail(f"{symbol} was not found in TMS security lookup.")
            quote = await tms_user.get_stock_details_async(security["id"], max_retries=1)
            if not quote or quote.get("ltp") in (None, 0):
                self.fail(f"Live quote unavailable for {symbol}.")
            if not (quote.get("topBuy") or quote.get("topSell")):
                raise unittest.SkipTest(f"Live quote for {symbol} has no market depth yet.")

            query = _live_depth_query(symbol=symbol, side=side, qty=qty)
            db_order = _make_live_order(
                client_id=client_id,
                symbol=symbol,
                side=side,
                qty=qty,
                security=security,
                query=query,
            )
            high_price = float(quote.get("high") or quote.get("dayHigh") or quote.get("ltp") or 0)
            decision, strategy_log = _evaluate_strategy(
                db_order,
                float(quote["ltp"]),
                quote,
                scan_count=1,
            )
            self.assertIsNone(strategy_log)
            self.assertIsNotNone(decision)
            assert decision is not None
            self.assertEqual(decision["action"], "execute")

            result = await submit_scheduled_order_to_tms(
                db_order,
                decision,
                high_price=high_price,
                fallback_qty=qty,
                security_details=security,
                order_type=side.lower(),
                tms_user=tms_user,
                execution_gate={"can_execute": True, "message": "Live smoke test gate open"},
            )

            self.assertTrue(result.submitted, result.blocked_reason or result.response)
            self.assertIsNotNone(result.response)
            print(
                "LIVE_BROKER_ORDER_RESPONSE",
                {
                    "symbol": symbol,
                    "side": side,
                    "qty": result.execution_qty,
                    "price": result.execution_price,
                    "response": result.response,
                },
            )
        finally:
            db.close()
