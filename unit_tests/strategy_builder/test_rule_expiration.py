import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from utils.strategy_builder.rule_expiration import evaluate_rule_based_expiration
from utils.strategies.types import MarketSnapshot, OrderContext, StrategyConfig


class RuleExpirationPolicyTest(unittest.TestCase):
    def _ctx(self, *, expiry_action="BUY_AT_PROTECTED_LTP", extra=None, expiry_time=None):
        return OrderContext(
            strategy_type="Custom Query Buy",
            canonical_strategy="Custom Query Buy",
            side="buy",
            symbol="API",
            qty=10,
            remaining_qty=10,
            target_price=0,
            expiry_time=expiry_time or (datetime.utcnow() - timedelta(minutes=1)),
            expiry_action=expiry_action,
            config=StrategyConfig(extra=extra or {}),
        )

    def test_top_sell_unavailable_falls_back_to_cancel(self):
        decision = evaluate_rule_based_expiration(
            self._ctx(
                expiry_action="BUY_AT_TOP_SELL",
                extra={"expiration": {"top_sell_fallback": "CANCEL"}},
            ),
            MarketSnapshot(symbol="API", ltp=480),
            MagicMock(),
        )
        self.assertEqual(decision.action, "EXPIRE")
        self.assertEqual(decision.reason_code, "EXPIRY_TOP_SELL_UNAVAILABLE")

    def test_market_closed_execute_at_next_quote_sets_pending(self):
        decision = evaluate_rule_based_expiration(
            self._ctx(
                extra={
                    "expiration": {
                        "market_closed_policy": "EXECUTE_AT_NEXT_VALID_MARKET_QUOTE",
                    }
                }
            ),
            MarketSnapshot(symbol="API", ltp=0),
            MagicMock(),
        )
        self.assertEqual(decision.action, "TRACK")
        self.assertEqual(decision.tracking_status, "EXPIRY_PENDING_MARKET_OPEN")
        self.assertTrue(decision.mutate.get("expiration_pending_market_open"))

    def test_secondary_expiry_cancels_pending_execution(self):
        decision = evaluate_rule_based_expiration(
            self._ctx(
                extra={
                    "expiration": {
                        "secondary_expires_at": (datetime.utcnow() - timedelta(minutes=1)).isoformat(),
                    }
                }
            ),
            MarketSnapshot(symbol="API", ltp=480),
            MagicMock(),
        )
        self.assertEqual(decision.action, "EXPIRE")
        self.assertEqual(decision.reason_code, "EXPIRY_SECONDARY_CANCELLED")


if __name__ == "__main__":
    unittest.main()
