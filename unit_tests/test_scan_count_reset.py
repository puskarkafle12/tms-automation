import unittest

import config.tms_config as tms_config
from models.order_log import OrderLog
from models.scheduled_order import ScheduledOrder
from schemas.schemas import OrderCreateRequest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from utils.log_sender import (
    consume_monitor_scan_count_resets,
    delete_order_log_scan_count,
    reset_scan_count_after_scheduled_order_removed,
)


class ScanCountResetTests(unittest.TestCase):
    def setUp(self):
        tms_config.scan_count_reset_keys.clear()
        engine = create_engine("sqlite:///:memory:")
        ScheduledOrder.__table__.create(engine)
        OrderLog.__table__.create(engine)
        self.SessionLocal = sessionmaker(bind=engine)

    def test_reset_after_last_scheduled_order_removed(self):
        db = self.SessionLocal()
        try:
            order = ScheduledOrder(
                OrderCreateRequest(
                    client_id="C1",
                    script_name="NABIL",
                    price=100,
                    qty=10,
                    order_type="buy",
                    status="pending",
                )
            )
            db.add(order)
            db.add(
                OrderLog(
                    client_id="C1",
                    script_name="NABIL",
                    scanning_count=42,
                    current_price=100,
                    order_placed=False,
                )
            )
            db.commit()

            db.delete(order)
            reset_scan_count_after_scheduled_order_removed(db, "C1", "NABIL")
            db.commit()

            self.assertIsNone(
                db.query(OrderLog)
                .filter_by(client_id="C1", script_name="NABIL")
                .first()
            )
            self.assertEqual(consume_monitor_scan_count_resets(), {("C1", "NABIL")})
        finally:
            db.close()

    def test_does_not_reset_while_other_scheduled_order_remains(self):
        db = self.SessionLocal()
        try:
            remaining = ScheduledOrder(
                OrderCreateRequest(
                    client_id="C1",
                    script_name="NABIL",
                    price=100,
                    qty=10,
                    order_type="buy",
                    status="pending",
                )
            )
            to_delete = ScheduledOrder(
                OrderCreateRequest(
                    client_id="C1",
                    script_name="NABIL",
                    price=110,
                    qty=5,
                    order_type="buy",
                    status="pending",
                )
            )
            db.add_all([remaining, to_delete])
            db.add(
                OrderLog(
                    client_id="C1",
                    script_name="NABIL",
                    scanning_count=15,
                    current_price=100,
                    order_placed=False,
                )
            )
            db.commit()

            db.delete(to_delete)
            reset_scan_count_after_scheduled_order_removed(db, "C1", "NABIL")
            db.commit()

            log = db.query(OrderLog).filter_by(client_id="C1", script_name="NABIL").first()
            self.assertIsNotNone(log)
            self.assertEqual(log.scanning_count, 15)
            self.assertEqual(consume_monitor_scan_count_resets(), set())
        finally:
            db.close()

    def test_delete_order_log_queues_monitor_reset(self):
        db = self.SessionLocal()
        try:
            db.add(
                OrderLog(
                    client_id="C2",
                    script_name="UPPER",
                    scanning_count=7,
                    current_price=50,
                    order_placed=False,
                )
            )
            db.commit()

            delete_order_log_scan_count(db, "C2", "UPPER", commit=True)

            self.assertIsNone(
                db.query(OrderLog)
                .filter_by(client_id="C2", script_name="UPPER")
                .first()
            )
            self.assertEqual(consume_monitor_scan_count_resets(), {("C2", "UPPER")})
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
