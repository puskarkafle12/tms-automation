import unittest

from utils.external_data_sources.nepse_alpha import (
    NepseAlphaError,
    fetch_force_url_key,
    get_nepse_alpha_signals,
    parse_nepse_alpha_signals_html,
)
from utils.external_data_sources.nepse_alpha.screener import flatten_nepse_alpha_for_screener
from utils.strategies.normalize import normalize_nepse_alpha_payload

SAMPLE_SIGNALS_HTML = """
<div class="row">
  <div class="col-md-12">
    <div class="box">
      <div class="box-header with-border">
        <h3 class="box-title"><i class="fa fa-signal"></i> Stastical Performance</h3>
      </div>
      <div class="box-body table-responsive">
        <table class="table table-hover table-striped table-bordered">
          <thead>
            <tr class="bg-primary">
              <th class="text-bold text-center">Alpha <sub>Anualized</sub></th>
              <th class="text-bold text-center">Beta 3 Month </th>
              <th class="text-bold text-center">Sharpe Ratio <sub>Anualized</sub></th>
              <th class="text-bold text-center">Daily VAR@95%CI</th>
              <th class="text-bold text-center">50D σ</th>
              <th class="text-bold text-center">1 Year Yield</th>
              <th class="text-bold text-center">52 Weeks High/Low</th>
              <th class="text-bold text-center">LTP</th>
              <th class="text-bold text-center">All Time High</th>
              <th class="text-bold text-center">All Time Low</th>
            </tr>
          </thead>
          <tbody>
            <td>-2.75 %</td>
            <td>1.05</td>
            <td>-0.63</td>
            <td>-2.03 %</td>
            <td>Rs. 17.75</td>
            <td>-7.24 % </td>
            <td>NPR.1,207.80/NPR.905.00</td>
            <td>NPR. 950</td>
            <td>NPR. 1857</td>
            <td>NPR. 492</td>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>
<div class="row">
  <div class="col-md-6">
    <div class="box">
      <div class="box-header with-border">
        <h3 class="box-title text-bold"><i class="fa fa-angle-double-right"></i> Fundamental Signals</h3>
      </div>
      <div class="box-body table-responsive">
        <table class="table table-hover table-striped table-bordered">
          <thead>
            <tr class="bg-green">
              <th class="text-bold text-center">Indicators</th>
              <th class="text-bold text-center">ACLBSL</th>
              <th class="text-bold text-center text-nowrap">Sector High</th>
              <th class="text-bold text-center text-nowrap">Sector Low</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="text-bold" title="Price to Earnings Ratio">PE <sub>TTM</sub></td>
              <td class="text-nowrap">27.51</td>
              <td>153.45<sub>LLBS</sub></td>
              <td>18.29<sub>DDBL</sub></td>
            </tr>
            <tr>
              <td class="text-bold">Debt to Equity</td>
              <td class="text-nowrap">8.36</td>
              <td>14.40<sub>MATRI</sub></td>
              <td>2.27<sub>FMDBL</sub></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
  <div class="col-md-6">
    <div class="box">
      <div class="box-header with-border">
        <h3 class="box-title"><i class="fa fa-angle-double-right"></i> Technical Signals</h3>
      </div>
      <div class="box-body table-responsive">
        <table class="table table-hover table-striped table-bordered">
          <thead>
            <tr class="bg-teal">
              <th class="text-bold text-center">Indicators</th>
              <th class="text-bold text-center">ACLBSL</th>
              <th class="text-bold text-center">Sector High</th>
              <th class="text-bold text-center">Sector Low</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="text-bold">RSI 14</td>
              <td>46.39</td>
              <td>55.76<sub>VLBS</sub></td>
              <td>27.91<sub>SWASTIK</sub></td>
            </tr>
            <tr>
              <td class="text-bold">MACD</td>
              <td colspan="3"><span class="text-green">Bullish</span></td>
            </tr>
            <tr>
              <td class="text-bold">SMA 10</td>
              <td colspan="3"><i class="fa fa-sort-down zoom" style="color: red;" title="Price Below Moving Average"></i></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>
"""


class TestNepseAlphaParser(unittest.TestCase):
    def test_parse_sample_html_to_json(self):
        payload = parse_nepse_alpha_signals_html(SAMPLE_SIGNALS_HTML, "ACLBSL")

        self.assertEqual(payload["symbol"], "ACLBSL")
        self.assertEqual(payload["source"], "nepsealpha")
        self.assertEqual(payload["statistical_performance"]["ltp"], "NPR. 950")
        self.assertEqual(payload["statistical_performance"]["beta_3_month"], "1.05")
        self.assertEqual(payload["fundamental_signals"][0]["indicator"], "PE TTM")
        self.assertEqual(payload["fundamental_signals"][0]["symbol_value"], "27.51")
        self.assertEqual(payload["fundamental_signals"][0]["sector_high"]["symbol"], "LLBS")
        self.assertEqual(payload["technical_signals"][0]["symbol_value"], "46.39")
        self.assertEqual(payload["technical_signals"][1]["signal"], "Bullish")
        self.assertEqual(payload["technical_signals"][2]["signal"], "Price Below Moving Average")

    def test_parse_empty_html_raises(self):
        with self.assertRaises(NepseAlphaError):
            parse_nepse_alpha_signals_html("", "ACLBSL")

    def test_normalizers_accept_non_slash_52_week_range(self):
        cases = [
            ("NPR. 1,200.50 - NPR. 800.25", 1200.50, 800.25),
            ("NPR.530.29/NPR.429.63", 530.29, 429.63),
            ("NPR.1,033.28/NPR.635.00", 1033.28, 635.00),
        ]
        for raw_range, expected_high, expected_low in cases:
            with self.subTest(raw_range=raw_range):
                payload = {
                    "symbol": "CHCL",
                    "statistical_performance": {
                        "52_weeks_high_low": raw_range,
                        "ltp": "NPR. 900",
                    },
                    "fundamental_signals": [],
                    "technical_signals": [],
                }

                details = normalize_nepse_alpha_payload(payload)
                flat = flatten_nepse_alpha_for_screener(payload)

                self.assertEqual(details.fifty_two_week_high, expected_high)
                self.assertEqual(details.fifty_two_week_low, expected_low)
                self.assertEqual(flat["fifty_two_week_high"], expected_high)
                self.assertEqual(flat["fifty_two_week_low"], expected_low)


class TestNepseAlphaFetch(unittest.TestCase):
    def test_get_nepse_alpha_signals_uses_key_and_parser(self):
        from unittest.mock import patch

        with patch("utils.external_data_sources.nepse_alpha.client.fetch_force_url_key") as mock_key, patch(
            "utils.external_data_sources.nepse_alpha.client.fetch_signals_raw"
        ) as mock_signals:
            mock_key.return_value = {"key": "Gnw21LX9", "time": "2026-06-17 06:23:46", "cached": False}
            mock_signals.return_value = {"html": SAMPLE_SIGNALS_HTML}

            payload = get_nepse_alpha_signals("ACLBSL")

        self.assertEqual(payload["symbol"], "ACLBSL")
        self.assertEqual(payload["meta"]["fsk"], "Gnw21LX9")
        self.assertEqual(payload["statistical_performance"]["alpha_anualized"], "-2.75 %")
        mock_key.assert_called_once()
        mock_signals.assert_called_once_with("ACLBSL", "Gnw21LX9")

    def test_fetch_force_url_key_uses_cache(self):
        import utils.external_data_sources.nepse_alpha.client as module
        from unittest.mock import patch

        module._fsk_cache = {
            "key": "cached-key",
            "expires_at": module.time.time() + 3600,
            "meta": {"key": "cached-key", "time": "cached", "cached": False},
        }
        with patch("utils.external_data_sources.nepse_alpha.client._http_get") as mock_get:
            payload = fetch_force_url_key()
        self.assertEqual(payload["key"], "cached-key")
        self.assertTrue(payload["cached"])
        mock_get.assert_not_called()
        module._fsk_cache = {"key": None, "expires_at": 0.0, "meta": None}
