import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from utils.strategy_builder.schedule_baseline import (
    ScheduleBaselineError,
    apply_fixed_trigger_to_compiled_plan,
    calculate_trigger_price,
    compile_baseline_strategy_config,
    reject_self_referential_drop_query,
    validate_expiration_timestamp,
)
from utils.strategy_builder.strategy_parser import StrategyQueryError, parse_strategy_query
from utils.strategy_builder.rule_expiration import (
    evaluate_rule_based_expiration,
    has_expired,
)
from utils.strategies.types import MarketSnapshot, OrderContext, StrategyConfig


QUERY = """STRATEGY_VERSION 1
SIDE BUY
RULE "Drop Buy" FOR SYMBOL "API" {
    WHEN technical_rsi_14 < 70
    ORDER QUANTITY 10
    EXECUTE ONCE PER SYMBOL
}"""


class ScheduleBaselineTest(unittest.TestCase):
    def test_reference_ltp_500_produces_trigger_450(self):
        self.assertEqual(calculate_trigger_price(500, 10), 450.0)

    def test_trigger_stays_fixed_when_live_ltp_rises(self):
        trigger = calculate_trigger_price(500, 10)
        self.assertEqual(trigger, 450.0)
        self.assertEqual(calculate_trigger_price(550, 10), 495.0)
        self.assertEqual(trigger, 450.0)

    def test_rejects_self_referential_drop_expression(self):
        with self.assertRaises(StrategyQueryError):
            reject_self_referential_drop_query(
                'STRATEGY_VERSION 1\nSIDE BUY\nRULE "X" FOR SYMBOL "API" {\nWHEN ltp <= ltp * 0.90\n}'
            )

    def test_compiled_plan_uses_fixed_numeric_trigger(self):
        plan = parse_strategy_query(QUERY)
        compiled = apply_fixed_trigger_to_compiled_plan(
            plan.model_dump(),
            symbol="API",
            trigger_price=450,
        )
        when = compiled["rules"][0]["when"]
        self.assertEqual(when["left"]["name"], "ltp")
        self.assertEqual(when["operator"], "lte")
        self.assertEqual(when["right"]["value"], 450.0)

    def test_live_ltp_450_matches_fixed_trigger_rule(self):
        plan = parse_strategy_query(QUERY)
        compiled = apply_fixed_trigger_to_compiled_plan(plan.model_dump(), symbol="API", trigger_price=450)
        when = compiled["rules"][0]["when"]
        self.assertEqual(when["right"]["value"], 450.0)

    def test_rejects_past_expiration(self):
        with self.assertRaises(ScheduleBaselineError):
            validate_expiration_timestamp(datetime.utcnow() - timedelta(minutes=1))

    def test_compile_baseline_config_persists_fields(self):
        baseline = {
            "symbol": "API",
            "reference_ltp": 500.0,
            "reference_ltp_captured_at": datetime.utcnow().isoformat(),
            "drop_percent": 10.0,
            "trigger_price": 450.0,
        }
        config = compile_baseline_strategy_config(
            query_text=QUERY,
            symbol="API",
            baseline=baseline,
            fixed_symbols=["API", "NABIL"],
        )
        self.assertTrue(config["capture_reference_ltp"])
        self.assertEqual(config["schedule_baseline"]["trigger_price"], 450.0)
        self.assertEqual(config["fixed_symbols"], ["API", "NABIL"])
        self.assertIn("baseline_warning", config)

    def test_merge_baseline_into_order_fields_freezes_reference_values(self):
        from utils.strategy_builder.schedule_baseline import merge_baseline_into_order_fields

        baseline = {
            "symbol": "API",
            "reference_ltp": 500.0,
            "reference_ltp_captured_at": datetime.utcnow().isoformat(),
            "drop_percent": 10.0,
            "trigger_price": 450.0,
        }
        order_data = MagicMock(
            reference_ltp=None,
            trigger_price=None,
            drop_percent=None,
            reference_ltp_captured_at=None,
        )

        merge_baseline_into_order_fields(order_data, baseline)

        self.assertEqual(order_data.reference_ltp, 500.0)
        self.assertEqual(order_data.trigger_price, 450.0)
        self.assertEqual(order_data.drop_percent, 10.0)
        self.assertIsNotNone(order_data.reference_ltp_captured_at)


class RuleExpirationTest(unittest.TestCase):
    def _ctx(self, *, expiry_action="CANCEL", extra=None):
        return OrderContext(
            strategy_type="Custom Query Buy",
            canonical_strategy="Custom Query Buy",
            side="buy",
            symbol="API",
            qty=10,
            remaining_qty=10,
            target_price=0,
            expiry_time=datetime.utcnow() - timedelta(minutes=1),
            expiry_action=expiry_action,
            config=StrategyConfig(extra=extra or {}),
        )

    def test_cancel_expires_without_execute(self):
        decision = evaluate_rule_based_expiration(
            self._ctx(),
            MarketSnapshot(symbol="API", ltp=480),
            MagicMock(),
        )
        self.assertEqual(decision.action, "EXPIRE")
        self.assertEqual(decision.reason_code, "EXPIRY_CANCELLED")

    def test_protected_ltp_expiration_executes_with_fresh_quote(self):
        decision = evaluate_rule_based_expiration(
            self._ctx(expiry_action="BUY_AT_PROTECTED_LTP"),
            MarketSnapshot(symbol="API", ltp=480),
            MagicMock(),
        )
        self.assertEqual(decision.action, "EXECUTE")
        self.assertEqual(decision.reason_code, "BUY_AT_PROTECTED_LTP")
        self.assertGreater(decision.price, 0)

    def test_has_expired_false_before_timestamp(self):
        ctx = self._ctx()
        ctx.expiry_time = datetime.utcnow() + timedelta(hours=1)
        self.assertFalse(has_expired(ctx))


class AsyncBaselineCaptureTest(unittest.IsolatedAsyncioTestCase):
    async def test_capture_baselines_for_multiple_symbols(self):
        from utils.strategy_builder.schedule_baseline import capture_baselines_for_symbols

        tms_user = AsyncMock()
        tms_user.get_security_id.return_value = {"id": "1"}
        tms_user.get_stock_details_async.return_value = {"ltp": 500, "lastTradedTime": "2026-06-19T10:00:00"}

        baselines, errors = await capture_baselines_for_symbols(
            tms_user,
            ["API", "NABIL"],
            drop_percent=10,
        )
        self.assertEqual(len(baselines), 2)
        self.assertEqual(errors, [])
        self.assertEqual({row["symbol"] for row in baselines}, {"API", "NABIL"})
        self.assertEqual(baselines[0]["trigger_price"], 450.0)


if __name__ == "__main__":
    unittest.main()
