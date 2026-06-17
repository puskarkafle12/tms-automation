import asyncio
import unittest
from datetime import date
from unittest.mock import AsyncMock

import aiohttp

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

    def test_iter_yearly_date_ranges_splits_all_time_span(self):
        ranges = list(TmsUser._iter_yearly_date_ranges(
            date.fromisoformat("2010-10-01"),
            date.fromisoformat("2026-06-18"),
        ))
        self.assertEqual(ranges[0], ("2010-10-01", "2010-12-31"))
        self.assertEqual(ranges[-1], ("2026-01-01", "2026-06-18"))
        self.assertEqual(len(ranges), 17)

    def test_dedupe_tradebook_rows_keeps_unique_ids(self):
        rows = [{"id": 1, "symbol": "SBL"}, {"id": 1, "symbol": "SBL"}, {"id": 2, "symbol": "GUFL"}]
        deduped = TmsUser._dedupe_tradebook_rows(rows)
        self.assertEqual(len(deduped), 2)


class TestGetTradebookHistory(unittest.IsolatedAsyncioTestCase):
    def _make_user(self) -> TmsUser:
        user = TmsUser(broker_no="35", username="MN336760", password="secret")
        user.client_details = {"id": 1669294}
        user.tokens = {"XSRF-TOKEN": "token"}
        user.headers = user.get_header("34300", {"XSRF-TOKEN": "token"})
        return user

    def test_tradebook_timeout_is_longer_than_default(self):
        self.assertGreater(
            TmsUser.TRADEBOOK_TIMEOUT.sock_read,
            TmsUser.DEFAULT_TIMEOUT.sock_read,
        )
        self.assertGreaterEqual(TmsUser.TRADEBOOK_TIMEOUT.sock_read, 60)

    async def test_get_tradebook_history_page_uses_tradebook_timeout(self):
        user = self._make_user()
        captured: dict = {}

        async def mock_request(*_args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return 200, SAMPLE_TRADEBOOK_ARRAY

        user._authenticated_request = mock_request  # type: ignore[method-assign]
        user._recreate_session = AsyncMock()  # type: ignore[method-assign]

        payload = await user.get_tradebook_history_page("2010-10-01", "2026-06-18")
        self.assertEqual(payload, SAMPLE_TRADEBOOK_ARRAY)
        self.assertIs(captured["timeout"], TmsUser.TRADEBOOK_TIMEOUT)

    async def test_get_tradebook_history_page_retries_after_timeout(self):
        user = self._make_user()
        calls = {"count": 0}

        async def mock_request(*_args, **_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise aiohttp.ServerTimeoutError("Timeout on reading data from socket")
            return 200, SAMPLE_TRADEBOOK_ARRAY

        user._authenticated_request = mock_request  # type: ignore[method-assign]
        user._recreate_session = AsyncMock()  # type: ignore[method-assign]

        payload = await user.get_tradebook_history_page("2010-10-01", "2026-06-18")
        self.assertEqual(payload, SAMPLE_TRADEBOOK_ARRAY)
        self.assertEqual(calls["count"], 2)
        user._recreate_session.assert_awaited_once()

    async def test_slow_tms_response_within_tradebook_timeout_succeeds(self):
        user = self._make_user()

        async def mock_request(*_args, **kwargs):
            timeout = kwargs.get("timeout")
            self.assertIs(timeout, TmsUser.TRADEBOOK_TIMEOUT)
            # Old default sock_read was 8s; simulate a slow but acceptable TMS response.
            await asyncio.sleep(0.05)
            return 200, SAMPLE_TRADEBOOK_ARRAY

        user._authenticated_request = mock_request  # type: ignore[method-assign]
        user._recreate_session = AsyncMock()  # type: ignore[method-assign]

        rows = await user.get_tradebook_history("2026-06-01", "2026-06-18")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["script_name"], "SBL")

    async def test_all_time_range_uses_single_unpaginated_array_response(self):
        user = self._make_user()

        sample = [{"id": index, "symbol": "SBL", "exchangeTradeId": str(index)} for index in range(26)]
        requested_ranges = []

        async def mock_page(from_date, to_date, page_size=10, page_no=1):
            requested_ranges.append((from_date, to_date))
            self.assertEqual(page_size, 10)
            return sample if page_no == 1 else []

        user.get_tradebook_history_page = mock_page  # type: ignore[method-assign]

        rows = await user.get_tradebook_history("2010-10-01", "2026-06-19")
        self.assertEqual(len(rows), 26)
        self.assertEqual(rows[0]["script_name"], "SBL")
        self.assertEqual(len(requested_ranges), 17)

    async def test_all_time_chunks_merge_distinct_trades_per_year(self):
        user = self._make_user()
        trades_by_year = {
            "2018": [{"id": 6244, "symbol": "CZBIL", "tradeTime": "2018-12-31 12:43:45"}],
            "2022": [{"id": 1644822, "symbol": "PRVU", "tradeTime": "2022-12-27 14:35:07"}],
            "2026": [{"id": 4429215, "symbol": "SBL", "tradeTime": "2026-06-15 14:59:32"}],
        }

        async def mock_page(from_date, to_date, page_size=10, page_no=1):
            if page_no != 1:
                return []
            year = from_date[:4]
            return trades_by_year.get(year, [])

        user.get_tradebook_history_page = mock_page  # type: ignore[method-assign]

        rows = await user.get_tradebook_history("2010-10-01", "2026-06-18")
        self.assertEqual(len(rows), 3)
        symbols = {row["symbol"] for row in rows}
        self.assertEqual(symbols, {"CZBIL", "PRVU", "SBL"})
        self.assertEqual(rows[0]["tradeTime"], "2026-06-15 14:59:32")

    async def test_short_range_does_not_chunk(self):
        user = self._make_user()
        requested_ranges = []

        async def mock_page(from_date, to_date, page_size=10, page_no=1):
            requested_ranges.append((from_date, to_date))
            return SAMPLE_TRADEBOOK_ARRAY if page_no == 1 else []

        user.get_tradebook_history_page = mock_page  # type: ignore[method-assign]

        rows = await user.get_tradebook_history("2026-06-01", "2026-06-18")
        self.assertEqual(len(rows), 3)
        self.assertEqual(requested_ranges, [("2026-06-01", "2026-06-18")])

    async def test_paginates_when_api_returns_exact_page_size(self):
        user = self._make_user()

        page_one = [{"id": index, "symbol": "SBL", "exchangeTradeId": str(index)} for index in range(10)]
        page_two = [{"id": index, "symbol": "GUFL", "exchangeTradeId": str(index)} for index in range(10, 13)]

        async def mock_page(from_date, to_date, page_size=10, page_no=1):
            return page_one if page_no == 1 else page_two

        user.get_tradebook_history_page = mock_page  # type: ignore[method-assign]

        rows = await user.get_tradebook_history("2026-06-01", "2026-06-19")
        self.assertEqual(len(rows), 13)
