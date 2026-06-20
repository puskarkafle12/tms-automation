import unittest

from utils.strategy_builder.rule_evaluator import evaluate_rule
from utils.strategy_builder.strategy_parser import parse_strategy_query
from utils.strategy_builder.history_service import TargetHistory
from utils.strategy_builder.market_normalizer import build_symbol_snapshot_from_parts
from utils.strategies.types import MarketSnapshot, ScriptDetails
from datetime import datetime


class RuleEvaluatorTest(unittest.TestCase):
    def test_evaluates_pydantic_when_nodes(self):
        plan = parse_strategy_query(
            'STRATEGY_VERSION 1\nSIDE BUY\nRULE "A" FOR SYMBOL "CZBIL" {\n'
            "WHEN technical_rsi_14 > 30\nORDER QUANTITY 100\n}"
        )
        rule = plan.rules[0]
        snap = MarketSnapshot(
            symbol="CZBIL",
            ltp=200.0,
            open=200.0,
            high=202.0,
            low=195.0,
            volume=82902.0,
            prev_close=200.0,
            change=-3.0,
            change_percent=-1.5,
            last_traded_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        )
        flat = build_symbol_snapshot_from_parts(
            "CZBIL",
            snap,
            ScriptDetails(available=True, rsi_14=35.0),
        )["flat"]
        result = evaluate_rule(rule, "CZBIL", flat, TargetHistory(), trigger_on_cross=True)
        self.assertTrue(result.matched)
        self.assertTrue(result.final_result)


if __name__ == "__main__":
    unittest.main()
