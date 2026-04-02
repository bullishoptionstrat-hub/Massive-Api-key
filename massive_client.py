"""
Massive API client for real-time futures data.

Wraps both the REST and WebSocket interfaces of the Massive (formerly
Polygon.io) Python SDK to expose futures snapshots, OHLCV aggregates,
last-trade lookups, and a live-streaming feed.

Docs: https://massive.com/docs/rest/futures/overview
SDK:  pip install -U massive
"""

import logging
import threading
from datetime import date
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Ticker display names for common continuous-contract symbols
FUTURES_NAMES: Dict[str, str] = {
    "ES1!": "S&P 500 E-mini",
    "NQ1!": "Nasdaq 100 E-mini",
    "YM1!": "Dow Jones E-mini",
    "RTY1!": "Russell 2000 E-mini",
    "CL1!": "Crude Oil WTI",
    "GC1!": "Gold",
    "SI1!": "Silver",
    "ZB1!": "US 30-Year T-Bond",
    "6E1!": "Euro FX",
    "BTC1!": "Bitcoin CME",
}

DEFAULT_TICKERS: List[str] = list(FUTURES_NAMES.keys())


def _fmt_ticker(ticker: str) -> str:
    """Return the Massive-prefixed ticker (e.g. ``F:ES1!``)."""
    return ticker if ticker.startswith("F:") else f"F:{ticker}"


class MassiveFuturesClient:
    """
    Thin wrapper around the official ``massive`` Python SDK tailored for
    futures market data.

    Parameters
    ----------
    api_key:
        Massive API key obtained from https://massive.com/dashboard/api-keys
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("A Massive API key is required.")

        from massive import RESTClient  # imported here so the module can be
        # imported even when the package is absent (tests can mock it)

        self.api_key = api_key
        self._rest = RESTClient(api_key=api_key)
        self._ws_client: Any = None
        self._ws_thread: Optional[threading.Thread] = None
        self._streaming = False

    # ------------------------------------------------------------------
    # REST helpers
    # ------------------------------------------------------------------

    def get_snapshot(self, tickers: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Return a list of snapshot dicts for the given futures tickers.

        Each dict contains at minimum: ``ticker``, ``name``, ``last_price``,
        ``prev_close``, ``change``, ``change_pct``, and ``volume``.

        Falls back gracefully to the previous close when real-time data is
        unavailable on the free tier.
        """
        tickers = tickers or DEFAULT_TICKERS
        results: List[Dict[str, Any]] = []

        for raw in tickers:
            fmt = _fmt_ticker(raw)
            record: Dict[str, Any] = {
                "ticker": raw,
                "name": FUTURES_NAMES.get(raw, raw),
                "last_price": None,
                "open": None,
                "high": None,
                "low": None,
                "prev_close": None,
                "change": None,
                "change_pct": None,
                "volume": None,
            }
            try:
                # v3 universal snapshot endpoint supports all asset classes
                # including futures via the F: ticker prefix
                snaps = list(
                    self._rest.list_snapshot_all(
                        params={"ticker.any_of": fmt}
                    )
                )
                snap = snaps[0] if snaps else None
                if snap:
                    day = getattr(snap, "day", None)
                    prev = getattr(snap, "prev_day", None)
                    if day:
                        record["last_price"] = getattr(day, "c", None)
                        record["open"] = getattr(day, "o", None)
                        record["high"] = getattr(day, "h", None)
                        record["low"] = getattr(day, "l", None)
                        record["volume"] = getattr(day, "v", None)
                    if prev:
                        record["prev_close"] = getattr(prev, "c", None)
                    if record["last_price"] and record["prev_close"]:
                        record["change"] = record["last_price"] - record["prev_close"]
                        record["change_pct"] = (
                            record["change"] / record["prev_close"] * 100
                        )
            except Exception as exc:
                logger.debug("Snapshot failed for %s: %s", fmt, exc)
                # Attempt last-trade lookup as fallback
                try:
                    trade = self._rest.get_last_trade(fmt)
                    if trade:
                        record["last_price"] = getattr(trade, "price", None)
                        record["volume"] = getattr(trade, "size", None)
                except Exception as exc2:
                    logger.debug("Last-trade fallback failed for %s: %s", fmt, exc2)

                # Previous close via aggs
                try:
                    prev_data = self._rest.get_previous_close_agg(fmt)
                    if prev_data:
                        entry = prev_data[0] if isinstance(prev_data, list) else prev_data
                        record["prev_close"] = getattr(entry, "c", None)
                        if record["last_price"] and record["prev_close"]:
                            record["change"] = record["last_price"] - record["prev_close"]
                            record["change_pct"] = (
                                record["change"] / record["prev_close"] * 100
                            )
                except Exception as exc3:
                    logger.debug("Prev-close fallback failed for %s: %s", fmt, exc3)

            results.append(record)
        return results

    def get_aggregates(
        self,
        ticker: str,
        multiplier: int = 1,
        timespan: str = "minute",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 50,
    ) -> List[Any]:
        """
        Return OHLCV aggregate bars for *ticker* for the given date range.

        Parameters
        ----------
        ticker:
            Futures symbol, e.g. ``"ES1!"`` or ``"F:ES1!"``.
        multiplier:
            Bar size multiplier (e.g. ``1`` for 1-minute bars).
        timespan:
            Bar size unit: ``"minute"``, ``"hour"``, ``"day"``, …
        from_date:
            Start date as ``"YYYY-MM-DD"`` (defaults to today).
        to_date:
            End date as ``"YYYY-MM-DD"`` (defaults to today).
        limit:
            Maximum number of bars to return per page.
        """
        fmt = _fmt_ticker(ticker)
        today = date.today().isoformat()
        from_date = from_date or today
        to_date = to_date or today
        try:
            return list(
                self._rest.list_aggs(
                    ticker=fmt,
                    multiplier=multiplier,
                    timespan=timespan,
                    from_=from_date,
                    to=to_date,
                    limit=limit,
                )
            )
        except Exception as exc:
            logger.error("get_aggregates failed for %s: %s", fmt, exc)
            return []

    def get_last_trade(self, ticker: str) -> Optional[Any]:
        """Return the most recent trade for *ticker*."""
        fmt = _fmt_ticker(ticker)
        try:
            return self._rest.get_last_trade(fmt)
        except Exception as exc:
            logger.error("get_last_trade failed for %s: %s", fmt, exc)
            return None

    # ------------------------------------------------------------------
    # WebSocket streaming
    # ------------------------------------------------------------------

    def start_streaming(
        self,
        tickers: Optional[List[str]] = None,
        on_message: Optional[Callable] = None,
    ) -> None:
        """
        Open a persistent WebSocket connection and stream real-time futures
        trades and quotes.

        The *on_message* callback receives ``List[WebSocketMessage]`` on every
        server push.  If omitted, messages are logged at DEBUG level.

        Streaming runs on a daemon thread; call :meth:`stop_streaming` to
        disconnect.
        """
        if self._streaming:
            logger.warning("Streaming is already active.")
            return

        from massive import WebSocketClient  # deferred import

        tickers = tickers or DEFAULT_TICKERS[:5]
        # FT.{ticker} = futures trades,  FQ.{ticker} = futures quotes
        subscriptions = [f"FT.{_fmt_ticker(t)}" for t in tickers] + [
            f"FQ.{_fmt_ticker(t)}" for t in tickers
        ]

        def _default_handler(msgs: List[Any]) -> None:
            for m in msgs:
                logger.debug("WS: %s", m)

        handler = on_message or _default_handler

        try:
            self._ws_client = WebSocketClient(
                api_key=self.api_key,
                feed="futures",
                market="futures",
                subscriptions=subscriptions,
            )
            self._streaming = True
            self._ws_thread = threading.Thread(
                target=self._ws_client.run,
                kwargs={"handle_msg": handler},
                daemon=True,
                name="massive-ws",
            )
            self._ws_thread.start()
            logger.info("WebSocket streaming started — subscriptions: %s", subscriptions)
        except Exception as exc:
            self._streaming = False
            logger.error("Failed to start WebSocket streaming: %s", exc)

    def stop_streaming(self) -> None:
        """Close the WebSocket connection and wait for the thread to finish."""
        self._streaming = False
        if self._ws_client is not None:
            try:
                self._ws_client.close()
            except Exception:
                pass
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=5)
        logger.info("WebSocket streaming stopped.")
