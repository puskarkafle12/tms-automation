from utils.strategy_builder.history_service import TargetHistory
from utils.strategy_builder.preview_builder import build_trigger_preview
from utils.strategy_builder.rule_evaluator import evaluate_rule, update_history_from_snapshot
from utils.strategy_builder.strategy_parser import parse_strategy_query


def test_slope_preview_shows_slope_not_raw_kama_price():
    query = """STRATEGY_VERSION 1
SIDE BUY
RULE "KAMA Adaptive Momentum" FOR SYMBOL "CHDC" {
    WHEN ltp > technical_kama_10
      AND SLOPE(field=technical_kama_10, window=5, operator="gt", threshold=0)
      AND technical_ppo_histogram > 0
    ORDER PERCENT_OF_AVAILABLE_CASH 100
    TRIGGER ON_CROSS
    EXECUTE ONCE PER SYMBOL
}"""
    plan = parse_strategy_query(query)
    rule = plan.rules[0]
    history = TargetHistory()
    for index, kama in enumerate([2100, 2110, 2120, 2130, 2140, 2172.57]):
        update_history_from_snapshot(history, {
            "ltp": 2254,
            "technical_kama_10": kama,
            "technical_ppo_histogram": 0.99,
            "received_at": f"2026-01-{index + 1:02d}",
            "last_traded_at": f"2026-01-{index + 1:02d}",
        })
    flat = {
        "ltp": 2254,
        "technical_kama_10": 2172.57,
        "technical_ppo_histogram": 0.99,
        "received_at": "2026-01-06",
        "last_traded_at": "2026-01-06",
    }
    evaluation = evaluate_rule(rule, "CHDC", flat, history, trigger_on_cross=False)
    preview = build_trigger_preview(rule, flat, evaluation)
    slope = next(item for item in preview.conditions if "slope" in item.strategy_text.lower())
    assert "={'type':" not in slope.strategy_text
    assert "Slope of" in slope.strategy_text or "SLOPE(" in slope.strategy_text
    assert slope.current_display is not None
    assert "2,172" not in str(slope.current_display)
    assert float(str(slope.current_display).replace(",", "")) > 0
    assert slope.target_display in {"0", "0.00"}
    assert slope.matched is True


def test_slope_preview_without_history_does_not_fake_kama_as_current():
    query = """STRATEGY_VERSION 1
SIDE BUY
RULE "Slope Only" FOR SYMBOL "CHDC" {
    WHEN SLOPE(field=technical_kama_10, window=5, operator="gt", threshold=0)
    ORDER QUANTITY 1
}"""
    plan = parse_strategy_query(query)
    rule = plan.rules[0]
    flat = {"ltp": 2254, "technical_kama_10": 2172.57}
    history = TargetHistory()
    evaluation = evaluate_rule(rule, "CHDC", flat, history, trigger_on_cross=False)
    preview = build_trigger_preview(rule, flat, evaluation)
    slope = preview.conditions[0]
    assert "Slope of" in slope.strategy_text
    assert slope.current_display is None
    assert slope.matched is False
