"""
Free market data client using Yahoo Finance (yfinance).

yfinance is a community library that wraps Yahoo Finance's public API at
no cost and requires no API key.  It supports real-time (15-minute delayed)
quotes, historical OHLCV data, and a wide range of futures contracts.

Futures continuous-contract tickers on Yahoo Finance:
  ES=F  → S&P 500 E-mini
  NQ=F  → Nasdaq 100 E-mini
  YM=F  → Dow Jones E-mini
  RTY=F → Russell 2000 E-mini
  CL=F  → Crude Oil WTI
  GC=F  → Gold
  SI=F  → Silver
  ZB=F  → US 30-Year T-Bond
  6E=F  → Euro FX
  BTC=F → Bitcoin CME
"""

import logging
from typing import Any, Dict, List, Optional

import yfinance as yf

logger = logging.getLogger(__name__)

# Human-readable names for the most common continuous futures tickers
FUTURES_NAMES: Dict[str, str] = {
    "ES=F": "S&P 500 E-mini",
    "NQ=F": "Nasdaq 100 E-mini",
    "YM=F": "Dow Jones E-mini",
    "RTY=F": "Russell 2000 E-mini",
    "CL=F": "Crude Oil WTI",
    "GC=F": "Gold",
    "SI=F": "Silver",
    "ZB=F": "US 30-Year T-Bond",
    "6E=F": "Euro FX",
    "BTC=F": "Bitcoin CME",
}

DEFAULT_TICKERS: List[str] = list(FUTURES_NAMES.keys())


class FreeMarketClient:
    """
    Fetches market and futures data from Yahoo Finance using yfinance.

    No API key required.  Data is typically delayed by 10–15 minutes for
    futures contracts.
    """

    def __init__(self, tickers: Optional[List[str]] = None) -> None:
        self.tickers = tickers or DEFAULT_TICKERS

    # ------------------------------------------------------------------
    # Snapshot (latest price + day stats)
    # ------------------------------------------------------------------

    def get_snapshot(self, tickers: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Return a list of snapshot dicts for the given Yahoo Finance futures
        tickers.

        Each dict contains: ``ticker``, ``name``, ``last_price``, ``open``,
        ``high``, ``low``, ``prev_close``, ``change``, ``change_pct``,
        ``volume``, ``52w_high``, ``52w_low``.
        """
        tickers = tickers or self.tickers
        results: List[Dict[str, Any]] = []

        try:
            data = yf.download(
                tickers=tickers,
                period="2d",
                interval="1m",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception as exc:
            logger.error("yf.download failed: %s", exc)
            data = None

        for ticker in tickers:
            record: Dict[str, Any] = {
                "ticker": ticker,
                "name": FUTURES_NAMES.get(ticker, ticker),
                "last_price": None,
                "open": None,
                "high": None,
                "low": None,
                "prev_close": None,
                "change": None,
                "change_pct": None,
                "volume": None,
                "52w_high": None,
                "52w_low": None,
            }

            # --- fast_info is the lightest-weight route ---
            try:
                obj = yf.Ticker(ticker)
                fi = obj.fast_info
                record["last_price"] = _safe(fi, "last_price")
                record["open"] = _safe(fi, "open")
                record["high"] = _safe(fi, "day_high")
                record["low"] = _safe(fi, "day_low")
                record["prev_close"] = _safe(fi, "previous_close")
                record["volume"] = _safe(fi, "three_month_average_volume")
                record["52w_high"] = _safe(fi, "year_high")
                record["52w_low"] = _safe(fi, "year_low")

                lp = record["last_price"]
                pc = record["prev_close"]
                if lp is not None and pc and pc != 0:
                    record["change"] = lp - pc
                    record["change_pct"] = (lp - pc) / pc * 100
            except Exception as exc:
                logger.debug("fast_info failed for %s: %s", ticker, exc)

            # Fall back to the downloaded OHLCV frame if fast_info gave nothing
            if record["last_price"] is None and data is not None:
                try:
                    frame = (
                        data[ticker] if len(tickers) > 1 else data
                    )
                    if not frame.empty:
                        latest = frame.dropna().iloc[-1]
                        record["last_price"] = float(latest["Close"])
                        record["open"] = float(latest["Open"])
                        record["high"] = float(latest["High"])
                        record["low"] = float(latest["Low"])
                        record["volume"] = float(latest["Volume"])
                except Exception as exc:
                    logger.debug("OHLCV fallback failed for %s: %s", ticker, exc)

            results.append(record)

        return results

    # ------------------------------------------------------------------
    # Historical OHLCV
    # ------------------------------------------------------------------

    def get_history(
        self,
        ticker: str,
        period: str = "5d",
        interval: str = "1m",
    ) -> Any:
        """
        Return a ``pandas.DataFrame`` with OHLCV history for *ticker*.

        Parameters
        ----------
        ticker:
            Yahoo Finance symbol, e.g. ``"ES=F"``.
        period:
            Data window: ``"1d"``, ``"5d"``, ``"1mo"``, ``"3mo"``, … or
            ``"max"`` for the full available history.
        interval:
            Bar size: ``"1m"``, ``"5m"``, ``"15m"``, ``"1h"``, ``"1d"``, …
        """
        try:
            return yf.Ticker(ticker).history(period=period, interval=interval)
        except Exception as exc:
            logger.error("get_history failed for %s: %s", ticker, exc)
            return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(obj: Any, attr: str) -> Optional[float]:
    """Return ``getattr(obj, attr)`` coerced to float, or ``None`` on failure."""
    try:
        val = getattr(obj, attr, None)
        return float(val) if val is not None else None
    except Exception:
        return None
