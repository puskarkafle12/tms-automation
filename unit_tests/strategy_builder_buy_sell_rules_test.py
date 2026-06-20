import unittest

from utils.strategy_builder.history_service import TargetHistory, append_observation, consecutive_moves
from utils.strategy_builder.position_protection import compute_protective_fields, seed_position_after_buy
from utils.strategy_builder.rule_evaluator import evaluate_rule, update_history_from_snapshot
from utils.strategy_builder.side_detection import detect_instruction_side, validate_instruction_side
from utils.strategy_builder.strategy_models import PositionProtectionConfig
from utils.strategy_builder.strategy_parser import parse_strategy_query


class SideDetectionTest(unittest.TestCase):
    def test_detects_buy_and_sell(self):
        self.assertEqual(detect_instruction_side("Buy CZBIL when RSI is low"), "BUY")
        self.assertEqual(detect_instruction_side("Sell CZBIL if RSI drops"), "SELL")

    def test_rejects_side_mismatch(self):
        message = validate_instruction_side("Sell CZBIL on weakness", "buy")
        self.assertIn("SELL", message or "")


class PositionProtectionTest(unittest.TestCase):
    def test_trailing_stop_only_moves_up(self):
        protection = PositionProtectionConfig(fixed_stop_loss_price=450, trailing_stop_pct=3)
        state = seed_position_after_buy({}, entry_price=500, protection=protection)
        first = compute_protective_fields(state, 520, protection)
        second = compute_protective_fields({**state, **first}, 510, protection)
        self.assertGreaterEqual(second["current_trailing_stop"], first["current_trailing_stop"])
        self.assertEqual(second["effective_stop_price"], max(450, second["current_trailing_stop"]))


class RuleEvaluatorTemporalTest(unittest.TestCase):
    def test_consecutive_drops_requires_three_observations(self):
        history = TargetHistory()
        for value in (500, 490, 480):
            append_observation(history, "ltp", value, source_timestamp=f"t-{value}", policy="count_only_new_trade")
        self.assertTrue(consecutive_moves("ltp", history, direction="drop", count=2))
        self.assertFalse(consecutive_moves("ltp", history, direction="drop", count=3))

    def test_parses_position_protection_block(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nPOSITION_PROTECTION {\n'
            "FIXED_STOP_LOSS_PRICE 450\nTRAILING_STOP_PCT 3\n}\n"
            'RULE "A" FOR SYMBOL "CZBIL" {\nWHEN ltp < 500\nORDER QUANTITY 10\n}'
        )
        self.assertIsNotNone(plan.position_protection)
        self.assertEqual(plan.position_protection.fixed_stop_loss_price, 450)
        self.assertEqual(plan.position_protection.trailing_stop_pct, 3)


if __name__ == "__main__":
    unittest.main()
