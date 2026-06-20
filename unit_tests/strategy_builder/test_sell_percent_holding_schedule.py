import unittest
from unittest.mock import AsyncMock

from fastapi import HTTPException

from main import _validate_sell_lot_against_holdings, _validate_strategy_order
from schemas.schemas import OrderCreateRequest
from utils.strategy_builder.strategy_parser import parse_strategy_query


SELL_100_PERCENT_QUERY = """STRATEGY_VERSION 1
SIDE SELL
RULE "Sell At 10 Percent Gain" FOR SYMBOL "HDL" {
    WHEN ltp >= REFERENCE(field=ltp) * 1.10
    ORDER PERCENT_OF_HOLDING 100
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    MAX_SLIPPAGE_PCT 1
    EXECUTE ONCE PER SYMBOL
}
"""


class SellPercentHoldingScheduleTest(unittest.IsolatedAsyncioTestCase):
    def _order(self, query: str, *, qty: int = 100) -> OrderCreateRequest:
        compiled = parse_strategy_query(query).model_dump()
        return OrderCreateRequest(
            client_id="C1",
            script_name="HDL",
            price=0,
            qty=qty,
            order_type="sell",
            status="Waiting",
            strategy_type="Custom Query Sell",
            security_details={"symbol": "HDL", "boardLot": 10},
            strategy_config={"query_text": query, "compiled_plan": compiled, "execution_mode": "live"},
        )

    async def test_percent_of_holding_100_schedules_even_when_form_qty_exceeds_holding(self):
        tms_user = AsyncMock()
        tms_user.get_user_stock_details.return_value = [{"scrip": "HDL", "currentBalance": 4}]
        order_data = self._order(SELL_100_PERCENT_QUERY, qty=100)
        _validate_strategy_order(order_data)

        await _validate_sell_lot_against_holdings(order_data, tms_user)

        self.assertEqual(order_data.qty, 0)
        self.assertEqual(order_data.remaining_quantity, 0)

    async def test_fixed_sell_quantity_still_rejects_when_it_exceeds_holding(self):
        fixed_qty_query = SELL_100_PERCENT_QUERY.replace("ORDER PERCENT_OF_HOLDING 100", "ORDER QUANTITY 100")
        tms_user = AsyncMock()
        tms_user.get_user_stock_details.return_value = [{"scrip": "HDL", "currentBalance": 4}]

        with self.assertRaises(HTTPException) as ctx:
            await _validate_sell_lot_against_holdings(self._order(fixed_qty_query, qty=100), tms_user)

        self.assertIn("Sell quantity cannot exceed DP holding quantity (4)", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
