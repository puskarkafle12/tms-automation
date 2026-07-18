"""Central field registry for strategy builder GUI, parser, validator, and evaluator."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from utils.external_data_sources.nepse_alpha.screener import (
    COLLOQUIAL_FIELD_ALIASES,
    FIELD_CATALOG as SCREENER_FIELD_CATALOG,
    build_field_aliases as build_screener_aliases,
)

NUMERIC_OPERATORS = ["eq", "neq", "gt", "gte", "lt", "lte", "between", "not_between", "in", "not_in"]
TEXT_OPERATORS = ["eq", "neq", "in", "not_in", "contains", "not_contains"]
ENUM_OPERATORS = ["eq", "neq", "in", "not_in", "changed_to", "changed_from_to"]
AVAILABILITY_OPERATORS = ["is_available", "is_not_available", "is_null", "is_not_null"]

LIVE_FIELDS: List[Dict[str, Any]] = [
    {"key": "symbol", "label": "Symbol", "category": "live", "data_type": "text", "nullable": False},
    {"key": "ltp", "label": "LTP", "category": "live", "data_type": "decimal", "nullable": True, "supports_history": True},
    {"key": "open", "label": "Open", "category": "live", "data_type": "decimal", "nullable": True},
    {"key": "high", "label": "High", "category": "live", "data_type": "decimal", "nullable": True},
    {"key": "low", "label": "Low", "category": "live", "data_type": "decimal", "nullable": True},
    {"key": "volume", "label": "Volume", "category": "live", "data_type": "decimal", "nullable": True, "supports_history": True},
    {"key": "previous_close", "label": "Previous Close", "category": "live", "data_type": "decimal", "nullable": True},
    {"key": "change", "label": "Change", "category": "live", "data_type": "decimal", "nullable": True},
    {"key": "change_percent", "label": "Change %", "category": "live", "data_type": "decimal", "nullable": True},
    {"key": "last_traded_at", "label": "Last Traded At", "category": "live", "data_type": "text", "nullable": True},
]

DERIVED_LIVE_FIELDS: List[Dict[str, Any]] = [
    {"key": "intraday_range", "label": "Intraday Range", "category": "derived_live", "data_type": "decimal", "nullable": True},
    {"key": "intraday_range_percent", "label": "Intraday Range %", "category": "derived_live", "data_type": "decimal", "nullable": True},
    {"key": "distance_from_open", "label": "Distance From Open", "category": "derived_live", "data_type": "decimal", "nullable": True},
    {"key": "distance_from_open_percent", "label": "Distance From Open %", "category": "derived_live", "data_type": "decimal", "nullable": True},
    {"key": "distance_from_day_high", "label": "Distance From Day High", "category": "derived_live", "data_type": "decimal", "nullable": True},
    {"key": "distance_from_day_high_percent", "label": "Distance From Day High %", "category": "derived_live", "data_type": "decimal", "nullable": True},
    {"key": "distance_from_day_low", "label": "Distance From Day Low", "category": "derived_live", "data_type": "decimal", "nullable": True},
    {"key": "distance_from_day_low_percent", "label": "Distance From Day Low %", "category": "derived_live", "data_type": "decimal", "nullable": True},
]

DERIVED_STAT_FIELDS: List[Dict[str, Any]] = [
    {"key": "distance_from_52_week_high", "label": "Distance From 52W High", "category": "derived_statistical", "data_type": "decimal", "nullable": True},
    {"key": "distance_from_52_week_high_percent", "label": "Distance From 52W High %", "category": "derived_statistical", "data_type": "decimal", "nullable": True},
    {"key": "distance_from_52_week_low", "label": "Distance From 52W Low", "category": "derived_statistical", "data_type": "decimal", "nullable": True},
    {"key": "distance_from_52_week_low_percent", "label": "Distance From 52W Low %", "category": "derived_statistical", "data_type": "decimal", "nullable": True},
    {"key": "position_in_52_week_range_percent", "label": "Position In 52W Range %", "category": "derived_statistical", "data_type": "decimal", "nullable": True},
    {"key": "distance_from_all_time_high_percent", "label": "Distance From ATH %", "category": "derived_statistical", "data_type": "decimal", "nullable": True},
    {"key": "distance_from_all_time_low_percent", "label": "Distance From ATL %", "category": "derived_statistical", "data_type": "decimal", "nullable": True},
]

MARKET_DEPTH_FIELDS: List[Dict[str, Any]] = [
    {"key": "market_depth_available", "label": "Market Depth Available", "category": "market_depth", "data_type": "boolean", "nullable": False},
    {"key": "best_bid", "label": "Best Bid / Top Buy Price", "category": "market_depth", "data_type": "decimal", "nullable": True},
    {"key": "best_ask", "label": "Best Ask / Top Sell Price", "category": "market_depth", "data_type": "decimal", "nullable": True},
    {"key": "spread", "label": "Bid-Ask Spread", "category": "market_depth", "data_type": "decimal", "nullable": True},
    {"key": "spread_percent", "label": "Bid-Ask Spread %", "category": "market_depth", "data_type": "decimal", "nullable": True},
    {"key": "top_buy_quantity", "label": "Top Buy Quantity", "category": "market_depth", "data_type": "decimal", "nullable": True},
    {"key": "top_sell_quantity", "label": "Top Sell Quantity", "category": "market_depth", "data_type": "decimal", "nullable": True},
    {"key": "total_buy_quantity", "label": "Total Buy Quantity", "category": "market_depth", "data_type": "decimal", "nullable": True},
    {"key": "total_sell_quantity", "label": "Total Sell Quantity", "category": "market_depth", "data_type": "decimal", "nullable": True},
    {"key": "buy_sell_quantity_ratio", "label": "Buy/Sell Quantity Ratio", "category": "market_depth", "data_type": "decimal", "nullable": True},
    {"key": "order_book_imbalance", "label": "Order Book Imbalance", "category": "market_depth", "data_type": "decimal", "nullable": True},
]

POSITION_PROTECTION_FIELDS: List[Dict[str, Any]] = [
    {"key": "entry_price", "label": "Entry Price", "category": "position", "data_type": "decimal", "nullable": True},
    {"key": "highest_price_since_entry", "label": "Highest Price Since Entry", "category": "position", "data_type": "decimal", "nullable": True},
    {"key": "fixed_stop_loss_price", "label": "Fixed Stop Loss Price", "category": "position", "data_type": "decimal", "nullable": True},
    {"key": "current_trailing_stop", "label": "Current Trailing Stop", "category": "position", "data_type": "decimal", "nullable": True},
    {"key": "effective_stop_price", "label": "Effective Stop Price", "category": "position", "data_type": "decimal", "nullable": True},
    {"key": "profit_percent", "label": "Profit %", "category": "position", "data_type": "decimal", "nullable": True},
    {"key": "unrealized_profit", "label": "Unrealized Profit", "category": "position", "data_type": "decimal", "nullable": True},
    {"key": "runup_percent", "label": "Run-up %", "category": "position", "data_type": "decimal", "nullable": True},
    {"key": "drawdown_from_peak_percent", "label": "Drawdown From Peak %", "category": "position", "data_type": "decimal", "nullable": True},
    {"key": "distance_from_entry_percent", "label": "Distance From Entry %", "category": "position", "data_type": "decimal", "nullable": True},
    {"key": "holding_scan_count", "label": "Holding Scan Count", "category": "position", "data_type": "decimal", "nullable": True},
    {"key": "time_since_entry_minutes", "label": "Time Since Entry (min)", "category": "position", "data_type": "decimal", "nullable": True},
]

LIQUIDITY_FIELDS: List[Dict[str, Any]] = [
    {"key": "order_quantity_to_top_buy_ratio", "label": "Order Qty / Top Buy", "category": "liquidity", "data_type": "decimal", "nullable": True},
    {"key": "order_quantity_to_top_sell_ratio", "label": "Order Qty / Top Sell", "category": "liquidity", "data_type": "decimal", "nullable": True},
    {"key": "order_quantity_to_total_depth_ratio", "label": "Order Qty / Total Depth", "category": "liquidity", "data_type": "decimal", "nullable": True},
    {"key": "estimated_slippage_percent", "label": "Estimated Slippage %", "category": "liquidity", "data_type": "decimal", "nullable": True},
    {"key": "depth_supported_quantity", "label": "Depth Supported Qty", "category": "liquidity", "data_type": "decimal", "nullable": True},
    {"key": "spread_change_percent", "label": "Spread Change %", "category": "liquidity", "data_type": "decimal", "nullable": True},
    {"key": "volatility_risk_score", "label": "Volatility Risk Score", "category": "risk", "data_type": "decimal", "nullable": True},
    {"key": "stop_distance_percent", "label": "Stop Distance %", "category": "risk", "data_type": "decimal", "nullable": True},
    {"key": "position_risk_percent", "label": "Position Risk %", "category": "risk", "data_type": "decimal", "nullable": True},
    {"key": "opening_gap_percent", "label": "Opening Gap %", "category": "derived_live", "data_type": "decimal", "nullable": True},
    {"key": "position_in_intraday_range_percent", "label": "Position In Intraday Range %", "category": "derived_live", "data_type": "decimal", "nullable": True},
    {"key": "distance_from_previous_close_percent", "label": "Distance From Prev Close %", "category": "derived_live", "data_type": "decimal", "nullable": True},
]

SECTOR_SUFFIXES = ("_sector_high", "_sector_low")

ENUM_VALUES: Dict[str, List[str]] = {
    "technical_macd": ["Bullish", "Bearish"],
    "technical_sma_10": ["above", "below"],
    "technical_sma_20": ["above", "below"],
    "technical_sma_50": ["above", "below"],
    "technical_sma_200": ["above", "below"],
    "technical_volume_trend": ["Trending Up", "Trending Down", "Flat"],
    "technical_supertrend": ["Bullish", "Bearish"],
    "technical_psar": ["Bullish", "Bearish"],
    "technical_squeeze": ["On", "Released", "Neutral"],
    "technical_3m_price_tend": ["Trending Up", "Trending Down", "Flat"],
    "technical_signal": ["Strong Buy", "Buy", "Neutral", "Sell", "Strong Sell"],
}

SUPPORTED_FUNCTIONS: List[Dict[str, Any]] = [
    {"name": "PREVIOUS", "category": "temporal", "description": "Previous field value N scans back"},
    {"name": "CHANGE", "category": "temporal", "description": "Absolute change over N scans"},
    {"name": "CHANGE_PERCENT", "category": "temporal", "description": "Percent change over N scans"},
    {"name": "CONSECUTIVE_DROPS", "category": "temporal", "description": "Consecutive valid drops in a field"},
    {"name": "CONSECUTIVE_RISES", "category": "temporal", "description": "Consecutive valid rises in a field"},
    {"name": "CROSSES_ABOVE", "category": "temporal", "description": "Field crosses above threshold"},
    {"name": "CROSSES_BELOW", "category": "temporal", "description": "Field crosses below threshold"},
    {"name": "REMAINS_ABOVE", "category": "temporal", "description": "Field remains above threshold"},
    {"name": "REMAINS_BELOW", "category": "temporal", "description": "Field remains below threshold"},
    {"name": "TRUE_FOR_SCANS", "category": "temporal", "description": "Condition true for N consecutive scans"},
    {"name": "MATCHES_IN_LAST", "category": "temporal", "description": "Condition matched N of last M scans"},
    {"name": "CHANGED_TO", "category": "temporal", "description": "Enum field changed to value"},
    {"name": "CHANGED_FROM_TO", "category": "temporal", "description": "Enum field changed from A to B"},
    {"name": "AVERAGE", "category": "rolling", "description": "Rolling average"},
    {"name": "MIN_VALUE", "category": "rolling", "description": "Rolling minimum"},
    {"name": "MAX_VALUE", "category": "rolling", "description": "Rolling maximum"},
    {"name": "SUM_VALUE", "category": "rolling", "description": "Rolling sum"},
    {"name": "STDDEV", "category": "rolling", "description": "Rolling standard deviation"},
    {"name": "SLOPE", "category": "rolling", "description": "Rolling linear slope"},
    {"name": "TREND", "category": "rolling", "description": "Trend direction over window"},
    {"name": "SECTOR_POSITION", "category": "sector", "description": "Sector-relative position percent"},
    {"name": "UNIVERSE_PERCENTILE", "category": "ranking", "description": "Percentile within current scan universe"},
    {"name": "SECTOR_PERCENTILE", "category": "ranking", "description": "Percentile within sector in current scan"},
    {"name": "DEPTH_QUANTITY", "category": "market_depth", "description": "Total quantity on BUY or SELL side across top N levels"},
    {"name": "DEPTH_ORDER_COUNT", "category": "market_depth", "description": "Number of non-empty BUY or SELL depth levels"},
    {"name": "DEPTH_IMBALANCE", "category": "market_depth", "description": "Buy/sell quantity imbalance across top N levels"},
    {"name": "DEPTH_IMBALANCE_REMAINS_ABOVE", "category": "market_depth", "description": "Depth imbalance remains above a threshold"},
    {"name": "DEPTH_IMBALANCE_REMAINS_BELOW", "category": "market_depth", "description": "Depth imbalance remains below a threshold"},
    {"name": "DEPTH_PRESSURE_TREND", "category": "market_depth", "description": "Buying/selling pressure trend from depth imbalance"},
    {"name": "SPREAD_REMAINS_BELOW", "category": "market_depth", "description": "Spread percent remains below a threshold"},
    {"name": "REFERENCE", "category": "schedule", "description": "Schedule-time snapshot of a registered field captured once per symbol"},
]


def _screener_to_registry_entry(item: Dict[str, Any]) -> Dict[str, Any]:
    data_type = "decimal" if item.get("type") == "number" else "text"
    category = (item.get("category") or "statistical").lower()
    entry: Dict[str, Any] = {
        "key": item["key"],
        "label": item["label"],
        "category": category,
        "data_type": data_type,
        "nullable": True,
        "supports_history": data_type == "decimal",
        "allowed_operators": NUMERIC_OPERATORS if data_type == "decimal" else TEXT_OPERATORS,
    }
    if item["key"] == "technical_rsi_14":
        entry.update({"minimum": 0, "maximum": 100})
    if item["key"] in ENUM_VALUES:
        entry["enum_values"] = ENUM_VALUES[item["key"]]
        entry["allowed_operators"] = ENUM_OPERATORS
    return entry


def _sector_entries() -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for item in SCREENER_FIELD_CATALOG:
        if item.get("type") != "number":
            continue
        base = item["key"]
        for suffix in SECTOR_SUFFIXES:
            key = f"{base}{suffix}"
            label_suffix = "Sector High" if suffix.endswith("_high") else "Sector Low"
            entries.append(
                {
                    "key": key,
                    "label": f"{item['label']} {label_suffix}",
                    "category": "sector",
                    "data_type": "decimal",
                    "nullable": True,
                    "supports_history": False,
                    "allowed_operators": NUMERIC_OPERATORS,
                }
            )
    return entries


def build_field_registry() -> Dict[str, Dict[str, Any]]:
    registry: Dict[str, Dict[str, Any]] = {}
    for item in LIVE_FIELDS + DERIVED_LIVE_FIELDS + DERIVED_STAT_FIELDS + MARKET_DEPTH_FIELDS + POSITION_PROTECTION_FIELDS + LIQUIDITY_FIELDS:
        registry[item["key"]] = dict(item)
    for item in SCREENER_FIELD_CATALOG:
        entry = _screener_to_registry_entry(item)
        registry[entry["key"]] = entry
    for item in _sector_entries():
        registry[item["key"]] = item
    return registry


FIELD_REGISTRY: Dict[str, Dict[str, Any]] = build_field_registry()


def get_field_metadata(key: str) -> Optional[Dict[str, Any]]:
    return FIELD_REGISTRY.get(key)


def get_field_catalog() -> List[Dict[str, Any]]:
    return list(FIELD_REGISTRY.values())


def get_supported_functions() -> List[Dict[str, Any]]:
    return list(SUPPORTED_FUNCTIONS)


def build_field_aliases() -> Dict[str, str]:
    aliases = build_screener_aliases()
    for key in FIELD_REGISTRY:
        aliases[key.lower()] = key
    for alias, target in COLLOQUIAL_FIELD_ALIASES.items():
        if target in FIELD_REGISTRY:
            aliases[alias.lower()] = target
    return aliases


def resolve_field_name(raw: str) -> Optional[str]:
    cleaned = (raw or "").strip()
    if not cleaned:
        return None
    if cleaned in FIELD_REGISTRY:
        return cleaned
    aliases = build_field_aliases()
    return aliases.get(cleaned.lower())


def allowed_operators_for_field(key: str) -> List[str]:
    meta = get_field_metadata(key)
    if not meta:
        return []
    return list(meta.get("allowed_operators") or NUMERIC_OPERATORS)


def is_known_field(key: str) -> bool:
    return key in FIELD_REGISTRY


def suggest_fields_for_unknown(raw: str, limit: int = 4) -> List[str]:
    cleaned = (raw or "").strip().lower()
    if not cleaned:
        return []
    scored: List[tuple[int, str]] = []
    for key, meta in FIELD_REGISTRY.items():
        label = str(meta.get("label") or key).lower()
        score = 0
        if cleaned in key.lower():
            score += 3
        if cleaned in label:
            score += 2
        if key.lower().startswith(cleaned[:4]):
            score += 1
        if score:
            scored.append((score, key))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [key for _, key in scored[:limit]]


def all_field_keys() -> Set[str]:
    return set(FIELD_REGISTRY.keys())
