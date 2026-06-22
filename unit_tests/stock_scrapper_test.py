import unittest

from services.stock_data_scrapper.scrapper import convert_to_numeric


class StockScrapperTest(unittest.TestCase):
    def test_convert_to_numeric_accepts_already_numeric_values(self):
        self.assertEqual(convert_to_numeric(123.45), 123.45)
        self.assertEqual(convert_to_numeric(10), 10)

    def test_convert_to_numeric_parses_formatted_strings(self):
        self.assertEqual(convert_to_numeric("1,234.5"), 1234.5)
        self.assertEqual(convert_to_numeric("-2.5%"), -2.5)

    def test_convert_to_numeric_keeps_empty_market_placeholders(self):
        self.assertEqual(convert_to_numeric("-"), "-")
        self.assertIsNone(convert_to_numeric(None))


if __name__ == "__main__":
    unittest.main()
