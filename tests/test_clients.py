"""
Unit tests for the trading terminal modules.

All external API calls (Massive SDK, yfinance) are patched so the test
suite runs without any network access or real API keys.
"""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub the ``massive`` package so tests run without it installed
# ---------------------------------------------------------------------------

def _make_massive_stub():
    massive = types.ModuleType("massive")
    massive.RESTClient = MagicMock()
    massive.WebSocketClient = MagicMock()

    ws_models = types.ModuleType("massive.websocket.models")
    ws_models.WebSocketMessage = object
    massive.websocket = types.ModuleType("massive.websocket")
    massive.websocket.models = ws_models

    sys.modules.setdefault("massive", massive)
    sys.modules.setdefault("massive.websocket", massive.websocket)
    sys.modules.setdefault("massive.websocket.models", ws_models)


_make_massive_stub()

# ---------------------------------------------------------------------------
# Now safe to import our modules
# ---------------------------------------------------------------------------

from config import Config, _parse_tickers  # noqa: E402
from massive_client import MassiveFuturesClient, _fmt_ticker  # noqa: E402
from free_market_client import FreeMarketClient, _safe  # noqa: E402


# ===========================================================================
# config.py
# ===========================================================================

class TestConfig(unittest.TestCase):

    def test_defaults(self):
        cfg = Config()
        self.assertIsInstance(cfg.default_massive_tickers, list)
        self.assertIsInstance(cfg.default_yf_tickers, list)
        self.assertGreater(len(cfg.default_massive_tickers), 0)
        self.assertGreater(len(cfg.default_yf_tickers), 0)

    def test_has_massive_key_false_when_empty(self):
        cfg = Config(massive_api_key="")
        self.assertFalse(cfg.has_massive_key())

    def test_has_massive_key_false_when_placeholder(self):
        cfg = Config(massive_api_key="your_massive_api_key_here")
        self.assertFalse(cfg.has_massive_key())

    def test_has_massive_key_true_when_real(self):
        cfg = Config(massive_api_key="abc123xyz")
        self.assertTrue(cfg.has_massive_key())

    def test_has_alpha_vantage_key_false_when_placeholder(self):
        cfg = Config(alpha_vantage_api_key="your_alpha_vantage_key_here")
        self.assertFalse(cfg.has_alpha_vantage_key())

    def test_has_alpha_vantage_key_true_when_real(self):
        cfg = Config(alpha_vantage_api_key="DEMO")
        self.assertTrue(cfg.has_alpha_vantage_key())

    def test_parse_tickers_strips_whitespace(self):
        result = _parse_tickers("  ES1! , NQ1!,  CL1!  ")
        self.assertEqual(result, ["ES1!", "NQ1!", "CL1!"])

    def test_parse_tickers_ignores_empty_entries(self):
        result = _parse_tickers("ES1!,,NQ1!")
        self.assertEqual(result, ["ES1!", "NQ1!"])

    def test_refresh_seconds_default(self):
        cfg = Config()
        self.assertEqual(cfg.refresh_seconds, 5)


# ===========================================================================
# massive_client.py
# ===========================================================================

class TestFmtTicker(unittest.TestCase):
    def test_already_prefixed(self):
        self.assertEqual(_fmt_ticker("F:ES1!"), "F:ES1!")

    def test_adds_prefix(self):
        self.assertEqual(_fmt_ticker("ES1!"), "F:ES1!")

    def test_empty_string(self):
        self.assertEqual(_fmt_ticker(""), "F:")


class TestMassiveFuturesClientInit(unittest.TestCase):
    def test_raises_on_empty_key(self):
        with self.assertRaises(ValueError):
            MassiveFuturesClient("")

    def test_accepts_valid_key(self):
        client = MassiveFuturesClient("test_key_123")
        self.assertEqual(client.api_key, "test_key_123")


class TestMassiveFuturesClientSnapshot(unittest.TestCase):
    """get_snapshot should return one dict per ticker even when REST calls fail."""

    def setUp(self):
        self.client = MassiveFuturesClient("test_key")
        # Simulate a REST error for every call
        self.client._rest.list_snapshot_all.side_effect = RuntimeError("rate limited")
        self.client._rest.get_last_trade.side_effect = RuntimeError("rate limited")
        self.client._rest.get_previous_close_agg.side_effect = RuntimeError("rate limited")

    def test_returns_list_same_length_as_tickers(self):
        tickers = ["ES1!", "NQ1!", "CL1!"]
        result = self.client.get_snapshot(tickers)
        self.assertEqual(len(result), 3)

    def test_records_have_expected_keys(self):
        result = self.client.get_snapshot(["ES1!"])
        self.assertIn("ticker", result[0])
        self.assertIn("name", result[0])
        self.assertIn("last_price", result[0])
        self.assertIn("change", result[0])
        self.assertIn("change_pct", result[0])

    def test_values_are_none_on_error(self):
        result = self.client.get_snapshot(["ES1!"])
        self.assertIsNone(result[0]["last_price"])
        self.assertIsNone(result[0]["change"])

    def test_ticker_preserved_in_record(self):
        result = self.client.get_snapshot(["NQ1!"])
        self.assertEqual(result[0]["ticker"], "NQ1!")


class TestMassiveFuturesClientAggs(unittest.TestCase):
    """get_aggregates should surface SDK errors as an empty list."""

    def setUp(self):
        self.client = MassiveFuturesClient("test_key")
        self.client._rest.list_aggs.side_effect = RuntimeError("no data")

    def test_returns_empty_list_on_error(self):
        result = self.client.get_aggregates("ES1!")
        self.assertEqual(result, [])

    def test_returns_list_on_success(self):
        mock_bar = MagicMock()
        self.client._rest.list_aggs.side_effect = None
        self.client._rest.list_aggs.return_value = iter([mock_bar, mock_bar])
        result = self.client.get_aggregates("ES1!", limit=2)
        self.assertEqual(len(result), 2)


class TestMassiveFuturesClientLastTrade(unittest.TestCase):
    def setUp(self):
        self.client = MassiveFuturesClient("test_key")

    def test_returns_none_on_error(self):
        self.client._rest.get_last_trade.side_effect = RuntimeError("error")
        self.assertIsNone(self.client.get_last_trade("ES1!"))

    def test_returns_trade_on_success(self):
        mock_trade = MagicMock(price=4800.0)
        # The RESTClient mock is a shared singleton; reset the side_effect that
        # test_returns_none_on_error may have set on the same mock object.
        self.client._rest.get_last_trade.side_effect = None
        self.client._rest.get_last_trade.return_value = mock_trade
        result = self.client.get_last_trade("ES1!")
        self.assertEqual(result.price, 4800.0)


# ===========================================================================
# free_market_client.py
# ===========================================================================

class TestSafeHelper(unittest.TestCase):
    def test_returns_float(self):
        obj = MagicMock(price=4800.5)
        self.assertEqual(_safe(obj, "price"), 4800.5)

    def test_returns_none_on_missing_attr(self):
        obj = MagicMock(spec=[])  # no attributes
        self.assertIsNone(_safe(obj, "price"))

    def test_returns_none_on_exception(self):
        class Bad:
            @property
            def price(self):
                raise ValueError("oops")

        self.assertIsNone(_safe(Bad(), "price"))


class TestFreeMarketClientSnapshot(unittest.TestCase):
    """get_snapshot should return one dict per ticker, handling yfinance errors."""

    @patch("free_market_client.yf")
    def test_returns_list_same_length(self, mock_yf):
        # Simulate yf.download raising an error
        mock_yf.download.side_effect = RuntimeError("network error")
        ticker_obj = MagicMock()
        ticker_obj.fast_info = MagicMock(
            last_price=4800.0,
            open=4750.0,
            day_high=4820.0,
            day_low=4730.0,
            previous_close=4788.0,
            three_month_average_volume=1_200_000,
            year_high=4900.0,
            year_low=3500.0,
        )
        mock_yf.Ticker.return_value = ticker_obj

        client = FreeMarketClient(["ES=F", "NQ=F", "CL=F"])
        result = client.get_snapshot()
        self.assertEqual(len(result), 3)

    @patch("free_market_client.yf")
    def test_records_have_expected_keys(self, mock_yf):
        mock_yf.download.side_effect = RuntimeError("network error")
        ticker_obj = MagicMock()
        ticker_obj.fast_info = MagicMock(
            last_price=4800.0,
            previous_close=4788.0,
            open=4750.0,
            day_high=4820.0,
            day_low=4730.0,
            three_month_average_volume=1_200_000,
            year_high=4900.0,
            year_low=3500.0,
        )
        mock_yf.Ticker.return_value = ticker_obj

        client = FreeMarketClient(["ES=F"])
        result = client.get_snapshot()
        keys = result[0].keys()
        for k in ("ticker", "name", "last_price", "change", "change_pct", "52w_high", "52w_low"):
            self.assertIn(k, keys)

    @patch("free_market_client.yf")
    def test_change_computed_correctly(self, mock_yf):
        mock_yf.download.side_effect = RuntimeError("network error")
        ticker_obj = MagicMock()
        ticker_obj.fast_info = MagicMock(
            last_price=4800.0,
            previous_close=4750.0,
            open=4755.0,
            day_high=4810.0,
            day_low=4740.0,
            three_month_average_volume=None,
            year_high=None,
            year_low=None,
        )
        mock_yf.Ticker.return_value = ticker_obj

        client = FreeMarketClient(["ES=F"])
        result = client.get_snapshot()
        rec = result[0]
        self.assertAlmostEqual(rec["change"], 50.0, places=2)
        self.assertAlmostEqual(rec["change_pct"], 50.0 / 4750.0 * 100, places=4)

    @patch("free_market_client.yf")
    def test_all_none_when_both_sources_fail(self, mock_yf):
        mock_yf.download.side_effect = RuntimeError("error")
        ticker_obj = MagicMock()
        ticker_obj.fast_info = MagicMock(
            last_price=None,
            previous_close=None,
            open=None,
            day_high=None,
            day_low=None,
            three_month_average_volume=None,
            year_high=None,
            year_low=None,
        )
        mock_yf.Ticker.return_value = ticker_obj

        client = FreeMarketClient(["XX=F"])
        result = client.get_snapshot()
        rec = result[0]
        self.assertIsNone(rec["last_price"])
        self.assertIsNone(rec["change"])


class TestFreeMarketClientHistory(unittest.TestCase):
    @patch("free_market_client.yf.Ticker")
    def test_returns_none_on_error(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = RuntimeError("error")
        mock_ticker_cls.return_value = mock_ticker

        client = FreeMarketClient(["ES=F"])
        result = client.get_history("ES=F")
        self.assertIsNone(result)

    @patch("free_market_client.yf.Ticker")
    def test_returns_dataframe_on_success(self, mock_ticker_cls):
        import pandas as pd

        mock_ticker = MagicMock()
        df = pd.DataFrame({"Close": [4800.0]})
        mock_ticker.history.return_value = df
        mock_ticker_cls.return_value = mock_ticker

        client = FreeMarketClient(["ES=F"])
        result = client.get_history("ES=F")
        self.assertIsNotNone(result)
        self.assertIn("Close", result.columns)


if __name__ == "__main__":
    unittest.main()
