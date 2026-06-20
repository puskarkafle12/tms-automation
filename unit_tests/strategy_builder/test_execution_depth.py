import unittest

from utils.strategy_builder.execution_depth import (
    depth_quantity_sufficient,
    resolve_depth_order_quantity,
    resolve_rule_execution_price,
)
from utils.strategy_builder.strategy_parser import parse_strategy_query
from utils.strategies.types import MarketSnapshot, OrderBookLevel


def _snapshot_with_depth(*, ltp: float = 200.0, top_buy_qty: int = 50, top_sell_qty: int = 40):
    return MarketSnapshot(
        symbol="CZBIL",
        ltp=ltp,
        top_buy_orders=[OrderBookLevel(price=199.5, quantity=top_buy_qty)],
        top_sell_orders=[OrderBookLevel(price=200.5, quantity=top_sell_qty)],
    )


class ExecutionDepthTest(unittest.TestCase):
    def test_parse_order_price_top_buy_and_partial_sell(self):
        query = """
STRATEGY_VERSION 1
SIDE SELL
RULE "Top Buyer Exit" FOR SYMBOL "CZBIL" {
    WHEN ltp > 0
    ORDER PARTIAL_TOP_BUY 100 PRICE TOP_BUY
    EXECUTE ONCE
}
"""
        plan = parse_strategy_query(query)
        order = plan.rules[0].order
        self.assertEqual(order.mode, "partial_top_buy")
        self.assertEqual(order.value, 100.0)
        self.assertEqual(order.price_source, "top_buy")

    def test_partial_top_buy_caps_to_top_buy_qty(self):
        snapshot = _snapshot_with_depth(top_buy_qty=30)
        flat = {"top_buy_quantity": 30}
        qty, note = resolve_depth_order_quantity(
            order_mode="partial_top_buy",
            order_value=100,
            snapshot=snapshot,
            flat=flat,
            side="SELL",
            form_qty=100,
            holding_qty=80,
        )
        self.assertEqual(qty, 30)
        self.assertIn("Partial sell", note or "")

    def test_top_buy_qty_sell_uses_top_level_only(self):
        snapshot = _snapshot_with_depth(top_buy_qty=25)
        flat = {"top_buy_quantity": 25}
        qty, note = resolve_depth_order_quantity(
            order_mode="top_buy_qty",
            order_value=None,
            snapshot=snapshot,
            flat=flat,
            side="SELL",
            form_qty=100,
            holding_qty=100,
        )
        self.assertEqual(qty, 25)
        self.assertIsNone(note)

    def test_depth_quantity_sufficient_false_when_order_exceeds_top(self):
        snapshot = _snapshot_with_depth(top_buy_qty=10)
        flat = {"top_buy_quantity": 10}
        ok, message = depth_quantity_sufficient(
            side="SELL",
            requested_qty=50,
            snapshot=snapshot,
            flat=flat,
        )
        self.assertFalse(ok)
        self.assertIn("less than order", message)

    def test_resolve_rule_execution_price_sell_at_top_buy(self):
        snapshot = _snapshot_with_depth(ltp=200.0, top_buy_qty=100)
        price, source = resolve_rule_execution_price(snapshot, "SELL", "top_buy")
        self.assertEqual(price, 199.5)
        self.assertEqual(source, "Top Buy")

    def test_resolve_rule_execution_price_buy_at_top_sell(self):
        snapshot = _snapshot_with_depth(ltp=200.0, top_sell_qty=100)
        price, source = resolve_rule_execution_price(snapshot, "BUY", "top_sell")
        self.assertEqual(price, 200.5)
        self.assertEqual(source, "Top Sell")

    def test_require_top_buy_quantity_in_query(self):
        query = """
STRATEGY_VERSION 1
SIDE SELL
RULE "Depth Check" FOR SYMBOL "CZBIL" {
    WHEN ltp > 0
    REQUIRE market_depth_available = TRUE AND top_buy_quantity >= 10
    ORDER TOP_BUY_QTY PRICE TOP_BUY
    EXECUTE ONCE
}
"""
        plan = parse_strategy_query(query)
        self.assertIsNotNone(plan.rules[0].require)


if __name__ == "__main__":
    unittest.main()
