import unittest

from utils.tms_broker import normalize_broker_no, tms_host_for_broker


class TmsClientResolverTest(unittest.TestCase):
    def test_normalize_short_broker_digits(self):
        self.assertEqual(normalize_broker_no("58"), "58")
        self.assertEqual(normalize_broker_no("tms58"), "58")

    def test_rejects_client_id_as_broker(self):
        with self.assertRaises(ValueError):
            normalize_broker_no("PK479690")

    def test_host_uses_normalized_broker(self):
        self.assertEqual(tms_host_for_broker("58"), "tms58.nepsetms.com.np")


if __name__ == "__main__":
    unittest.main()
