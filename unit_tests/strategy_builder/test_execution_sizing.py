import unittest

from utils.strategy_builder.constants import DEFAULT_RULE_ORDER_QUANTITY
from utils.strategy_builder.execution_sizing import resolve_order_quantity


class ExecutionSizingTest(unittest.TestCase):
    def test_quantity_mode_defaults_to_ten_without_value_or_form_qty(self):
        qty = resolve_order_quantity(order_mode="quantity", order_value=None, ltp=200.0)
        self.assertEqual(qty, DEFAULT_RULE_ORDER_QUANTITY)
        self.assertEqual(qty, 10)

    def test_quantity_mode_uses_explicit_value(self):
        qty = resolve_order_quantity(order_mode="quantity", order_value=100, ltp=200.0)
        self.assertEqual(qty, 100)

    def test_from_form_falls_back_to_default_when_form_qty_missing(self):
        qty = resolve_order_quantity(order_mode="quantity", order_value=-1, ltp=200.0, form_qty=0)
        self.assertEqual(qty, 10)


if __name__ == "__main__":
    unittest.main()
