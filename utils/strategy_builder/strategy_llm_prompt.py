"""Copy-ready LLM prompt for Strategy Query Language authoring.

Field keys, enums, supported functions, and blocked indicators are assembled from the
same registries used by the parser, validator, preview service, and schedule preflight.
When adding fields or grammar rules, update those registries first — this prompt follows.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from utils.strategy_builder.constants import DEFAULT_RULE_ORDER_QUANTITY
from utils.strategy_builder.feature_registry import (
    RUNTIME_FUNCTIONS,
    UNSUPPORTED_DATA_FIELDS,
    classify_field,
)
from utils.strategy_builder.strategy_fields import ENUM_VALUES, SUPPORTED_FUNCTIONS, get_field_catalog

_PROMPT_FIELD_CATEGORIES = {
    "technical",
    "fundamental",
    "statistical",
    "sector",
    "live",
    "derived_live",
    "derived_statistical",
    "market_depth",
    "liquidity",
    "position",
}


def supported_catalog_fields() -> List[dict]:
    supported: List[dict] = []
    for field in get_field_catalog():
        key = str(field.get("key") or "")
        if not key or classify_field(key) != "SUPPORTED_RUNTIME":
            continue
        category = str(field.get("category") or "other")
        if category not in _PROMPT_FIELD_CATEGORIES:
            continue
        supported.append(field)
    return supported


def _field_registry_section() -> str:
    by_category: Dict[str, List[str]] = {}
    for field in supported_catalog_fields():
        category = str(field.get("category") or "other")
        nullable = "nullable" if field.get("nullable") else "required"
        history = ", history" if field.get("supports_history") else ""
        by_category.setdefault(category, []).append(
            f"- {field['key']}: {field.get('label', field['key'])} ({field.get('data_type', 'unknown')}, {nullable}{history})"
        )
    category_labels = {
        "technical": "NEPSE ALPHA TECHNICALS",
        "fundamental": "NEPSE ALPHA FUNDAMENTALS",
        "statistical": "NEPSE ALPHA STATISTICS",
        "sector": "NEPSE ALPHA SECTOR",
        "live": "TMS LIVE QUOTE",
        "derived_live": "DERIVED LIVE (from TMS quote)",
        "derived_statistical": "DERIVED STATISTICAL (TMS LTP + Nepse Alpha 52w range)",
        "market_depth": "TMS MARKET DEPTH (from stock quote topBuy/topSell)",
        "liquidity": "DERIVED MARKET DEPTH / LIQUIDITY",
        "position": "POSITION STATE (after entry)",
    }
    sections: List[str] = []
    for category in (
        "technical",
        "fundamental",
        "statistical",
        "sector",
        "live",
        "derived_live",
        "derived_statistical",
        "market_depth",
        "liquidity",
        "position",
    ):
        lines = by_category.get(category)
        if not lines:
            continue
        label = category_labels.get(category, category.upper())
        sections.append(f"{label}:\n" + "\n".join(lines))
    return "\n\n".join(sections)


def _enum_section() -> str:
    lines = [f"- {key}: {', '.join(repr(v) for v in values)}" for key, values in sorted(ENUM_VALUES.items())]
    return "\n".join(lines) if lines else "- (none)"


def _function_section() -> str:
    catalog = {item["name"].upper(): item for item in SUPPORTED_FUNCTIONS}
    lines: List[str] = []
    for name in sorted(RUNTIME_FUNCTIONS):
        meta = catalog.get(name, {})
        description = meta.get("description") or "Supported runtime function"
        lines.append(f"- {name}: {description}")
    return "\n".join(lines)


def _forbidden_section() -> str:
    blocked_fields = sorted(UNSUPPORTED_DATA_FIELDS)
    return (
        "FORBIDDEN — never use these in a query and never suggest them as alternatives:\n"
        "Fields:\n"
        + "\n".join(f"- {item}" for item in blocked_fields)
        + "\nFunctions:\n"
        "- (none currently beyond unregistered/custom functions)\n"
        + "\nOther blocked indicators: any custom indicator not in FIELD REGISTRY. Registered local OHLCV indicators such as technical_adx_14 are supported.\n"
        "Market depth is available only through registered stock quote fields/functions; do not invent unlisted depth names."
    )


def _unsupported_section() -> str:
    return (
        f"{_forbidden_section()}\n\n"
        "Also blocked: any field or function not listed in FIELD REGISTRY or SUPPORTED FUNCTIONS below.\n"
        "Ranking functions UNIVERSE_PERCENTILE and SECTOR_PERCENTILE parse for preview but cannot be scheduled "
        "for single-symbol monitored orders."
    )


def _response_format_section(*, side: str) -> str:
    side_upper = (side or "buy").upper()
    return f"""RESPONSE FORMAT — single-pass: produce the safest valid answer on the first reply.

Decision path:
1. If the user gave enough concrete inputs for at least one valid rule, return STATUS: OK.
2. If part of the request is unsupported but a registered substitute can still express the main intent, return STATUS: OK and name the substitution in Summary.
3. Return STATUS: ERROR only when SIDE is wrong, quantity/holding mode is missing for SELL, or no valid rule/condition can be built.
4. If the user asks for "top N", "best N", "N stocks", or a basket, first look for an "Available symbol universe" or pasted symbols in the user message. Use those symbols with FOR SYMBOL IN (...) and RANK MATCHES BY ... LIMIT N ORDERS. Only fall back to the current form symbol for clearly single-symbol requests.

When the request CAN be satisfied or approximated (default — use this whenever possible):
STATUS: OK
Summary:
- 2-4 bullets: what the rule does, key filters, execution mode
- Limitation: (required when you dropped, substituted, or could not match part of the request) We don't have <missing>; this plan uses <substitute> — close, not exact.
Query:
```
STRATEGY_VERSION 1
SIDE {side_upper}
...
```

When the request CANNOT be satisfied at all (only these cases):
STATUS: ERROR
Reason:
- Start with: This query is not supported —
- Use only for wrong SIDE, missing SELL quantity/holding mode, or no parseable trading rule/condition at all
- Do not return ERROR only because the user requested multiple/top N stocks. If the user message contains an available symbol universe, use it. If no universe exists, produce a clear single-symbol fallback with a Limitation bullet rather than pretending it is true market-wide top-N.
Do NOT include a Query block when STATUS is ERROR.

Parsing rules:
- Output exactly one STATUS block per turn.
- Prefer STATUS: OK with a registered substitute over STATUS: ERROR when the user asked for an unsupported indicator/field.
- Put Strategy Query Language only inside the Query fenced block on STATUS: OK."""


def _strict_output_contract_section() -> str:
    return """STRICT OUTPUT CONTRACT — this is the final gate before answering:
1. Always start with STATUS: OK or STATUS: ERROR (see RESPONSE FORMAT). Never answer with only a refusal sentence.
2. On STATUS: OK, the Query block must contain a complete Strategy Query Language document starting with STRATEGY_VERSION 1 and SIDE BUY or SIDE SELL.
3. On STATUS: ERROR, include Reason bullets only — no Query block, no STRATEGY_VERSION document.
4. Do not output JSON, YAML, SQL, Python, or commentary outside the STATUS wrapper.
5. Do not output placeholders such as <symbol>, SYMBOL, YOUR_SYMBOL, target_price, trigger_price, quantity, or TODO.
6. Do not guess missing numbers, timestamps, holdings, or quantities. Every RULE must include explicit ORDER sizing and explicit FOR SYMBOL target(s).
7. Use only exact uppercase quoted script symbols. For top-N requests, prefer an available symbol universe or user-supplied symbols over the current form symbol. Use a single fallback symbol only when no universe exists and say it is not true market-wide top-N.
8. Use only exact field keys from FIELD REGISTRY. Field keys are lowercase snake_case and case-sensitive.
9. Use only exact function names from SUPPORTED FUNCTIONS. Function names are uppercase and case-sensitive.
10. Function arguments must be named. Operator argument values must be quoted strings: operator="gte", not operator=gte.
11. Enum values must match ENUM TEXT VALUES exactly, including case, e.g. "Bullish", "Bearish", "above", "below".
12. Substitute registered alternatives for unsupported requests when possible; note gaps in a Limitation Summary bullet — do not fail just because one requested indicator is missing.
13. Before answering, verify every field/function in the Query block appears in FIELD REGISTRY or SUPPORTED FUNCTIONS, every string enum is quoted, and every RULE has FOR SYMBOL plus ORDER."""


def _hard_rules_section() -> str:
    return """HARD RULES — follow without exception:
1. Use ONLY field keys from FIELD REGISTRY and functions from SUPPORTED FUNCTIONS in the Query block.
2. If the user asks for an unlisted indicator/field/function:
   - Prefer STATUS: OK with the closest registered substitute that preserves the trading intent (e.g. technical_rsi_14, technical_macd, volatility, or technical_volume_trend).
   - Add a Limitation Summary bullet: We don't have <name>; used <substitute> — close, not exact.
   - Use STATUS: ERROR only if no reasonable substitute exists and no valid rule can be built.
3. Never invent field names, SQL, Python, or indicators outside the registries.
4. Every RULE must declare FOR SYMBOL targets and include ORDER sizing.
5. A RULE must include at least one of: USE STRATEGY "...", WHEN <expr>, or ELIGIBILITY + SIGNAL.
6. USE STRATEGY may combine with optional ELIGIBILITY / WHEN / SIGNAL / REQUIRE gates (gates run first).
7. Never nest Custom Query / Technical Buy/Sell inside USE STRATEGY — those are rule-based types, not delegatable.
8. Symbols must be exact uppercase NEPSE/TMS script codes in double quotes. Prefer symbols the user explicitly pasted or the current form symbol; use "CZBIL" only as a fallback when no symbol context exists.
9. Multi-symbol/top-N requests: when symbols or an available symbol universe are present, use FOR SYMBOL IN (...) and add RANK MATCHES BY <field> DESC LIMIT <N> ORDERS. When no universe is present, do not claim the query finds N market-wide stocks; use the current/fallback symbol and add a Limitation bullet.
10. Do not refuse with vague errors. Name the real blocker or give the closest valid query with a Limitation bullet.
11. Use quoted operator strings inside function calls: operator="gte" / "lte" / "gt" / "lt" / "eq" / "neq".
12. Use positive numeric literals only; do not write negative numbers like -3. Prefer equivalent comparisons such as field < 0.
13. SELL queries must stay within the user's sellable DP holdings. If the user has not provided a sell quantity, holding quantity, ALL_AVAILABLE instruction, or percent-of-holding instruction, return STATUS: ERROR; do not invent a sell amount.
14. Single-pass: aim to return STATUS: OK with the best query on the first reply. Follow RESPONSE FORMAT every time.
15. Final self-check before output: remove any unsupported requested part instead of inventing syntax; if removal changes the intent, mention it in a Limitation bullet. Never answer with "paste the symbols" when a valid current-symbol query can be produced."""


def _data_sources_section() -> str:
    return """DATA SOURCES (only these are available at runtime):

1. Nepse Alpha technicals — e.g. technical_rsi_14, technical_macd, technical_sma_20, technical_volume_trend
2. Nepse Alpha fundamentals — e.g. fundamental_pbv, fundamental_roe_ttm, fundamental_eps_ttm
3. Nepse Alpha statistics — e.g. fifty_two_week_high, fifty_two_week_low, alpha, beta, volatility
4. Nepse Alpha sector — e.g. ltp_sector_high, volume_sector_low
5. TMS live quote — ltp, open, high, low, volume, previous_close, change, change_percent, last_traded_at
6. Derived live — computed from TMS quote: distance_from_day_high_percent, opening_gap_percent,
   position_in_intraday_range_percent, intraday_range_percent, etc.
7. TMS market depth — computed from stock_quote topBuy/topSell: market_depth_available, best_bid, best_ask,
   spread, spread_percent, top_buy_quantity, top_sell_quantity, total_buy_quantity, total_sell_quantity,
   buy_sell_quantity_ratio, order_book_imbalance, and DEPTH_* functions.
8. Derived statistical — computed from TMS LTP + Nepse 52w range: position_in_52_week_range_percent,
   distance_from_52_week_high_percent, distance_from_52_week_low_percent, etc.
9. Position state — after a buy entry: profit_percent, effective_stop_price, drawdown_from_peak_percent, etc.

NOT available: unregistered indicators or raw order-book level fields outside the registered depth fields/functions. ADX is available as technical_adx_14."""


def _scheduling_preflight_section() -> str:
    return f"""Before a monitored (rule-based) order is scheduled, the portal runs preflight checks.
A query that parses but cannot be monitored will NOT be placed. Preflight requires:

1. Parser + validator pass (only registered, supported fields/functions; SIDE must match portal side).
   Queries using ADX or other blocked/unregistered fields/functions are rejected immediately.
2. TMS client selected and logged in (monitoring needs an active TMS session).
3. Nepse Alpha direct fields: every symbol in FOR SYMBOL / FOR SYMBOL IN (...) must have Nepse Alpha data
   for each technical_*, fundamental_*, statistical_*, or sector_* field used in ELIGIBILITY, SIGNAL, REQUIRE,
   or WHEN. If Nepse Alpha is down or a direct field is null for that symbol, scheduling is blocked
   with a message naming the symbol and missing fields.
4. Derived statistical fields (e.g. position_in_52_week_range_percent): computed from live TMS LTP plus
   Nepse Alpha fifty_two_week_high / fifty_two_week_low. Preflight blocks scheduling when either 52-week
   endpoint is missing for any targeted symbol, naming the symbol and missing prerequisite.
   When both 52-week values exist, scheduling must proceed without a 52-week warning.
5. TMS live quote and market depth: if the query uses live, derived-live, or market-depth fields/functions
   (ltp, volume, open, high, low, change_percent, distance_from_day_high_percent, market_depth_available,
   best_bid, top_buy_quantity, DEPTH_QUANTITY, etc.), preflight fetches a live TMS quote for each symbol.
   Missing quote blocks scheduling. Queries that use market-depth fields/functions (DEPTH_IMBALANCE,
   market_depth_available, TOP_BUY/TOP_SELL order modes, etc.) are blocked when TMS depth is unavailable.

When writing queries:
- Prefer fields you can see in the FIELD REGISTRY below.
- For multi-symbol rules, every symbol must pass data checks independently.
- If the user asks for data the portal cannot supply, use a registered substitute when it still gives a useful strategy; otherwise return STATUS: ERROR and explain what is missing.
- For "top N" or "N stocks" requests, prefer RANK MATCHES BY with LIMIT N ORDERS plus the strongest valid rule filters. Do not stop with a symbol-list refusal when a current-symbol or ranked query can be generated.
- Every RULE must include explicit ORDER sizing (for example ORDER QUANTITY 10). Do not omit ORDER.
- Per-symbol different classic strategies: use separate RULE blocks (one USE STRATEGY per symbol or per symbol group).

USE STRATEGY preflight notes:
- Delegated strategies run only after optional ELIGIBILITY / WHEN / SIGNAL / REQUIRE gates pass.
- Strategies marked requires Nepse Alpha (Quality Pullback, Mean Reversion, Technical Weakness) need Nepse Alpha at runtime.
- Order Book Strength Buy requires live market depth at runtime. Custom query conditions can also use registered
  market-depth fields/functions from the TMS stock quote.
- SELL delegated strategies require sellable DP holdings for the symbol.
- Strategy params (TARGET_PRICE, STOP_LOSS_PRICE, EXPIRY_TIME, etc.) are validated at parse/schedule time — include all required * params.
- Time-Based Buy EXPIRY_TIME must be in the future at schedule time; past expiry is rejected.

Schedule-time field references (preferred for pullback / fixed baseline rules):
- Use REFERENCE(field=<registered_field>) to snapshot a field value once at schedule time.
- CORRECT: WHEN ltp <= REFERENCE(field=ltp) * 0.90
- CORRECT: WHEN ltp <= REFERENCE(field=ltp) - 50
- INCORRECT: WHEN ltp <= ltp * 0.90 (self-referential live comparison)
- INCORRECT: WHEN ltp <= trigger_price (trigger_price is not a registered field; use REFERENCE)
- Live ltp (and other live fields) stay dynamic on every scan; REFERENCE(field=...) stays fixed until explicitly refreshed.
- Do NOT guess numeric LTP, symbols, quantities, or expiration timestamps.
- Expiration (expires_at, expiration_action) is configured outside the query in schedule settings, not with EXPIRES_AT query syntax.
- SELL schedules should not guess quantity. If the user does not tell you the sellable holding amount, use STATUS: ERROR unless they explicitly requested all-available or percent-of-holding.

Legacy schedule-time drop baseline (older orders only):
- Some existing orders use capture_reference_ltp with literal compiled triggers; new queries should prefer REFERENCE(field=ltp) instead."""


def _buy_sizing_modes() -> str:
    return (
        "QUANTITY, AMOUNT, PERCENT_OF_AVAILABLE_CASH, TARGET_POSITION_VALUE, "
        "RISK_PERCENT, MAX_LOSS_AMOUNT, FROM_FORM, PER SYMBOL"
    )


def _sell_sizing_modes() -> str:
    return "QUANTITY, PERCENT_OF_HOLDING, ALL_AVAILABLE, SELL_UP_TO, FROM_FORM, PER SYMBOL"


def _strategy_param_glossary_section() -> str:
    from utils.strategies.strategy_query_catalog import QUERY_PARAM_ALIASES, get_strategy_param_glossary

    lines = [
        "Strategy parameter clauses (place after USE STRATEGY, before ORDER):",
        "- Numbers: PARAM_NAME 532",
        "- Strings: WRAPPED_STRATEGY \"Quality Pullback Recovery Buy\"",
        "- Booleans: EMERGENCY_CONFIRMED TRUE | REQUIRE_VOLUME_INCREASE FALSE",
        "- Datetime (Nepal local): EXPIRY_TIME \"2026-06-20T15:00\"",
        "",
        "Parameter glossary (* = required for at least one strategy):",
    ]
    for item in get_strategy_param_glossary():
        aliases = item.get("aliases") or []
        alias_text = f" (aliases: {', '.join(aliases)})" if aliases else ""
        lines.append(
            f"- {item['query_name']} [{item['type']}]{alias_text}: {item['label']}"
        )
    if QUERY_PARAM_ALIASES:
        lines.append("")
        lines.append("Name aliases accepted in queries:")
        for alias, canonical in sorted(QUERY_PARAM_ALIASES.items()):
            lines.append(f"- {alias} → {canonical}")
    return "\n".join(lines)


def _strategy_delegation_section(*, side: str = "buy") -> str:
    from utils.strategies.strategy_query_catalog import DELEGATABLE_STRATEGIES, RULE_BASED_STRATEGIES, get_delegatable_strategies

    lines = [
        "Named portal strategies (USE STRATEGY):",
        "- Each RULE may delegate to one classic TMS strategy instead of encoding all logic in WHEN.",
        "- Combine mode: optional ELIGIBILITY / WHEN / SIGNAL / REQUIRE gates run first; named strategy runs only if gates pass.",
        "- One Custom Query order can mix rules — different USE STRATEGY per symbol.",
        "- Syntax (params before ORDER, gates optional):",
        '  USE STRATEGY "Fixed Price Buy"',
        "  TARGET_PRICE 532",
        "  ELIGIBILITY technical_rsi_14 BETWEEN 30 AND 50   # optional gate",
        "  ORDER QUANTITY 100",
        "  EXECUTE ONCE PER SYMBOL",
        "",
        "NOT delegatable (never use with USE STRATEGY):",
        f"  {', '.join(sorted(RULE_BASED_STRATEGIES))}",
        "",
        f"Delegatable strategies for SIDE {side.upper()} ({len(get_delegatable_strategies(side))} total, {len(DELEGATABLE_STRATEGIES)} all sides):",
    ]
    for entry in get_delegatable_strategies(side):
        params = ", ".join(
            f"{item['query_name']}{'*' if item['required'] else ''}"
            for item in entry.get("params") or []
        )
        param_suffix = f" ({params})" if params else " (no extra params)"
        flags = []
        if entry.get("requires_nepse_alpha"):
            flags.append("Nepse Alpha")
        if entry.get("requires_market_depth"):
            flags.append("market depth")
        if entry.get("requires_holdings"):
            flags.append("holdings")
        flag_suffix = f" [needs: {', '.join(flags)}]" if flags else ""
        lines.append(f"- {entry['name']}{param_suffix}{flag_suffix}")
        lines.append(f"  {entry['purpose']}")
        if entry.get("aliases"):
            lines.append(f"  Aliases: {', '.join(entry['aliases'])}")
    lines.extend(
        [
            "",
            _strategy_param_glossary_section(),
            "",
            "Examples:",
            "",
            "Example A — strategy only (no extra gates):",
            'RULE "NABIL Fixed" FOR SYMBOL "NABIL" {',
            '    USE STRATEGY "Fixed Price Buy"',
            "    TARGET_PRICE 532",
            "    ORDER QUANTITY 100",
            "    EXECUTE ONCE PER SYMBOL",
            "}",
            "",
            "Example B — combine gate + strategy:",
            'RULE "EBL Quality" FOR SYMBOL "EBL" {',
            '    USE STRATEGY "Quality Pullback Recovery Buy"',
            "    MIN_BUY_SCORE 65",
            "    ELIGIBILITY technical_rsi_14 BETWEEN 30 AND 50",
            "    ORDER QUANTITY 50",
            "    EXECUTE ONCE PER SYMBOL",
            "}",
            "",
            "Example C — multi-stock, different strategy per symbol:",
            "STRATEGY_VERSION 1",
            "SIDE BUY",
            'RULE "NABIL Fixed" FOR SYMBOL "NABIL" {',
            '    USE STRATEGY "Fixed Price Buy"',
            "    TARGET_PRICE 532",
            "    ORDER QUANTITY 100",
            "    EXECUTE ONCE PER SYMBOL",
            "}",
            'RULE "EBL Breakout" FOR SYMBOL "EBL" {',
            '    USE STRATEGY "Confirmed Breakout Buy"',
            "    TARGET_PRICE 720",
            "    ORDER QUANTITY 50",
            "    EXECUTE ONCE PER SYMBOL",
            "}",
        ]
    )
    if side.lower() == "sell":
        lines.extend(
            [
                "",
                "Example D — sell protection:",
                'RULE "NABIL Protect" FOR SYMBOL "NABIL" {',
                '    USE STRATEGY "Capital Protection Sell"',
                "    STOP_LOSS_PRICE 480",
                "    TRAILING_DROP_PCT 3",
                "    ORDER PERCENT_OF_HOLDING 100",
                "    EXECUTE ONCE PER SYMBOL",
                "}",
                "",
                "Example E — profit ladder with gate:",
                'RULE "EBL Ladder" FOR SYMBOL "EBL" {',
                '    USE STRATEGY "Profit Ladder Sell"',
                "    FIRST_TARGET 720",
                "    FIRST_PERCENT 50",
                "    SECOND_TARGET 780",
                "    SECOND_PERCENT 50",
                "    ELIGIBILITY ltp > entry_price",
                "    ORDER PERCENT_OF_HOLDING 100",
                "    EXECUTE ONCE PER SYMBOL",
                "}",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Example D — REFERENCE pullback + gate + fixed price:",
                'RULE "Pullback Ref" FOR SYMBOL "NABIL" {',
                "    ELIGIBILITY ltp <= REFERENCE(field=ltp) * 0.90",
                '    USE STRATEGY "Smart Pullback Buy"',
                "    TARGET_PRICE 500",
                "    ORDER QUANTITY 100",
                "    EXECUTE ONCE PER SYMBOL",
                "}",
            ]
        )
    return "\n".join(lines)


def _compact_field_key_list() -> str:
    keys = [str(field.get("key")) for field in supported_catalog_fields() if field.get("key")]
    return ", ".join(sorted(keys))


def _compact_function_list() -> str:
    return ", ".join(sorted(RUNTIME_FUNCTIONS))


def _copy_prompt_current_symbol(side_upper: str, form_symbol: Optional[str]) -> str:
    symbol = (form_symbol or "CZBIL").upper()
    if form_symbol:
        return (
            f'The current order form symbol is "{symbol}". Use it for single-symbol order rules when the user does not provide another symbol.'
        )
    return (
        "No form symbol was provided in this copied prompt. For order rules, use CZBIL only as an example "
        "single-symbol target and mention that the user should replace it or provide a symbol universe."
    )


def build_strategy_query_copy_prompt(*, side: str = "buy", form_symbol: Optional[str] = None) -> str:
    """Compact external prompt meant for copying into ChatGPT."""

    side_upper = (side or "buy").upper()
    sizing = _buy_sizing_modes() if side_upper == "BUY" else _sell_sizing_modes()
    current_symbol_note = _copy_prompt_current_symbol(side_upper, form_symbol)

    return f"""You generate Strategy Query Language for a Nepal TMS automation portal.
The user will paste a plain-English trading request after this prompt.

Your job: return the closest valid query in one shot and clearly choose the right query type.

Output format:
STATUS: OK
Summary:
- 2-4 short bullets explaining the rule
- Limitation: only if you had to approximate something
Query:
```
STRATEGY_VERSION 1
SIDE {side_upper}
...
```

Avoid STATUS: ERROR. If the request is unclear, return a useful default with a Limitation bullet.

Choose the right query type:
- Screener query discovers/ranks stocks across the market. Use it for "top N", "best N", "good N stocks", or "N NEPSE stocks" when no symbol universe is provided.
- Strategy Query Language schedules/monitors orders. It can rank only the symbols already listed in `FOR SYMBOL IN (...)`; `RANK MATCHES BY ... LIMIT N ORDERS` does not discover symbols by itself.
- If the user asks for true top-N NEPSE discovery without symbols, return a SCREENER query, not a fake single-symbol strategy.
- If the user provides symbols, or asks about the current form symbol, return Strategy Query Language.

Strategy symbol behavior:
- Every Strategy RULE needs `FOR SYMBOL` or `FOR SYMBOL IN`.
- {current_symbol_note}
- If the user does provide uppercase symbols, use `FOR SYMBOL IN ("NABIL", "EBL")`.
- If the user asks for top-N orders and also provides a symbol universe, use `FOR SYMBOL IN (...)` with those symbols and add `RANK MATCHES BY <field> DESC LIMIT N ORDERS`.
- If the user does not specify quantity, use `ORDER QUANTITY {DEFAULT_RULE_ORDER_QUANTITY}`.
- Use only the field keys and functions listed below. If a requested indicator is missing, use the closest available field and mention it in Limitation.
- Never output SQL, Python, JSON, placeholders, or invented field names.

Strategy Query Language syntax:
```
STRATEGY_VERSION 1
SIDE {side_upper}
RULE "Trading Quality Buy" FOR SYMBOL "{(form_symbol or "CZBIL").upper()}" {{
    ELIGIBILITY volume > 0
    SIGNAL technical_rsi_14 BETWEEN 30 AND 55 AND technical_macd = "Bullish"
    REQUIRE market_depth_available = TRUE
    ORDER QUANTITY {DEFAULT_RULE_ORDER_QUANTITY}
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    EXECUTE ONCE
}}
```

Rule syntax:
- `RULE "Name" FOR SYMBOL "CZBIL" {{ ... }}`
- `RULE "Name" FOR SYMBOL IN ("CZBIL", "NABIL") {{ ... }}`
- Conditions: `WHEN <expr>` or `ELIGIBILITY <expr>` + `SIGNAL <expr>` with optional `REQUIRE <expr>`
- Comparisons: `= != > >= < <=`, `BETWEEN a AND b`, `IN (...)`
- Logic: `AND`, `OR`, `NOT`, parentheses
- Confirmation: `CONFIRM IMMEDIATE`, `CONFIRM TRUE_FOR 2 SCANS`, `CONFIRM MATCHES 2 OF LAST 3 SCANS`
- Trigger: `TRIGGER LEVEL` or `TRIGGER ON_CROSS`
- Execution: `EXECUTE ONCE`, `EXECUTE ONCE PER SYMBOL`, `EXECUTE ONCE PER MARKET DAY`
- Order sizing for SIDE {side_upper}: {sizing}

Screener query syntax:
- Use only screener field keys shown in the screener page prompt when available.
- Common shape:
```
WHERE technical_rsi_14 BETWEEN 30 AND 55
  AND technical_macd = 'Bullish'
ORDER BY alpha_annualized DESC
LIMIT 50
```
- If exact screener fields are not listed in this prompt, still output a simple screener query and add a Limitation saying it must be checked against the screener field list.

Useful BUY fields:
- quality/fundamental: fundamental_roe_ttm, fundamental_eps_ttm, fundamental_pbv, fundamental_pe_ttm
- technical: technical_rsi_14, technical_macd, technical_sma_20, technical_sma_50, technical_volume_trend
- live/liquidity: ltp, open, high, low, volume, change_percent, market_depth_available, spread_percent, top_buy_quantity, top_sell_quantity, buy_sell_quantity_ratio
- range/risk: position_in_52_week_range_percent, distance_from_52_week_high_percent, distance_from_52_week_low_percent, volatility_risk_score

Available field keys:
{_compact_field_key_list()}

Available functions:
{_compact_function_list()}

Examples:

True top 50 NEPSE discovery when no symbols are provided (SCREENER query):
STATUS: OK
Summary:
- Screens for liquid bullish trading candidates.
- Ranks the market and returns 50 rows.
- Limitation: This is a screener query for discovery, not an order-scheduling Strategy Query Language document.
Query:
```
WHERE technical_rsi_14 BETWEEN 30 AND 55
  AND technical_macd = 'Bullish'
ORDER BY alpha_annualized DESC
LIMIT 50
```

Top 50 orders from an explicit symbol universe (Strategy Query Language):
```
STRATEGY_VERSION 1
SIDE BUY
RANK MATCHES BY volume DESC, buy_sell_quantity_ratio DESC LIMIT 50 ORDERS
RULE "Top Trading Quality" FOR SYMBOL IN ("NABIL", "EBL", "GBIME") {{
    ELIGIBILITY volume > 0 AND technical_rsi_14 BETWEEN 30 AND 55
    SIGNAL technical_macd = "Bullish" AND ltp >= open
    REQUIRE market_depth_available = TRUE
    ORDER QUANTITY {DEFAULT_RULE_ORDER_QUANTITY}
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    EXECUTE ONCE
}}
```

Pullback buy:
```
STRATEGY_VERSION 1
SIDE BUY
RULE "Pullback Buy" FOR SYMBOL "{(form_symbol or "CZBIL").upper()}" {{
    ELIGIBILITY ltp <= REFERENCE(field=ltp) * 0.95
    SIGNAL technical_rsi_14 BETWEEN 30 AND 45 AND technical_macd = "Bullish"
    ORDER QUANTITY {DEFAULT_RULE_ORDER_QUANTITY}
    EXECUTE ONCE
}}
```

Now answer the user's request using only STATUS + Summary + Query.
User request:
[PASTE REQUEST HERE]"""


def build_strategy_query_llm_prompt(*, side: str = "buy", form_symbol: Optional[str] = None) -> str:
    side_upper = (side or "buy").upper()
    sizing = _buy_sizing_modes() if side_upper == "BUY" else _sell_sizing_modes()

    form_note = ""
    if form_symbol:
        form_note = (
            f"\nThe user's order form currently shows symbol {form_symbol.upper()}. "
            "Every rule must still declare explicit FOR SYMBOL targets inside the query."
        )

    return f"""You are writing a Strategy Query Language plan for the Nepal TMS automation portal.
This is NOT SQL, NOT Python, and NOT JSON. Never use SELECT, INSERT, JOIN, eval, or markdown inside the query.

This prompt is generated from the live field/function/strategy registries shared with the parser, validator,
preview, and schedule preflight — use only keys listed in FIELD REGISTRY, SUPPORTED FUNCTIONS, and USE STRATEGY catalog.

Goal: produce a valid STRATEGY_VERSION 1 query for SIDE {side_upper}.{form_note}

================================================================================
RESPONSE FORMAT (mandatory — copy this shape exactly)
================================================================================
{_response_format_section(side=side_upper)}

================================================================================
STRICT OUTPUT CONTRACT
================================================================================
{_strict_output_contract_section()}

================================================================================
HARD RULES
================================================================================
{_hard_rules_section()}

================================================================================
DOCUMENT STRUCTURE (top to bottom)
================================================================================
STRATEGY_VERSION 1
SIDE {side_upper}

Optional global blocks (0 or 1 each):
- POSITION_PROTECTION {{ FIXED_STOP_LOSS_PRICE <n> | TRAILING_STOP_PCT <n> }}
- POSITION_EXIT {{ sell / stop-management actions — SELL side only }}
- RANK MATCHES BY <field> [ASC|DESC] [, <field> ...] [LIMIT <n> ORDERS]

Then one or more RULE blocks. Each RULE is independent and evaluated per symbol per scan.

================================================================================
RULE BLOCK (required shape)
================================================================================
RULE "Descriptive name" FOR SYMBOL "CZBIL" {{
    [USE STRATEGY "Fixed Price Buy"]
    [TARGET_PRICE <n> | STOP_LOSS_PRICE <n> | ... strategy params ...]
    [ELIGIBILITY <expr>]
    [SIGNAL <expr>]
    [REQUIRE <expr>]
    WHEN <expr>                    # use WHEN alone, or ELIGIBILITY+SIGNAL instead of WHEN
    ORDER <mode> <value>           # required
    [CONFIRM TRUE_FOR <n> SCANS | MATCHES <n> OF LAST <m> SCANS | IMMEDIATE]
    [TRIGGER ON_CROSS | TRIGGER LEVEL]
    [MAX_SLIPPAGE_PCT <n>]
    [MAX_DATA_AGE <n> SECONDS]
    [MISSING_HOLDING WARN_AND_SKIP|WAITING_FOR_HOLDING|REJECT]   # SELL only
    [COOLDOWN <n> MINUTES]
    [EXECUTE ONCE | ONCE PER SYMBOL | ONCE PER MARKET DAY | MAX <n> TIMES [PER SYMBOL]]
}}

Multi-symbol same rule:
RULE "Name" FOR SYMBOL IN ("CZBIL", "NABIL", "GBIME") {{ ... }}

Every RULE must include:
1. FOR SYMBOL "X" or FOR SYMBOL IN (...)
2. At least one condition via WHEN, ELIGIBILITY + SIGNAL, or USE STRATEGY (REQUIRE optional)
3. ORDER sizing ({sizing})

================================================================================
USE STRATEGY (named portal strategies)
================================================================================
{_strategy_delegation_section(side=side)}

================================================================================
CONDITION SYNTAX
================================================================================
Comparisons: = != > >= < <=
Logic: AND OR NOT and parentheses
Ranges: field BETWEEN a AND b | field NOT BETWEEN a AND b
Sets: field IN (a, b) | field NOT IN (a, b)
Text: field CONTAINS "text" | field NOT CONTAINS "text"
Availability: field IS AVAILABLE | field IS NOT AVAILABLE | field IS NULL | field IS NOT NULL
Enum transitions:
- field CHANGED TO "value"
- field CHANGED FROM "old" TO "new"
Boolean literals: TRUE | FALSE (e.g. REQUIRE volume > 0)
Arithmetic: + - * / on numbers and fields (e.g. ltp * 1.05 > open)

Function calls — ALWAYS use named arguments:
- CONSECUTIVE_DROPS(field=ltp, count=2, min_each_change_pct=0.25, min_total_change_pct=1)
- CONSECUTIVE_RISES(field=ltp, count=2, min_total_change_pct=1)
- CROSSES_ABOVE(field=ltp, threshold=500)
- CROSSES_BELOW(field=ltp, threshold=450)
- REMAINS_ABOVE(field=ltp, value=500, scans=2)
- REMAINS_BELOW(field=ltp, value=450, scans=2)
- PREVIOUS(field=ltp, offset=1)
- CHANGE(field=ltp, scans_back=2)
- CHANGE_PERCENT(field=ltp, scans_back=2)
- CHANGED_TO(field=technical_macd, value="Bullish")
- CHANGED_FROM_TO(field=technical_macd, from_value="Bearish", to_value="Bullish")
- AVERAGE(field=ltp, window=5) | MIN_VALUE | MAX_VALUE | SUM_VALUE | STDDEV | SLOPE | TREND
- REFERENCE(field=<registered_field>) — schedule-time snapshot; stays fixed until refresh
- REFERENCE(field=ltp) * 0.90 — compare live LTP to 90% of captured schedule-time LTP
- DEPTH_QUANTITY(side="BUY", levels=3, operator="gte", threshold=1000)
- DEPTH_ORDER_COUNT(side="SELL", levels=3, operator="gte", threshold=2)
- DEPTH_IMBALANCE(levels=2, operator="gte", threshold=0.2)
- DEPTH_IMBALANCE_REMAINS_ABOVE(levels=2, threshold=0.2, scans=2)
- DEPTH_PRESSURE_TREND(levels=3, scans=3, value="BUYING")
- SPREAD_REMAINS_BELOW(threshold=0.5, scans=2)
- SECTOR_POSITION(field=ltp, operator="gte", threshold=80)
- UNIVERSE_PERCENTILE(field=volume, operator="gte", threshold=80)   # preview only — not schedulable
- SECTOR_PERCENTILE(field=change_percent, operator="gte", threshold=70)   # preview only — not schedulable

Do NOT use positional-only function args like CONSECUTIVE_RISES(ltp, count=2).
Depth functions must use named args and registered names only; use top_buy_quantity/top_sell_quantity for top-level qty checks.
Operator args inside functions must be quoted strings, e.g. operator="gte". Unquoted operator=gte is parsed as a field and is invalid.

================================================================================
ORDER SIZING MODES (SIDE {side_upper})
================================================================================
{sizing}

Notes:
- ORDER QUANTITY 100 — fixed shares
- If the user does not specify quantity, omit ORDER QUANTITY; runtime default is {DEFAULT_RULE_ORDER_QUANTITY} kitta
- ORDER AMOUNT 50000 — rupee budget at LTP
- ORDER QUANTITY FROM_FORM — use scheduled form quantity
- ORDER RISK_PERCENT 1 — risk % of available cash (needs stop distance)
- ORDER MAX_LOSS_AMOUNT 5000 — cap loss in rupees
- ORDER ALL_AVAILABLE — sell entire holding (SELL)
- ORDER PERCENT_OF_HOLDING 50 — partial sell (SELL)
- ORDER SELL_UP_TO 200 — sell up to N shares (SELL)
- ORDER PRICE TOP_BUY | TOP_SELL | LTP | BEST_BID | BEST_ASK — execution limit price from live depth
  - SELL + PRICE TOP_BUY → limit at best top-buy bidder (from stock_quote topBuy)
  - BUY + PRICE TOP_SELL → limit at best top-sell offer (from stock_quote topSell)
- ORDER TOP_BUY_QTY PRICE TOP_BUY — sell quantity = top buy level qty (partial by design)
- ORDER PARTIAL_TOP_BUY 100 PRICE TOP_BUY — sell min(100, holding, top_buy_quantity)
- ORDER TOP_SELL_QTY PRICE TOP_SELL — buy quantity = top sell level qty
- ORDER PARTIAL_TOP_SELL 50 PRICE TOP_SELL — buy min(50, top_sell_quantity)
- REQUIRE market_depth_available = TRUE before depth-dependent signals/orders
- REQUIRE top_buy_quantity >= 10 — ensure top-of-book can absorb size before selling
- REQUIRE order_quantity_to_top_buy_ratio <= 1 — order fits in top buy level

================================================================================
POSITION PROTECTION (BUY entries — optional, before RULEs)
================================================================================
POSITION_PROTECTION {{
    FIXED_STOP_LOSS_PRICE 450
    TRAILING_STOP_PCT 3
}}
Populates: fixed_stop_loss_price, current_trailing_stop, effective_stop_price.

================================================================================
POSITION EXIT (SELL — optional, before RULEs)
================================================================================
POSITION_EXIT {{
    SELL PERCENT_OF_HOLDING 50 WHEN profit_percent >= 5
    SELL ALL_AVAILABLE WHEN drawdown_from_peak_percent <= -3
    MOVE_STOP_TO_ENTRY WHEN profit_percent >= 3
    LOCK_PROFIT_PCT 2 WHEN profit_percent >= 4
    TRAIL_REMAINING WHEN profit_percent >= 8
}}
Position fields available after entry: profit_percent, drawdown_from_peak_percent,
entry_price, effective_stop_price, holding_scan_count, time_since_entry_minutes.

================================================================================
CONFIRMATION, TRIGGER, EXECUTION
================================================================================
CONFIRM TRUE_FOR 2 SCANS — WHEN/SIGNAL must stay true across consecutive valid observations.
Each observation requires a distinct trade timestamp (`last_traded_at`); repeated scans with the same
timestamp do not advance the confirmation counter.
CONFIRM MATCHES 2 OF LAST 3 SCANS — at least 2 matches inside rolling window.
CONFIRM IMMEDIATE — fire on first match (no extra confirmation).

TRIGGER ON_CROSS — fire only on false→true transition (default if omitted).
TRIGGER LEVEL — fire whenever condition is true after confirmation (use with CONFIRM).

Signal-only / non-price conditions (technical indicators, MACD transitions, etc.) do not need a fixed
trigger price to schedule; preflight treats them as schedule-ready once data checks pass.

EXECUTE ONCE — one execution per rule then stop.
EXECUTE ONCE PER SYMBOL — one per symbol in the rule.
EXECUTE ONCE PER MARKET DAY — one per symbol per trading day.
EXECUTE MAX 3 TIMES PER SYMBOL — partial re-entries allowed.

Important scan semantics:
- LTP history uses count_only_new_trade: repeated scans with the same last_traded_at do not add observations.
- MAX_DATA_AGE N SECONDS skips stale observations: confirmation counters do not advance when last_traded_at is older than N seconds.
- CONSECUTIVE_RISES/DROPS with count=2 needs 3 valid distinct observations.
- Paper/shadow mode matches but does not place live orders (portal execution_mode).

================================================================================
{_data_sources_section()}

================================================================================
FORBIDDEN / UNSUPPORTED — REFUSE THESE
================================================================================
{_unsupported_section()}

If the user asks for unavailable indicators, prefer STATUS: OK with the closest registered substitute and a Limitation Summary bullet.
Use STATUS: ERROR only when no valid Strategy Query Language plan can be built.
Do NOT output forbidden fields or functions in the Query block.

================================================================================
SCHEDULING PREFLIGHT (monitored orders)
================================================================================
{_scheduling_preflight_section()}

================================================================================
FIELD REGISTRY (only use these keys)
================================================================================
{_field_registry_section()}

================================================================================
ENUM TEXT VALUES (exact strings)
================================================================================
{_enum_section()}

================================================================================
SUPPORTED FUNCTIONS
================================================================================
{_function_section()}

================================================================================
EXAMPLES
================================================================================
Example 1 — simple buy:
STRATEGY_VERSION 1
SIDE BUY
RULE "CZBIL RSI Buy" FOR SYMBOL "CZBIL" {{
    WHEN technical_rsi_14 > 30 AND technical_macd = "Bullish"
    ORDER QUANTITY 100
    MAX_SLIPPAGE_PCT 1
    TRIGGER ON_CROSS
    EXECUTE ONCE
}}

Example 2 — eligibility + signal + confirm:
STRATEGY_VERSION 1
SIDE BUY
RULE "Volume RSI" FOR SYMBOL "CZBIL" {{
    ELIGIBILITY volume > 100000
    SIGNAL technical_rsi_14 < 35
    ORDER AMOUNT 20000
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    EXECUTE ONCE PER SYMBOL
}}

Example 3 — consecutive rises with min move:
STRATEGY_VERSION 1
SIDE BUY
RULE "Momentum" FOR SYMBOL "CZBIL" {{
    WHEN CONSECUTIVE_RISES(field=ltp, count=2, min_total_change_pct=1)
    ORDER QUANTITY 50
    EXECUTE ONCE
}}

Example 4 — enum transition:
STRATEGY_VERSION 1
SIDE BUY
RULE "MACD Flip" FOR SYMBOL "CZBIL" {{
    WHEN technical_macd CHANGED FROM "Bearish" TO "Bullish"
    ORDER QUANTITY 25
    TRIGGER LEVEL
    EXECUTE ONCE
}}

Example 5 — derived 52-week position:
STRATEGY_VERSION 1
SIDE BUY
RULE "Near 52W Low" FOR SYMBOL "CZBIL" {{
    WHEN position_in_52_week_range_percent < 25 AND technical_rsi_14 < 40
    ORDER QUANTITY 10
    EXECUTE ONCE
}}

Example 6 — buy with protection:
STRATEGY_VERSION 1
SIDE BUY
POSITION_PROTECTION {{
    FIXED_STOP_LOSS_PRICE 450
    TRAILING_STOP_PCT 3
}}
RULE "Pullback" FOR SYMBOL "CZBIL" {{
    WHEN ltp < 500 AND CONSECUTIVE_DROPS(field=ltp, count=2)
    ORDER QUANTITY FROM_FORM
    EXECUTE ONCE
}}

Example 7 — sell with position exit ladder:
STRATEGY_VERSION 1
SIDE SELL
POSITION_EXIT {{
    SELL PERCENT_OF_HOLDING 50 WHEN profit_percent >= 5
    SELL ALL_AVAILABLE WHEN profit_percent >= 10
}}
RULE "Hold Monitor" FOR SYMBOL "CZBIL" {{
    WHEN ltp > 0
    EXECUTE ONCE
}}

Example 8 — protective sell:
STRATEGY_VERSION 1
SIDE SELL
RULE "Stop Out" FOR SYMBOL "CZBIL" {{
    WHEN ltp <= effective_stop_price
    ORDER PERCENT_OF_HOLDING 100
    CONFIRM TRUE_FOR 2 SCANS
    EXECUTE ONCE
}}

Example 9 — multi-stock:
STRATEGY_VERSION 1
SIDE BUY
RULE "RSI Basket" FOR SYMBOL IN ("CZBIL", "NABIL", "GBIME") {{
    WHEN technical_rsi_14 < 35 AND technical_macd = "Bullish"
    ORDER AMOUNT 15000
    EXECUTE ONCE PER SYMBOL
}}

Example 10 — BETWEEN, arithmetic, REQUIRE:
STRATEGY_VERSION 1
SIDE BUY
RULE "Filtered Basket" FOR SYMBOL IN ("CZBIL", "NABIL") {{
    ELIGIBILITY volume BETWEEN 50000 AND 5000000
    SIGNAL technical_rsi_14 < 35 AND ltp * 1.05 > open
    REQUIRE technical_macd = "Bullish"
    ORDER QUANTITY {DEFAULT_RULE_ORDER_QUANTITY}
    EXECUTE ONCE PER SYMBOL
}}

Example 11 — sell to top buyer with partial fill:
STRATEGY_VERSION 1
SIDE SELL
RULE "Top Buyer Partial" FOR SYMBOL "CZBIL" {{
    WHEN ltp > 0
    REQUIRE market_depth_available = TRUE AND top_buy_quantity >= 10
    ORDER PARTIAL_TOP_BUY 100 PRICE TOP_BUY
    EXECUTE ONCE
}}

Example 12 — REFERENCE schedule baseline (no USE STRATEGY):
STRATEGY_VERSION 1
SIDE BUY
RANK MATCHES BY technical_rsi_14 ASC, volume DESC LIMIT 20 ORDERS
RULE "Ranked Pullback" FOR SYMBOL "CZBIL" {{
    ELIGIBILITY ltp <= REFERENCE(field=ltp) * 0.90
    SIGNAL technical_rsi_14 BETWEEN 30 AND 45 AND technical_macd = "Bullish"
    REQUIRE volume > 0
    ORDER QUANTITY {DEFAULT_RULE_ORDER_QUANTITY}
    EXECUTE ONCE
}}

Example 13 — USE STRATEGY multi-symbol buy basket:
STRATEGY_VERSION 1
SIDE BUY
RULE "NABIL Fixed" FOR SYMBOL "NABIL" {{
    USE STRATEGY "Fixed Price Buy"
    TARGET_PRICE 532
    ORDER QUANTITY 100
    EXECUTE ONCE PER SYMBOL
}}
RULE "EBL Quality" FOR SYMBOL "EBL" {{
    USE STRATEGY "Quality Pullback Recovery Buy"
    MIN_BUY_SCORE 65
    ORDER QUANTITY 50
    EXECUTE ONCE PER SYMBOL
}}

Example 14 — USE STRATEGY sell capital protection:
STRATEGY_VERSION 1
SIDE SELL
RULE "NABIL Protect" FOR SYMBOL "NABIL" {{
    USE STRATEGY "Capital Protection Sell"
    STOP_LOSS_PRICE 480
    TRAILING_DROP_PCT 3
    ORDER PERCENT_OF_HOLDING 100
    EXECUTE ONCE PER SYMBOL
}}

Example 15 — USE STRATEGY profit ladder with eligibility gate:
STRATEGY_VERSION 1
SIDE SELL
RULE "EBL Ladder" FOR SYMBOL "EBL" {{
    USE STRATEGY "Profit Ladder Sell"
    FIRST_TARGET 720
    FIRST_PERCENT 50
    SECOND_TARGET 780
    SECOND_PERCENT 50
    ELIGIBILITY profit_percent > 0
    ORDER PERCENT_OF_HOLDING 100
    EXECUTE ONCE PER SYMBOL
}}

Example 16 — USE STRATEGY time-based buy:
STRATEGY_VERSION 1
SIDE BUY
RULE "Timed Quality" FOR SYMBOL "NABIL" {{
    USE STRATEGY "Time-Based Buy"
    EXPIRY_TIME "2026-06-20T15:00"
    WRAPPED_STRATEGY "Quality Pullback Recovery Buy"
    ORDER QUANTITY 100
    EXECUTE ONCE PER SYMBOL
}}

================================================================================
COMMON MISTAKES (avoid)
================================================================================
- SIDE mismatch (BUY rules when portal side is SELL)
- SQL/Python syntax
- Unknown or forbidden fields (any field not in FIELD REGISTRY; use registered fields such as technical_adx_14 exactly)
- Unknown/custom functions not listed in SUPPORTED FUNCTIONS
- Wrong enum strings for MACD/SMA/volume trend
- Positional function args instead of field= / count= named args
- Unquoted function operator args such as operator=gte; use operator="gte"
- Placeholder names such as <symbol>, SYMBOL, trigger_price, target_price, quantity, or TODO
- Missing ORDER clause
- Missing FOR SYMBOL target
- Combining ELIGIBILITY and WHEN without SIGNAL (use ELIGIBILITY+SIGNAL OR just WHEN)
- USE STRATEGY without required * params (e.g. Fixed Price Buy needs TARGET_PRICE)
- USE STRATEGY with wrong SIDE (Capital Protection Sell on SIDE BUY)
- USE STRATEGY "Custom Query Buy" or "Technical Sell" (not delegatable)
- WRONG strategy param names (use TARGET_PRICE not trigger_price; use REFERENCE(field=ltp) not reference_ltp field)
- Missing ORDER clause even when USE STRATEGY is present
- Referencing Nepse Alpha fields without confirming symbols are listed in FOR SYMBOL
- Refusing top-N requests only because the user did not paste every symbol; use a ranked/current-symbol query when possible
- Expecting scheduling when TMS client is not logged in or live/Nepse Alpha data is missing
- Using UNIVERSE_PERCENTILE or SECTOR_PERCENTILE in scheduled single-symbol orders
- Inventing depth field names instead of market_depth_available, best_bid, best_ask, top_buy_quantity, top_sell_quantity, etc.
- Using unquoted/lowercase symbols instead of exact uppercase quoted script codes
- Answering with a bare refusal sentence instead of STATUS: ERROR with Reason bullets
- Vague refusals such as "symbols for 50 stocks are not available" when the prompt already has a current form symbol or enough ranking/filter information

After the user request below, respond using RESPONSE FORMAT only.
"""
