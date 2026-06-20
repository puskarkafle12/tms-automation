"""NEPSE Strategy Query E2E test pack (from NEPSE_Strategy_E2E_Test_Pack.md).

Single source of query fixtures. Runtime tests live in test_nepse_strategy_e2e_pack.py;
some cases are covered elsewhere — see EXISTING_COVERAGE.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, List, Optional, Set, Tuple


@dataclass(frozen=True)
class ValidQueryCase:
    case_id: str
    title: str
    query: str
    side: str = "buy"
    strategy_type: str = "Custom Query Buy"
    symbols: Tuple[str, ...] = ("NABIL",)
    parse_only: bool = False
    covered_elsewhere: FrozenSet[str] = frozenset()


@dataclass(frozen=True)
class InvalidQueryCase:
    case_id: str
    title: str
    query: str
    check: str  # parse | validate | preflight | baseline | runtime
    expect_codes: Tuple[str, ...] = ()
    side: str = "buy"
    strategy_type: str = "Custom Query Buy"
    covered_elsewhere: FrozenSet[str] = frozenset()


# Maps case IDs to existing test modules (avoid duplicating runtime coverage).
EXISTING_COVERAGE: Dict[str, str] = {
    "Q02": "unit_tests/strategy_builder/test_reference_runtime.py",
    "Q07": "unit_tests/strategies/test_rule_based_realtime_matrix.py::test_consecutive_rises_with_min_change",
    "Q08": "unit_tests/strategy_builder/test_schedule_preflight.py",
    "Q09": "unit_tests/strategy_builder/test_execution_depth.py",
    "Q24": "unit_tests/strategy_builder/test_execution_depth.py::test_depth_sell_query_executes_at_top_buy_end_to_end",
    "N01": "unit_tests/strategy_builder/query_strategy_scenarios.py::unsupported_adx",
    "N07": "unit_tests/strategy_builder/query_strategy_scenarios.py::universe_percentile_schedule",
    "P01": "unit_tests/strategy_builder/test_schedule_preflight.py::test_requires_logged_in_client",
    "P02": "unit_tests/strategy_builder/test_query_strategy_gate_matrix.py::test_client_not_logged_in_blocks_monitoring",
    "P08": "unit_tests/strategy_builder/query_strategy_scenarios.py::sell_not_held",
    "M01": "unit_tests/strategy_builder/test_reference_runtime.py::test_live_ltp_changes_but_reference_stays_fixed",
    "E10": "unit_tests/strategy_builder/query_strategy_scenarios.py::execute_once_blocks_repeat",
}


VALID_QUERIES: List[ValidQueryCase] = [
    ValidQueryCase(
        "Q01",
        "Basic parser, schedule, and waiting-state BUY",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Basic Waiting Buy" FOR SYMBOL "NABIL" {
    WHEN ltp <= 1
    ORDER QUANTITY 10
    CONFIRM IMMEDIATE
    TRIGGER LEVEL
    MAX_DATA_AGE 30 SECONDS
    EXECUTE ONCE
}""",
        symbols=("NABIL",),
    ),
    ValidQueryCase(
        "Q02",
        "Bulk schedule-time REFERENCE snapshot",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Bulk One Percent Pullback" FOR SYMBOL IN ("NABIL", "EBL", "SCB") {
    ELIGIBILITY ltp <= REFERENCE(field=ltp) * 0.99
    SIGNAL technical_rsi_14 BETWEEN 20 AND 60
    REQUIRE volume > 0
    ORDER QUANTITY 10
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    MAX_SLIPPAGE_PCT 1
    MAX_DATA_AGE 30 SECONDS
    EXECUTE ONCE PER SYMBOL
}""",
        symbols=("NABIL", "EBL", "SCB"),
        covered_elsewhere=frozenset({"Q02"}),
    ),
    ValidQueryCase(
        "Q03",
        "Bulk immediate execution path (paper first)",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Bulk Paper Execution" FOR SYMBOL IN ("NABIL", "EBL", "SCB") {
    WHEN ltp > 0
    REQUIRE market_depth_available = TRUE AND top_sell_quantity >= 10
    ORDER PARTIAL_TOP_SELL 10 PRICE TOP_SELL
    CONFIRM IMMEDIATE
    TRIGGER LEVEL
    MAX_SLIPPAGE_PCT 1
    MAX_DATA_AGE 30 SECONDS
    EXECUTE ONCE PER SYMBOL
}""",
        symbols=("NABIL", "EBL", "SCB"),
    ),
    ValidQueryCase(
        "Q04",
        "Confirmation counter and distinct-trade semantics",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Two Scan Confirmation" FOR SYMBOL "NABIL" {
    WHEN ltp > 0
    ORDER QUANTITY 10
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    MAX_DATA_AGE 30 SECONDS
    EXECUTE ONCE
}""",
        symbols=("NABIL",),
    ),
    ValidQueryCase(
        "Q05",
        "Rolling 2-of-3 confirmation, cooldown, and max executions",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Rolling Confirmation Reentry" FOR SYMBOL "CZBIL" {
    WHEN change_percent > 0
    ORDER QUANTITY 10
    CONFIRM MATCHES 2 OF LAST 3 SCANS
    TRIGGER LEVEL
    MAX_DATA_AGE 30 SECONDS
    COOLDOWN 5 MINUTES
    EXECUTE MAX 3 TIMES PER SYMBOL
}""",
        symbols=("CZBIL",),
    ),
    ValidQueryCase(
        "Q06",
        "ON_CROSS transition test",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Cross Above Test" FOR SYMBOL "NABIL" {
    WHEN CROSSES_ABOVE(field=ltp, threshold=500)
    ORDER QUANTITY 10
    CONFIRM IMMEDIATE
    TRIGGER ON_CROSS
    EXECUTE ONCE
}""",
        symbols=("NABIL",),
    ),
    ValidQueryCase(
        "Q07",
        "Consecutive-rise history test",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Consecutive Rise Test" FOR SYMBOL "EBL" {
    WHEN CONSECUTIVE_RISES(field=ltp, count=2, min_total_change_pct=0.5)
    ORDER QUANTITY 10
    CONFIRM IMMEDIATE
    TRIGGER LEVEL
    EXECUTE ONCE
}""",
        symbols=("EBL",),
        parse_only=True,
        covered_elsewhere=frozenset({"Q07"}),
    ),
    ValidQueryCase(
        "Q08",
        "52-week derived-field preflight and monitoring",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Near 52 Week Low Test" FOR SYMBOL IN ("NABIL", "EBL", "GBIME") {
    WHEN position_in_52_week_range_percent <= 10
    ORDER QUANTITY 10
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    EXECUTE ONCE PER SYMBOL
}""",
        symbols=("NABIL", "EBL", "GBIME"),
        covered_elsewhere=frozenset({"Q08"}),
    ),
    ValidQueryCase(
        "Q09",
        "Market-depth signal and price-source test",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Depth Controlled Buy" FOR SYMBOL "NABIL" {
    WHEN DEPTH_IMBALANCE(levels=3, operator="gte", threshold=0.2)
    REQUIRE market_depth_available = TRUE AND SPREAD_REMAINS_BELOW(threshold=1, scans=2)
    ORDER PARTIAL_TOP_SELL 10 PRICE TOP_SELL
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    MAX_SLIPPAGE_PCT 1
    EXECUTE ONCE
}""",
        symbols=("NABIL",),
        covered_elsewhere=frozenset({"Q09"}),
    ),
    ValidQueryCase(
        "Q10",
        "Fixed Price Buy",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Fixed Price Buy Test" FOR SYMBOL "NABIL" {
    USE STRATEGY "Fixed Price Buy"
    TARGET_PRICE 500
    ORDER QUANTITY 10
    MAX_SLIPPAGE_PCT 1
    EXECUTE ONCE PER SYMBOL
}""",
    ),
    ValidQueryCase(
        "Q11",
        "Confirmed Breakout Buy",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Breakout Buy Test" FOR SYMBOL "EBL" {
    USE STRATEGY "Confirmed Breakout Buy"
    TARGET_PRICE 700
    ORDER QUANTITY 10
    MAX_SLIPPAGE_PCT 1
    EXECUTE ONCE PER SYMBOL
}""",
        symbols=("EBL",),
    ),
    ValidQueryCase(
        "Q12",
        "Smart Pullback Buy",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Smart Pullback Test" FOR SYMBOL "CZBIL" {
    USE STRATEGY "Smart Pullback Buy"
    TARGET_PRICE 300
    ORDER QUANTITY 10
    MAX_SLIPPAGE_PCT 1
    EXECUTE ONCE PER SYMBOL
}""",
        symbols=("CZBIL",),
    ),
    ValidQueryCase(
        "Q13",
        "Quality Pullback Recovery Buy",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Quality Pullback Test" FOR SYMBOL "GBIME" {
    USE STRATEGY "Quality Pullback Recovery Buy"
    MIN_BUY_SCORE 65
    REQUIRE_VOLUME_INCREASE TRUE
    REQUIRE_FRESH_TRADE TRUE
    ORDER QUANTITY 10
    EXECUTE ONCE PER SYMBOL
}""",
        symbols=("GBIME",),
    ),
    ValidQueryCase(
        "Q14",
        "Mean Reversion Bounce Buy",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Mean Reversion Test" FOR SYMBOL "NABIL" {
    USE STRATEGY "Mean Reversion Bounce Buy"
    MIN_BUY_SCORE 60
    REQUIRE_VOLUME_INCREASE TRUE
    REQUIRE_FRESH_TRADE TRUE
    ORDER QUANTITY 10
    EXECUTE ONCE PER SYMBOL
}""",
    ),
    ValidQueryCase(
        "Q15",
        "Order Book Strength Buy",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Order Book Strength Test" FOR SYMBOL "EBL" {
    USE STRATEGY "Order Book Strength Buy"
    MIN_BUY_SCORE 60
    REQUIRE_VOLUME_INCREASE TRUE
    REQUIRE_FRESH_TRADE TRUE
    REQUIRE market_depth_available = TRUE
    ORDER PARTIAL_TOP_SELL 10 PRICE TOP_SELL
    MAX_SLIPPAGE_PCT 1
    EXECUTE ONCE PER SYMBOL
}""",
        symbols=("EBL",),
    ),
    ValidQueryCase(
        "Q16",
        "Time-Based Buy",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Timed Quality Buy Test" FOR SYMBOL "NABIL" {
    USE STRATEGY "Time-Based Buy"
    EXPIRY_TIME "2026-06-22T14:45"
    WRAPPED_STRATEGY "Quality Pullback Recovery Buy"
    ORDER QUANTITY 10
    EXECUTE ONCE PER SYMBOL
}""",
    ),
    ValidQueryCase(
        "Q17",
        "Different strategies per symbol in one schedule",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "NABIL Fixed" FOR SYMBOL "NABIL" {
    USE STRATEGY "Fixed Price Buy"
    TARGET_PRICE 500
    ORDER QUANTITY 10
    EXECUTE ONCE PER SYMBOL
}
RULE "EBL Breakout" FOR SYMBOL "EBL" {
    USE STRATEGY "Confirmed Breakout Buy"
    TARGET_PRICE 700
    ORDER QUANTITY 10
    EXECUTE ONCE PER SYMBOL
}
RULE "GBIME Quality" FOR SYMBOL "GBIME" {
    USE STRATEGY "Quality Pullback Recovery Buy"
    MIN_BUY_SCORE 65
    ORDER QUANTITY 10
    EXECUTE ONCE PER SYMBOL
}""",
        symbols=("NABIL", "EBL", "GBIME"),
    ),
    ValidQueryCase(
        "Q18",
        "Entry plus fixed and trailing protection state",
        """STRATEGY_VERSION 1
SIDE BUY
POSITION_PROTECTION {
    FIXED_STOP_LOSS_PRICE 450
    TRAILING_STOP_PCT 3
}
RULE "Protected Buy Test" FOR SYMBOL "NABIL" {
    WHEN ltp <= 500
    ORDER QUANTITY 10
    CONFIRM IMMEDIATE
    TRIGGER LEVEL
    EXECUTE ONCE
}""",
    ),
    ValidQueryCase(
        "Q19",
        "Simple fixed-price custom SELL",
        """STRATEGY_VERSION 1
SIDE SELL
RULE "Fixed Price Sell Test" FOR SYMBOL "NABIL" {
    WHEN ltp >= 600
    ORDER PERCENT_OF_HOLDING 10
    CONFIRM IMMEDIATE
    TRIGGER ON_CROSS
    MAX_SLIPPAGE_PCT 1
    MISSING_HOLDING REJECT
    EXECUTE ONCE
}""",
        side="sell",
        strategy_type="Custom Query Sell",
    ),
    ValidQueryCase(
        "Q20",
        "Capital Protection Sell",
        """STRATEGY_VERSION 1
SIDE SELL
RULE "Capital Protection Test" FOR SYMBOL "NABIL" {
    USE STRATEGY "Capital Protection Sell"
    STOP_LOSS_PRICE 480
    AVERAGE_BUY_PRICE 500
    BREAK_EVEN_TRIGGER_PCT 3
    TRAILING_DROP_PCT 3
    ORDER PERCENT_OF_HOLDING 100
    MAX_SLIPPAGE_PCT 1
    MISSING_HOLDING REJECT
    EXECUTE ONCE PER SYMBOL
}""",
        side="sell",
        strategy_type="Custom Query Sell",
    ),
    ValidQueryCase(
        "Q21",
        "Profit Ladder Sell",
        """STRATEGY_VERSION 1
SIDE SELL
RULE "Profit Ladder Test" FOR SYMBOL "EBL" {
    USE STRATEGY "Profit Ladder Sell"
    FIRST_TARGET 720
    FIRST_PERCENT 50
    SECOND_TARGET 780
    SECOND_PERCENT 50
    ORDER PERCENT_OF_HOLDING 100
    MAX_SLIPPAGE_PCT 1
    MISSING_HOLDING REJECT
    EXECUTE ONCE PER SYMBOL
}""",
        side="sell",
        strategy_type="Custom Query Sell",
        symbols=("EBL",),
    ),
    ValidQueryCase(
        "Q22",
        "Technical weakness custom SELL",
        """STRATEGY_VERSION 1
SIDE SELL
RULE "Technical Weakness Test" FOR SYMBOL "NABIL" {
    WHEN technical_macd CHANGED TO "Bearish" AND technical_rsi_14 < 45
    ORDER PERCENT_OF_HOLDING 25
    CONFIRM IMMEDIATE
    TRIGGER LEVEL
    MISSING_HOLDING REJECT
    EXECUTE ONCE
}""",
        side="sell",
        strategy_type="Custom Query Sell",
    ),
    ValidQueryCase(
        "Q23",
        "Trailing-runner functional SELL",
        """STRATEGY_VERSION 1
SIDE SELL
RULE "Trailing Runner Functional Test" FOR SYMBOL "NABIL" {
    WHEN highest_price_since_entry >= ltp * 1.03 AND profit_percent > 0
    ORDER PERCENT_OF_HOLDING 100
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    MISSING_HOLDING REJECT
    EXECUTE ONCE
}""",
        side="sell",
        strategy_type="Custom Query Sell",
    ),
    ValidQueryCase(
        "Q24",
        "Emergency top-buyer partial SELL",
        """STRATEGY_VERSION 1
SIDE SELL
RULE "Top Buyer Emergency Test" FOR SYMBOL "NABIL" {
    WHEN ltp > 0
    REQUIRE market_depth_available = TRUE AND top_buy_quantity >= 10 AND order_quantity_to_top_buy_ratio <= 1
    ORDER PARTIAL_TOP_BUY 10 PRICE TOP_BUY
    CONFIRM IMMEDIATE
    TRIGGER LEVEL
    MAX_SLIPPAGE_PCT 1
    MISSING_HOLDING REJECT
    EXECUTE ONCE
}""",
        side="sell",
        strategy_type="Custom Query Sell",
        covered_elsewhere=frozenset({"Q24"}),
    ),
    ValidQueryCase(
        "Q25",
        "Effective-stop SELL after protected entry",
        """STRATEGY_VERSION 1
SIDE SELL
RULE "Effective Stop Test" FOR SYMBOL "NABIL" {
    WHEN ltp <= effective_stop_price
    ORDER PERCENT_OF_HOLDING 100
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    MAX_SLIPPAGE_PCT 1
    MISSING_HOLDING WAITING_FOR_HOLDING
    EXECUTE ONCE
}""",
        side="sell",
        strategy_type="Custom Query Sell",
    ),
]

INVALID_QUERIES: List[InvalidQueryCase] = [
    InvalidQueryCase(
        "N01",
        "Unsupported ADX field",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Reject ADX" FOR SYMBOL "NABIL" {
    WHEN technical_adx > 25
    ORDER QUANTITY 10
    EXECUTE ONCE
}""",
        check="preflight",
        expect_codes=("unsupported_feature",),
        covered_elsewhere=frozenset({"N01"}),
    ),
    InvalidQueryCase(
        "N02",
        "Missing ORDER clause",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Reject Missing Order" FOR SYMBOL "NABIL" {
    WHEN ltp < 500
    EXECUTE ONCE
}""",
        check="validate",
        expect_codes=("MISSING_ORDER_SIZE",),
    ),
    InvalidQueryCase(
        "N03",
        "Missing required strategy parameter",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Reject Missing Target" FOR SYMBOL "NABIL" {
    USE STRATEGY "Fixed Price Buy"
    ORDER QUANTITY 10
    EXECUTE ONCE
}""",
        check="validate",
        expect_codes=("MISSING_STRATEGY_PARAM",),
    ),
    InvalidQueryCase(
        "N04",
        "Wrong-side delegated strategy",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Reject Wrong Side" FOR SYMBOL "NABIL" {
    USE STRATEGY "Capital Protection Sell"
    STOP_LOSS_PRICE 480
    ORDER QUANTITY 10
    EXECUTE ONCE
}""",
        check="validate",
        expect_codes=("STRATEGY_SIDE_MISMATCH", "UNKNOWN_STRATEGY"),
    ),
    InvalidQueryCase(
        "N05",
        "Unquoted function operator",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Reject Operator" FOR SYMBOL "NABIL" {
    WHEN DEPTH_QUANTITY(side="BUY", levels=3, operator=gte, threshold=1000)
    ORDER QUANTITY 10
    EXECUTE ONCE
}""",
        check="validate",
        expect_codes=("UNKNOWN_FIELD",),
    ),
    InvalidQueryCase(
        "N06",
        "Invalid enum casing",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Reject Enum" FOR SYMBOL "NABIL" {
    WHEN technical_macd = "bullish"
    ORDER QUANTITY 10
    EXECUTE ONCE
}""",
        check="runtime",
    ),
    InvalidQueryCase(
        "N07",
        "Preview-only percentile in scheduled order",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Reject Preview Function" FOR SYMBOL "NABIL" {
    WHEN UNIVERSE_PERCENTILE(field=volume, operator="gte", threshold=80)
    ORDER QUANTITY 10
    EXECUTE ONCE
}""",
        check="preflight",
        expect_codes=("unsupported_feature",),
        covered_elsewhere=frozenset({"N07"}),
    ),
    InvalidQueryCase(
        "N08",
        "Lowercase symbol",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Reject Lowercase Symbol" FOR SYMBOL "nabil" {
    WHEN ltp < 500
    ORDER QUANTITY 10
    EXECUTE ONCE
}""",
        check="parse",
    ),
    InvalidQueryCase(
        "N09",
        "Past Time-Based Buy expiry",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Reject Past Expiry" FOR SYMBOL "NABIL" {
    USE STRATEGY "Time-Based Buy"
    EXPIRY_TIME "2026-06-19T15:00"
    WRAPPED_STRATEGY "Quality Pullback Recovery Buy"
    ORDER QUANTITY 10
    EXECUTE ONCE
}""",
        check="validate",
        expect_codes=("EXPIRY_IN_PAST", "MISSING_STRATEGY_PARAM", "UNKNOWN_STRATEGY_PARAM"),
    ),
    InvalidQueryCase(
        "N10",
        "Semantic self-reference lint",
        """STRATEGY_VERSION 1
SIDE BUY
RULE "Reject Self Reference" FOR SYMBOL "NABIL" {
    WHEN ltp <= ltp * 0.90
    ORDER QUANTITY 10
    EXECUTE ONCE
}""",
        check="baseline",
    ),
]

ALL_VALID_IDS: Set[str] = {case.case_id for case in VALID_QUERIES}
ALL_INVALID_IDS: Set[str] = {case.case_id for case in INVALID_QUERIES}


def query_by_id(case_id: str) -> ValidQueryCase:
    for case in VALID_QUERIES:
        if case.case_id == case_id:
            return case
    raise KeyError(case_id)
