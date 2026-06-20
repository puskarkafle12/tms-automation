import unittest
from unittest.mock import patch

from utils.strategies.types import MarketSnapshot, OrderContext, ScannerMemory, ScriptDetails, StrategyDecision
from utils.strategy_builder.strategy_models import OrderSizing, RuleBlock
from utils.strategy_builder.strategy_delegate import evaluate_delegated_strategy


class StrategyDelegationRuntimeTest(unittest.TestCase):
    def test_fixed_price_buy_executes_when_ltp_below_target(self):
        rule = RuleBlock(
            rule_id="r1",
            name="Fixed",
            symbols=["NABIL"],
            use_strategy="Fixed Price Buy",
            strategy_params={"TARGET_PRICE": 600},
            order=OrderSizing(mode="quantity", value=10),
        )
        snapshot = MarketSnapshot(symbol="NABIL", ltp=580, open=590, high=610, low=575)
        memory = ScannerMemory(last_prices=[580], previous_ltp=581)
        parent = OrderContext(
            strategy_type="Custom Query Buy",
            canonical_strategy="Custom Query Buy",
            side="buy",
            symbol="NABIL",
            qty=10,
            remaining_qty=10,
            target_price=580,
        )
        decision = evaluate_delegated_strategy(
            rule,
            plan_side="BUY",
            symbol="NABIL",
            parent_ctx=parent,
            snapshot=snapshot,
            memory=memory,
            details=ScriptDetails(available=True),
        )
        self.assertEqual(decision.action, "EXECUTE")
        self.assertEqual(decision.price, 600)

    def test_fixed_price_buy_tracks_when_above_target(self):
        rule = RuleBlock(
            rule_id="r1",
            name="Fixed",
            symbols=["NABIL"],
            use_strategy="Fixed Price Buy",
            strategy_params={"TARGET_PRICE": 500},
            order=OrderSizing(mode="quantity", value=10),
        )
        snapshot = MarketSnapshot(symbol="NABIL", ltp=580)
        parent = OrderContext(
            strategy_type="Custom Query Buy",
            canonical_strategy="Custom Query Buy",
            side="buy",
            symbol="NABIL",
            qty=10,
            remaining_qty=10,
            target_price=580,
        )
        decision = evaluate_delegated_strategy(
            rule,
            plan_side="BUY",
            symbol="NABIL",
            parent_ctx=parent,
            snapshot=snapshot,
            memory=ScannerMemory(),
            details=ScriptDetails(),
        )
        self.assertEqual(decision.action, "TRACK")

    @patch("utils.strategy_builder.strategy_delegate.can_place_order")
    def test_risk_guard_blocks_execute(self, mock_risk):
        from utils.strategies.risk_guard import RiskDecision

        mock_risk.return_value = RiskDecision(False, "BLOCKED", "Risk blocked")
        rule = RuleBlock(
            rule_id="r1",
            name="Fixed",
            symbols=["NABIL"],
            use_strategy="Fixed Price Buy",
            strategy_params={"TARGET_PRICE": 600},
            order=OrderSizing(mode="quantity", value=10),
        )
        snapshot = MarketSnapshot(symbol="NABIL", ltp=580)
        parent = OrderContext(
            strategy_type="Custom Query Buy",
            canonical_strategy="Custom Query Buy",
            side="buy",
            symbol="NABIL",
            qty=10,
            remaining_qty=10,
            target_price=580,
        )
        decision = evaluate_delegated_strategy(
            rule,
            plan_side="BUY",
            symbol="NABIL",
            parent_ctx=parent,
            snapshot=snapshot,
            memory=ScannerMemory(),
            details=ScriptDetails(),
        )
        self.assertEqual(decision.action, "NO_TRADE")


if __name__ == "__main__":
    unittest.main()
