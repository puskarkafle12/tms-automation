from __future__ import annotations

import unittest

from services.stock_data_scrapper.sharesansar import (
    PAGE_SIZE,
    fetch_all_company_details,
    normalize_company_row,
)
from utils.market_data.daily_snapshot import _merge_latest_market_activity


class _FakeResponse:
    def __init__(self, *, text="", payload=None):
        self.text = text
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self):
        self.requests = []

    def get(self, _url, *, params=None, headers=None, timeout=None):
        if params is None:
            return _FakeResponse(
                text="""
                <select id="sector" name="sector">
                  <option value="1">Commercial Bank</option>
                  <option value="7">Hydropower</option>
                </select>
                """
            )
        self.requests.append(dict(params))
        sector = str(params["sector"])
        start = int(params["start"])
        if sector == "1":
            total = 51
            count = 50 if start == 0 else 1
            rows = [
                {
                    "symbol": f"<a href='https://example.test/C{start + idx}'>C{start + idx}</a>",
                    "companyname": f"Company {start + idx}",
                    "shares": "1,000.00",
                    "marketcap": "2,500.50",
                    "ltp": "250.05",
                    "date": "2026-07-15",
                }
                for idx in range(count)
            ]
        else:
            total = 1
            rows = [{"symbol": "<a>H1</a>", "companyname": "Hydro One"}]
        return _FakeResponse(payload={"recordsTotal": total, "recordsFiltered": total, "data": rows})


class ShareSansarCompanyListTest(unittest.TestCase):
    def test_normalizes_html_and_numeric_fields(self):
        row = normalize_company_row(
            {
                "symbol": "<a href='https://www.sharesansar.com/company/czbil'>CZBIL</a>",
                "companyname": "<a>Citizens Bank International Limited</a>",
                "shares": "155,074,638.00",
                "prom_share": "75,440,119.00 (48.65%)",
                "public_share": "72,250,012.00 (46.59%)",
                "paidup": "100.00",
                "paidupcap": "15,507,463,800.00",
                "marketcap": "30,518,688,758.40",
                "listing_date": "2017-01-10",
                "ltp": "196.80",
                "date": "2026-07-15",
            },
            sector_id="1",
            sector="Commercial Bank",
        )

        self.assertEqual(row["symbol"], "CZBIL")
        self.assertEqual(row["company_name"], "Citizens Bank International Limited")
        self.assertEqual(row["shares_outstanding"], 155074638.0)
        self.assertEqual(row["promoter_shares"], 75440119.0)
        self.assertEqual(row["promoter_share_percent"], 48.65)
        self.assertEqual(row["public_share_percent"], 46.59)
        self.assertEqual(row["market_cap"], 30518688758.4)
        self.assertEqual(row["listing_age_days"], 3473)
        self.assertTrue(row["is_ordinary_share"])
        self.assertEqual(row["market_data_source"], "sharesansar_company_list")
        self.assertEqual(row["market_snapshot_version"], 2)

    def test_merges_latest_volume_into_company_fundamentals(self):
        rows = [{"symbol": "KAHL", "company_name": "Kalanga Hydro", "paid_up_capital": 1_000_000}]
        merged = _merge_latest_market_activity(
            rows,
            [{"Symbol": "KAHL", "LTP": "479.90", "% Change": "0.19", "Qty.": "22,727"}],
        )

        self.assertEqual(merged[0]["qty"], 22727.0)
        self.assertEqual(merged[0]["ltp"], 479.9)
        self.assertEqual(merged[0]["paid_up_capital"], 1_000_000)

    def test_discovers_all_sectors_and_paginates_at_api_limit(self):
        session = _FakeSession()
        rows = fetch_all_company_details(session=session)

        self.assertEqual(len(rows), 52)
        self.assertEqual({row["sector"] for row in rows}, {"Commercial Bank", "Hydropower"})
        self.assertEqual([request["start"] for request in session.requests], [0, 50, 0])
        self.assertTrue(all(request["length"] == PAGE_SIZE for request in session.requests))


if __name__ == "__main__":
    unittest.main()
