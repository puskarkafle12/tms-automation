"""Catalog of rule-based query scenarios for schedule gates and realtime execution tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ScheduleGateScenario:
    """A query that must be blocked (or allowed) before scheduling."""

    scenario_id: str
    category: str
    query: str
    should_block: bool
    expected_status: str
    description: str
    strategy_type: str = "Technical Buy"
    script_name: str = "CZBIL"
    side: str = "buy"
    holdings: Optional[Dict[str, int]] = None


@dataclass(frozen=True)
class RealtimeScenario:
    """Multi-scan market behaviour after a query passed schedule gates."""

    scenario_id: str
    category: str
    query: str
    price_series: List[float]
    description: str
    expected_action: str  # EXECUTE | TRACK | SKIP
    execute_at_scan: Optional[int] = None
    strategy_type: str = "Technical Buy"
    side: str = "buy"
    symbol: str = "CZBIL"
    qty: int = 100
    holding_qty: int = 0
    execution_mode: str = "live"
    expected_qty: Optional[int] = None


SCHEDULE_BLOCK_SCENARIOS: List[ScheduleGateScenario] = [
    ScheduleGateScenario(
        scenario_id="parse_empty",
        category="parse",
        query="",
        should_block=True,
        expected_status="parse_error",
        description="Empty query text",
    ),
    ScheduleGateScenario(
        scenario_id="parse_sql",
        category="parse",
        query="SELECT * FROM users",
        should_block=True,
        expected_status="parse_error",
        description="SQL syntax rejected",
    ),
    ScheduleGateScenario(
        scenario_id="unsupported_adx",
        category="unsupported_field",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "ADX" FOR SYMBOL "CZBIL" {
    WHEN technical_adx > 25
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
        should_block=True,
        expected_status="unsupported_feature",
        description="ADX is not in the field registry",
    ),
    ScheduleGateScenario(
        scenario_id="unknown_function",
        category="unsupported_function",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "BadFn" FOR SYMBOL "CZBIL" {
    WHEN FAKE_INDICATOR(ltp) > 1
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
        should_block=True,
        expected_status="unsupported_feature",
        description="Unknown function name",
    ),
    ScheduleGateScenario(
        scenario_id="universe_percentile_schedule",
        category="unsupported_schedule_context",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "Rank" FOR SYMBOL "CZBIL" {
    WHEN UNIVERSE_PERCENTILE(field=volume, operator=gte, threshold=80)
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
        should_block=True,
        expected_status="unsupported_feature",
        description="Universe ranking needs multi-symbol scan context",
    ),
    ScheduleGateScenario(
        scenario_id="sector_percentile_schedule",
        category="unsupported_schedule_context",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "Sector Rank" FOR SYMBOL "CZBIL" {
    WHEN SECTOR_PERCENTILE(field=change_percent, operator=gte, threshold=70)
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
        should_block=True,
        expected_status="unsupported_feature",
        description="Sector ranking needs universe scan context",
    ),
    ScheduleGateScenario(
        scenario_id="side_mismatch_sell_query_on_buy_strategy",
        category="validation",
        query="""
STRATEGY_VERSION 1
SIDE SELL
RULE "Sell" FOR SYMBOL "CZBIL" {
    WHEN ltp >= 200
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
        should_block=True,
        expected_status="invalid_query",
        description="SELL query cannot be saved as Technical Buy",
        strategy_type="Technical Buy",
    ),
    ScheduleGateScenario(
        scenario_id="form_symbol_not_in_plan",
        category="symbol_target",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "NABIL only" FOR SYMBOL "NABIL" {
    WHEN technical_rsi_14 < 70
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
        should_block=True,
        expected_status="invalid_query",
        description="Scheduled CZBIL order but query only targets NABIL",
        script_name="CZBIL",
    ),
    ScheduleGateScenario(
        scenario_id="sell_not_held",
        category="sell_holding",
        query="""
STRATEGY_VERSION 1
SIDE SELL
RULE "Sell CZBIL" FOR SYMBOL "CZBIL" {
    WHEN ltp >= 200
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
        should_block=True,
        expected_status="invalid_query",
        description="Cannot schedule sell without DP holding",
        strategy_type="Technical Sell",
        side="sell",
        holdings={"CZBIL": 0},
    ),
    ScheduleGateScenario(
        scenario_id="sell_qty_exceeds_holding",
        category="sell_holding",
        query="""
STRATEGY_VERSION 1
SIDE SELL
RULE "Sell CZBIL" FOR SYMBOL "CZBIL" {
    WHEN ltp >= 200
    ORDER QUANTITY 100
    EXECUTE ONCE
}
""",
        should_block=True,
        expected_status="invalid_query",
        description="Sell quantity exceeds available holding",
        strategy_type="Technical Sell",
        side="sell",
        holdings={"CZBIL": 50},
    ),
]

SCHEDULE_PASS_SCENARIOS: List[ScheduleGateScenario] = [
    ScheduleGateScenario(
        scenario_id="rsi_buy_ready",
        category="happy_path",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "CZBIL RSI" FOR SYMBOL "CZBIL" {
    WHEN technical_rsi_14 < 70
    ORDER QUANTITY 100
    EXECUTE ONCE
}
""",
        should_block=False,
        expected_status="ready",
        description="Nepse Alpha + TMS fields available",
    ),
    ScheduleGateScenario(
        scenario_id="ltp_only_buy",
        category="happy_path",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "LTP" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
        should_block=False,
        expected_status="ready",
        description="TMS live field only",
    ),
    ScheduleGateScenario(
        scenario_id="multi_symbol_includes_scheduled",
        category="happy_path",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "Basket" FOR SYMBOL IN ("CZBIL", "NABIL") {
    WHEN technical_rsi_14 < 70
    ORDER QUANTITY 10
    EXECUTE ONCE PER SYMBOL
}
""",
        should_block=False,
        expected_status="ready",
        description="Scheduled symbol is inside IN list",
        script_name="CZBIL",
    ),
    ScheduleGateScenario(
        scenario_id="sell_with_holding",
        category="happy_path",
        query="""
STRATEGY_VERSION 1
SIDE SELL
RULE "Sell" FOR SYMBOL "CZBIL" {
    WHEN ltp >= 200
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
        should_block=False,
        expected_status="ready",
        description="Sell allowed when holding exists",
        strategy_type="Technical Sell",
        side="sell",
        holdings={"CZBIL": 100},
    ),
]

REALTIME_MARKET_SCENARIOS: List[RealtimeScenario] = [
    RealtimeScenario(
        scenario_id="market_pullback_buy",
        category="price_action",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "Pullback" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 100
    EXECUTE ONCE
}
""",
        price_series=[205.0, 200.0],
        description="Price must dip to trigger limit-style buy rule",
        expected_action="EXECUTE",
        execute_at_scan=1,
        expected_qty=100,
    ),
    RealtimeScenario(
        scenario_id="rsi_not_met_keeps_tracking",
        category="nepse_alpha",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "RSI" FOR SYMBOL "CZBIL" {
    WHEN technical_rsi_14 < 30
    ORDER QUANTITY 50
    EXECUTE ONCE
}
""",
        price_series=[200.0, 200.0],
        description="RSI too high — no order until indicator aligns",
        expected_action="TRACK",
    ),
    RealtimeScenario(
        scenario_id="between_volume_filter",
        category="eligibility",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "Volume band" FOR SYMBOL "CZBIL" {
    WHEN volume BETWEEN 50000 AND 200000
    ORDER QUANTITY 25
    EXECUTE ONCE
}
""",
        price_series=[200.0],
        description="Intraday volume inside BETWEEN range",
        expected_action="EXECUTE",
        execute_at_scan=0,
        expected_qty=25,
    ),
    RealtimeScenario(
        scenario_id="require_macd_bullish",
        category="require",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "MACD gate" FOR SYMBOL "CZBIL" {
    ELIGIBILITY ltp > 0
    SIGNAL technical_rsi_14 < 70
    REQUIRE technical_macd = "Bullish"
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
        price_series=[200.0],
        description="REQUIRE boolean gate with Nepse + live fields",
        expected_action="EXECUTE",
        execute_at_scan=0,
        expected_qty=10,
    ),
    RealtimeScenario(
        scenario_id="arithmetic_trigger",
        category="arithmetic",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "Premium" FOR SYMBOL "CZBIL" {
    WHEN ltp * 1.05 > open
    ORDER QUANTITY 15
    EXECUTE ONCE
}
""",
        price_series=[210.0],
        description="Arithmetic expression on live quote fields",
        expected_action="EXECUTE",
        execute_at_scan=0,
        expected_qty=15,
    ),
    RealtimeScenario(
        scenario_id="on_cross_waits_for_transition",
        category="trigger",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "Cross" FOR SYMBOL "CZBIL" {
    WHEN technical_rsi_14 < 70
    TRIGGER ON_CROSS
    ORDER QUANTITY 20
    EXECUTE ONCE
}
""",
        price_series=[200.0, 200.0],
        description="ON_CROSS waits for false→true transition",
        expected_action="EXECUTE",
        execute_at_scan=1,
        expected_qty=20,
    ),
    RealtimeScenario(
        scenario_id="execute_once_blocks_repeat",
        category="execution_limit",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "Once" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
        price_series=[200.0, 199.0, 198.0],
        description="EXECUTE ONCE fires only on first match",
        expected_action="EXECUTE",
        execute_at_scan=0,
        expected_qty=10,
    ),
    RealtimeScenario(
        scenario_id="wrong_symbol_skips",
        category="symbol_target",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "Other" FOR SYMBOL "NABIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 10
    EXECUTE ONCE
}
""",
        price_series=[200.0],
        description="Monitoring CZBIL when plan targets NABIL only",
        expected_action="SKIP",
        symbol="CZBIL",
    ),
    RealtimeScenario(
        scenario_id="paper_mode_no_live_execute",
        category="execution_mode",
        query="""
STRATEGY_VERSION 1
SIDE BUY
RULE "Paper" FOR SYMBOL "CZBIL" {
    WHEN ltp <= 200
    ORDER QUANTITY 100
    EXECUTE ONCE
}
""",
        price_series=[200.0],
        description="Paper mode matches but does not send live TMS order",
        expected_action="TRACK",
        execution_mode="paper",
    ),
]
