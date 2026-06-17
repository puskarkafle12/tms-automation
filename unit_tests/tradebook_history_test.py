import unittest

from utils.tms import TmsUser

SAMPLE_TRADEBOOK_ARRAY = [
    {
        "id": 4429215,
        "clientMemberCode": "MN336760",
        "symbol": "SBL",
        "tradeTime": "2026-06-15 14:59:32",
        "exchangeTradeId": "2026061501021873",
        "exchangeOrderId": "2026061501051674",
        "buyOrSell": 2,
        "tradePrice": 398.0,
        "tradedQuantity": 521,
    },
    {
        "id": 1644822,
        "clientMemberCode": "MN336760",
        "symbol": "PRVU",
        "tradeTime": "2022-12-27 14:35:07",
        "exchangeTradeId": "2022122701017403",
        "exchangeOrderId": "2022122701030949",
        "buyOrSell": 1,
        "tradePrice": 200.0,
        "tradedQuantity": 390,
    },
    {
        "id": 6244,
        "clientMemberCode": "MN336760",
        "symbol": "CZBIL",
        "tradeTime": "2018-12-31 12:43:45",
        "exchangeTradeId": "2018123101001431",
        "exchangeOrderId": "2018123101004447",
        "buyOrSell": 1,
        "tradePrice": 222.0,
        "tradedQuantity": 32,
    },
]


class TestTradebookPagination(unittest.TestCase):
    def test_merge_single_unpaginated_response_larger_than_page_size(self):
        rows = [{"id": index} for index in range(26)]
        merged = TmsUser._merge_tradebook_pages([rows], page_size=10)
        self.assertEqual(len(merged), 26)

    def test_merge_multiple_pages(self):
        page_one = [{"id": index} for index in range(10)]
        page_two = [{"id": index} for index in range(10, 15)]
        merged = TmsUser._merge_tradebook_pages([page_one, page_two], page_size=10)
        self.assertEqual(len(merged), 15)

    def test_merge_stops_on_empty_page(self):
        page_one = [{"id": index} for index in range(10)]
        merged = TmsUser._merge_tradebook_pages([page_one, []], page_size=10)
        self.assertEqual(len(merged), 10)

    def test_merge_respects_total_pages(self):
        page_one = [{"id": index} for index in range(10)]
        page_two = [{"id": index} for index in range(10, 20)]
        merged = TmsUser._merge_tradebook_pages([page_one, page_two], page_size=10, total_pages=2)
        self.assertEqual(len(merged), 20)

    def test_order_book_rows_reads_top_level_tradebook_array(self):
        rows = TmsUser._order_book_rows(SAMPLE_TRADEBOOK_ARRAY)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["symbol"], "SBL")

    def test_order_book_rows_reads_tradebook_history_key(self):
        payload = {"tradeBookHistory": [{"exchangeTradeId": "1"}]}
        rows = TmsUser._order_book_rows(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exchangeTradeId"], "1")

    def test_normalize_tradebook_row_sets_script_name_alias(self):
        normalized = TmsUser._normalize_tradebook_row({"symbol": "sbl"})
        self.assertEqual(normalized["symbol"], "SBL")
        self.assertEqual(normalized["script_name"], "SBL")


class TestGetTradebookHistory(unittest.IsolatedAsyncioTestCase):
    async def test_all_time_range_uses_single_unpaginated_array_response(self):
        user = TmsUser(broker_no="35", username="MN336760", password="secret")
        user.client_details = {"id": 1669294}
        user.tokens = {"XSRF-TOKEN": "token"}
        user.headers = user.get_header("34300", {"XSRF-TOKEN": "token"})

        sample = [{"id": index, "symbol": "SBL", "exchangeTradeId": str(index)} for index in range(26)]

        async def mock_page(from_date, to_date, page_size=10, page_no=1):
            self.assertEqual(from_date, "2010-10-01")
            self.assertEqual(to_date, "2026-06-19")
            self.assertEqual(page_size, 10)
            return sample if page_no == 1 else []

        user.get_tradebook_history_page = mock_page  # type: ignore[method-assign]

        rows = await user.get_tradebook_history("2010-10-01", "2026-06-19")
        self.assertEqual(len(rows), 26)
        self.assertEqual(rows[0]["script_name"], "SBL")

    async def test_paginates_when_api_returns_exact_page_size(self):
        user = TmsUser(broker_no="35", username="MN336760", password="secret")
        user.client_details = {"id": 1669294}
        user.tokens = {"XSRF-TOKEN": "token"}
        user.headers = user.get_header("34300", {"XSRF-TOKEN": "token"})

        page_one = [{"id": index, "symbol": "SBL", "exchangeTradeId": str(index)} for index in range(10)]
        page_two = [{"id": index, "symbol": "GUFL", "exchangeTradeId": str(index)} for index in range(10, 13)]

        async def mock_page(from_date, to_date, page_size=10, page_no=1):
            return page_one if page_no == 1 else page_two

        user.get_tradebook_history_page = mock_page  # type: ignore[method-assign]

        rows = await user.get_tradebook_history("2026-06-01", "2026-06-19")
        self.assertEqual(len(rows), 13)
