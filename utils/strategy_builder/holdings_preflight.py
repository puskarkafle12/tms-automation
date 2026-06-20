from __future__ import annotations

from typing import Dict, List, Optional

from utils.strategy_builder.strategy_models import StrategyPlanAST, TargetPreview, ValidationIssue


async def build_holdings_map(tms_user) -> Dict[str, int]:
    holdings: Dict[str, int] = {}
    rows = await tms_user.get_user_stock_details()
    for row in rows or []:
        qty = int(float(row.get("currentBalance") or 0))
        symbols = {
            str(row.get("scrip") or "").strip().upper(),
            str(row.get("symbolName") or "").strip().upper(),
            str(row.get("symbol") or "").strip().upper(),
        }
        for symbol in symbols:
            if not symbol:
                continue
            holdings[symbol] = max(holdings.get(symbol, 0), qty)
    return holdings


def apply_holdings_warnings(plan: StrategyPlanAST, holdings: Dict[str, int]) -> List[ValidationIssue]:
    warnings: List[ValidationIssue] = []
    if plan.side != "SELL":
        return warnings
    for rule in plan.rules:
        for symbol in rule.symbols:
            qty = holdings.get(symbol.upper(), 0)
            if qty <= 0:
                warnings.append(
                    ValidationIssue(
                        code="SELL_SYMBOL_NOT_HELD",
                        symbol=symbol.upper(),
                        message=(
                            f"Warning: {symbol.upper()} is not currently present in your holdings. "
                            "Its SELL rule can be saved, but no sell order will be placed until a sellable holding is available."
                        ),
                    )
                )
    return warnings


def enrich_targets_with_holdings(targets: List[TargetPreview], holdings: Dict[str, int]) -> List[TargetPreview]:
    enriched: List[TargetPreview] = []
    for target in targets:
        holding_qty = holdings.get(target.symbol.upper())
        item = target.model_copy()
        if holding_qty is not None:
            item.holding_qty = holding_qty
            if holding_qty <= 0:
                item.eligible = False
                item.status = "SKIPPED_NOT_HELD"
        enriched.append(item)
    return enriched
