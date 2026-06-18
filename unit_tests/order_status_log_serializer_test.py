import unittest

from models.scheduled_order import ScheduledOrder
from schemas.schemas import OrderCreateRequest
from utils.order_status_log_serializer import serialize_order_status_log, status_log_from_scheduled_order


class TestOrderStatusLogSerializer(unittest.TestCase):
    def test_status_log_preserves_strategy_and_execution_fields(self):
        order = ScheduledOrder(
            OrderCreateRequest(
                client_id="MN336760",
                script_name="AKJCL",
                price=385.0,
                qty=222,
                order_type="sell",
                status="Executed",
                strategy_type="Capital Protection Sell",
                stop_loss_price=385.0,
                average_buy_price=400.0,
                max_allowed_slippage_percent=1.0,
            )
        )
        order.order_id = 99
        order.execution_price = 385.0
        order.execution_price_source = "Top Buy"
        order.execution_reason = "SELL_TRIGGERED_CAPITAL_PROTECTION: confirmed stop"

        log = status_log_from_scheduled_order(order)
        payload = serialize_order_status_log(log)

        self.assertEqual(payload["strategy_type"], "Capital Protection Sell")
        self.assertEqual(payload["requested_price"], 385.0)
        self.assertEqual(payload["execution_price"], 385.0)
        self.assertEqual(payload["price"], 385.0)
        self.assertEqual(payload["stop_loss_price"], 385.0)
        self.assertEqual(payload["average_buy_price"], 400.0)


if __name__ == "__main__":
    unittest.main()
