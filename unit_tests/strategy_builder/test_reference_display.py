import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.scheduled_field_reference import ScheduledFieldReference
from models.scheduled_order import ScheduledOrder
from schemas.schemas import OrderCreateRequest
from utils.strategy_builder.reference_display import display_values_for_scheduled_order, display_values_from_strategy_config
from utils.strategy_builder.reference_schedule import serialize_reference_rows
from utils.strategy_builder.reference_store import ReferenceRow, ReferenceStore, persist_reference_rows
from utils.strategy_builder.strategy_parser import parse_strategy_query


SELL_GAIN_QUERY = """STRATEGY_VERSION 1
SIDE SELL
RULE "Sell At 10 Percent Gain" FOR SYMBOL IN ("API") {
    WHEN ltp >= REFERENCE(field=ltp) * 1.10
    ORDER PERCENT_OF_HOLDING 100
    CONFIRM TRUE_FOR 2 SCANS
    TRIGGER LEVEL
    MAX_SLIPPAGE_PCT 1
    EXECUTE ONCE PER SYMBOL
}"""


class ReferenceDisplayTest(unittest.TestCase):
    def test_sell_reference_ltp_trigger_is_displayed_from_stored_rows(self):
        plan = parse_strategy_query(SELL_GAIN_QUERY)
        captured_at = datetime(2026, 6, 20, 10, 15, 0)
        rows = [
            ReferenceRow(
                rule_name="Sell At 10 Percent Gain",
                symbol="API",
                field_key="ltp",
                field_type="decimal",
                numeric_value=500.0,
                captured_at=captured_at,
                source="tms_quote",
            )
        ]
        values = display_values_from_strategy_config(
            strategy_config={"compiled_plan": plan.model_dump()},
            symbol="API",
            store=ReferenceStore(rows),
        )

        self.assertEqual(values.reference_ltp, 500.0)
        self.assertAlmostEqual(values.trigger_price, 550.0)
        self.assertEqual(values.reference_ltp_captured_at, captured_at)

    def test_strategy_config_rows_are_used_as_fallback(self):
        plan = parse_strategy_query(SELL_GAIN_QUERY)
        rows = [
            ReferenceRow(
                rule_name="Sell At 10 Percent Gain",
                symbol="API",
                field_key="ltp",
                field_type="decimal",
                numeric_value=700.0,
            )
        ]

        values = display_values_from_strategy_config(
            strategy_config={
                "compiled_plan": plan.model_dump(),
                "field_reference_rows": serialize_reference_rows(rows),
            },
            symbol="API",
        )

        self.assertEqual(values.reference_ltp, 700.0)
        self.assertAlmostEqual(values.trigger_price, 770.0)

    def test_display_reads_reference_rows_from_database_first(self):
        plan = parse_strategy_query(SELL_GAIN_QUERY)
        engine = create_engine("sqlite:///:memory:")
        ScheduledOrder.__table__.create(engine)
        ScheduledFieldReference.__table__.create(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        try:
            order = ScheduledOrder(
                OrderCreateRequest(
                    client_id="CLIENT1",
                    script_name="API",
                    price=0,
                    qty=10,
                    order_type="sell",
                    strategy_type="Custom Query Sell",
                    strategy_config={"compiled_plan": plan.model_dump()},
                )
            )
            db.add(order)
            db.flush()
            persist_reference_rows(
                db,
                order.order_id,
                [
                    ReferenceRow(
                        rule_name="Sell At 10 Percent Gain",
                        symbol="API",
                        field_key="ltp",
                        field_type="decimal",
                        numeric_value=600.0,
                    )
                ],
            )
            db.commit()

            loaded = db.query(ScheduledOrder).filter(ScheduledOrder.order_id == order.order_id).first()
            values = display_values_for_scheduled_order(db, loaded)

            self.assertEqual(values.reference_ltp, 600.0)
            self.assertAlmostEqual(values.trigger_price, 660.0)
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
