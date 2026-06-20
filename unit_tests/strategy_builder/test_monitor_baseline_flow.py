import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from utils.monitor_order import _try_claim_order_for_execution
from utils.strategy_builder.rule_expiration import evaluate_rule_based_expiration
from utils.strategies.types import MarketSnapshot, OrderContext, StrategyConfig


class MonitorBaselineFlowTest(unittest.TestCase):
    def test_try_claim_order_for_execution_is_atomic(self):
        db = MagicMock()
        db.execute.return_value.rowcount = 1
        self.assertTrue(_try_claim_order_for_execution(db, 7))
        db.execute.return_value.rowcount = 0
        self.assertFalse(_try_claim_order_for_execution(db, 7))

    def test_expiration_executed_prevents_repeat_execution(self):
        ctx = OrderContext(
            strategy_type="Custom Query Buy",
            canonical_strategy="Custom Query Buy",
            side="buy",
            symbol="API",
            qty=10,
            remaining_qty=10,
            target_price=0,
            expiry_time=datetime.utcnow() - timedelta(minutes=5),
            expiry_action="BUY_AT_PROTECTED_LTP",
            config=StrategyConfig(extra={"expiration_executed": True}),
        )
        decision = evaluate_rule_based_expiration(
            ctx,
            MarketSnapshot(symbol="API", ltp=480),
            MagicMock(),
        )
        self.assertEqual(decision.action, "EXPIRE")
        self.assertEqual(decision.reason_code, "STRATEGY_EXPIRED")

    def test_trigger_before_expiry_does_not_expire(self):
        ctx = OrderContext(
            strategy_type="Custom Query Buy",
            canonical_strategy="Custom Query Buy",
            side="buy",
            symbol="API",
            qty=10,
            remaining_qty=10,
            target_price=0,
            expiry_time=datetime.utcnow() + timedelta(hours=2),
            expiry_action="CANCEL",
            config=StrategyConfig(
                extra={
                    "schedule_baseline": {"trigger_price": 450, "reference_ltp": 500},
                    "compiled_plan": {
                        "rules": [
                            {
                                "symbols": ["API"],
                                "when": {
                                    "type": "comparison",
                                    "left": {"type": "field", "name": "ltp"},
                                    "operator": "lte",
                                    "right": {"type": "literal", "value": 450},
                                },
                            }
                        ]
                    },
                }
            ),
        )
        from utils.strategy_builder.rule_expiration import evaluate_rule_based_expiration

        decision = evaluate_rule_based_expiration(
            ctx,
            MarketSnapshot(symbol="API", ltp=440),
            MagicMock(),
        )
        self.assertIsNone(decision)


if __name__ == "__main__":
    unittest.main()
