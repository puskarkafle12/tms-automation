import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import _reject_duplicate_scheduled_order, _scheduled_order_dedup_key
from models.scheduled_field_reference import ScheduledFieldReference
from models.scheduled_order import ScheduledOrder
from schemas.schemas import OrderCreateRequest
from utils.strategy_builder.strategy_parser import parse_strategy_query


QUERY = """STRATEGY_VERSION 1
SIDE SELL
RULE "Sell At 10 Percent Gain" FOR SYMBOL IN ("API") {
    WHEN ltp >= REFERENCE(field=ltp) * 1.10
    ORDER PERCENT_OF_HOLDING 100
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    MAX_SLIPPAGE_PCT 1
    EXECUTE ONCE PER SYMBOL
}"""


class DuplicateScheduleGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_schedule_is_skipped_with_reason(self):
        engine = create_engine("sqlite:///:memory:")
        ScheduledOrder.__table__.create(engine)
        ScheduledFieldReference.__table__.create(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        try:
            compiled = parse_strategy_query(QUERY).model_dump()
            order_data = OrderCreateRequest(
                client_id="CLIENT1",
                script_name="API",
                price=0,
                qty=100,
                order_type="sell",
                strategy_type="Custom Query Sell",
                strategy_config={"query_text": QUERY, "compiled_plan": compiled},
            )
            order = ScheduledOrder(order_data)
            db.add(order)
            db.flush()
            order.strategy_config = dict(order.strategy_config or {})
            order.strategy_config["schedule_dedup_key"] = _scheduled_order_dedup_key(order_data)
            db.commit()

            duplicate = await _reject_duplicate_scheduled_order(db, order_data)

            self.assertIsNotNone(duplicate)
            self.assertTrue(duplicate["skipped"])
            self.assertIn("duplicate order", duplicate["message"].lower())
            self.assertEqual(duplicate["existing_order_id"], order.order_id)
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
