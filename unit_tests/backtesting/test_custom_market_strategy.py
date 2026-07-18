from utils.backtesting.v2_jobs import _custom_strategy_descriptor
from utils.strategy_builder.strategy_parser import parse_strategy_query, retarget_strategy_query


QUERY = """
STRATEGY_VERSION 1
SIDE BUY
BACKTEST {
  INITIAL_CAPITAL 100000
  CHARGE_MODEL "nepse_equity"
  INVESTOR_TYPE "individual"
  APPLY_CGT TRUE
  DP_CHARGE 25
  STOP_LOSS_PCT 6
  TAKE_PROFIT_PCT 15
  MAX_HOLDING_DAYS 30
}
RULE "Professional custom" FOR SYMBOL "NABIL" {
  WHEN technical_supertrend = "Bullish" AND technical_ppo_histogram > 0
  ORDER PERCENT_OF_AVAILABLE_CASH 100
  EXECUTE MAX 100 TIMES PER SYMBOL
}
"""


def test_custom_descriptor_is_versioned_and_keeps_risk_configuration():
    descriptor = _custom_strategy_descriptor(QUERY, {})
    assert descriptor["id"].startswith("custom_")
    assert descriptor["source_hash"]
    assert descriptor["defaults"] == {
        "stop_loss_pct": 6.0, "take_profit_pct": 15.0,
        "min_holding_days": 5, "max_holding_days": 30,
    }
    plan = parse_strategy_query(descriptor["custom_query_text"])
    assert plan.backtest.charge_model == "nepse_equity"
    assert plan.rules[0].symbols == ["NABIL"]


def test_one_query_can_be_retargeted_to_each_market_symbol():
    descriptor = _custom_strategy_descriptor(QUERY, {})
    nmb = parse_strategy_query(retarget_strategy_query(descriptor["custom_query_text"], ["NMB"]))
    nabil = parse_strategy_query(retarget_strategy_query(descriptor["custom_query_text"], ["NABIL"]))
    assert nmb.rules[0].symbols == ["NMB"]
    assert nabil.rules[0].symbols == ["NABIL"]
    assert nmb.rules[0].when.model_dump() == nabil.rules[0].when.model_dump()
    assert nmb.backtest.model_dump() == nabil.backtest.model_dump()
