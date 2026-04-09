"""
Real-Time Futures Trading Terminal
===================================
A Rich-powered CLI terminal that displays live futures data from two sources:

  1. **Massive API** (formerly Polygon.io) — REST + WebSocket, requires an
     API key (https://massive.com/dashboard/api-keys).

  2. **Yahoo Finance** via yfinance — free, no key required, ~15 min delayed.

Usage
-----
  # Interactive terminal (auto-refreshes every N seconds)
  python terminal.py

  # One-shot snapshot then exit
  python terminal.py --once

  # Use a specific refresh interval (seconds)
  python terminal.py --refresh 10

  # Override default tickers (comma-separated)
  python terminal.py --massive-tickers ES1!,NQ1!,CL1! --yf-tickers ES=F,NQ=F,CL=F

Environment
-----------
Copy ``.env.example`` to ``.env`` and fill in your keys before running.
"""

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import Config, config as default_config
from free_market_client import FreeMarketClient

console = Console()
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_price(value: Optional[float], decimals: int = 2) -> str:
    if value is None:
        return "[dim]N/A[/dim]"
    return f"{value:,.{decimals}f}"


def _fmt_change(change: Optional[float], pct: Optional[float]) -> str:
    if change is None or pct is None:
        return "[dim]N/A[/dim]"
    colour = "green" if change >= 0 else "red"
    sign = "+" if change >= 0 else ""
    return f"[{colour}]{sign}{change:,.2f}  ({sign}{pct:.2f}%)[/{colour}]"


def _fmt_volume(vol: Optional[float]) -> str:
    if vol is None:
        return "[dim]N/A[/dim]"
    if vol >= 1_000_000:
        return f"{vol / 1_000_000:.2f}M"
    if vol >= 1_000:
        return f"{vol / 1_000:.1f}K"
    return str(int(vol))


def _market_status() -> Text:
    now = datetime.now(timezone.utc)
    # Simple weekday/hour check for rough US futures session indication
    weekday = now.weekday()  # 0=Mon … 6=Sun
    hour = now.hour
    # Futures trade Sunday 6 PM–Friday 5 PM ET (≈ UTC-5/-4)
    # Rough UTC equivalent: Sun 23:00 – Fri 22:00 UTC
    is_open = not (weekday == 5 or (weekday == 6 and hour < 23) or (weekday == 4 and hour >= 22))
    if is_open:
        return Text("● FUTURES SESSION", style="bold green")
    return Text("● SESSION CLOSED", style="bold red")


# ---------------------------------------------------------------------------
# Table builders
# ---------------------------------------------------------------------------

def _massive_table(rows: List[Dict[str, Any]]) -> Table:
    tbl = Table(
        title="[bold cyan]Massive API — Real-Time Futures[/bold cyan]",
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold white on dark_blue",
        expand=True,
    )
    tbl.add_column("Symbol", style="bold yellow", no_wrap=True, min_width=8)
    tbl.add_column("Name", style="white", min_width=22)
    tbl.add_column("Last", justify="right", min_width=12)
    tbl.add_column("Change / %", justify="right", min_width=20)
    tbl.add_column("Open", justify="right", min_width=10)
    tbl.add_column("High", justify="right", min_width=10)
    tbl.add_column("Low", justify="right", min_width=10)
    tbl.add_column("Volume", justify="right", min_width=8)

    for r in rows:
        tbl.add_row(
            r.get("ticker", ""),
            r.get("name", ""),
            _fmt_price(r.get("last_price")),
            _fmt_change(r.get("change"), r.get("change_pct")),
            _fmt_price(r.get("open")),
            _fmt_price(r.get("high")),
            _fmt_price(r.get("low")),
            _fmt_volume(r.get("volume")),
        )
    return tbl


def _yf_table(rows: List[Dict[str, Any]]) -> Table:
    tbl = Table(
        title="[bold cyan]Yahoo Finance — Free Market Data (≈15 min delayed)[/bold cyan]",
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold white on dark_green",
        expand=True,
    )
    tbl.add_column("Symbol", style="bold yellow", no_wrap=True, min_width=8)
    tbl.add_column("Name", style="white", min_width=22)
    tbl.add_column("Last", justify="right", min_width=12)
    tbl.add_column("Change / %", justify="right", min_width=20)
    tbl.add_column("52W High", justify="right", min_width=10)
    tbl.add_column("52W Low", justify="right", min_width=10)
    tbl.add_column("Volume", justify="right", min_width=8)

    for r in rows:
        tbl.add_row(
            r.get("ticker", ""),
            r.get("name", ""),
            _fmt_price(r.get("last_price")),
            _fmt_change(r.get("change"), r.get("change_pct")),
            _fmt_price(r.get("52w_high")),
            _fmt_price(r.get("52w_low")),
            _fmt_volume(r.get("volume")),
        )
    return tbl


def _header(cfg: Config) -> Panel:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    status = _market_status()

    key_status = Text()
    if cfg.has_massive_key():
        key_status.append("Massive API ✓", style="green")
    else:
        key_status.append("Massive API (key not set)", style="yellow")
    key_status.append("  ")
    key_status.append("Yahoo Finance ✓", style="green")

    content = Text.assemble(
        ("Real-Time Futures Trading Terminal\n", "bold white"),
        (f"{ts}  ", "dim"),
        status,
        ("  │  ", "dim"),
        key_status,
    )
    return Panel(content, style="bold on black", padding=(0, 2))


def _footer(refresh: int) -> Text:
    return Text(
        f"Auto-refreshes every {refresh}s  │  Press Ctrl+C to quit",
        style="dim",
        justify="center",
    )


# ---------------------------------------------------------------------------
# Data fetch helpers
# ---------------------------------------------------------------------------

def _fetch_massive(cfg: Config, tickers: List[str]) -> List[Dict[str, Any]]:
    if not cfg.has_massive_key():
        return []
    try:
        from massive_client import MassiveFuturesClient

        client = MassiveFuturesClient(cfg.massive_api_key)
        return client.get_snapshot(tickers)
    except Exception as exc:
        logging.getLogger(__name__).warning("Massive fetch failed: %s", exc)
        return []


def _fetch_yf(yf_client: FreeMarketClient) -> List[Dict[str, Any]]:
    try:
        return yf_client.get_snapshot()
    except Exception as exc:
        logging.getLogger(__name__).warning("Yahoo Finance fetch failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Renderable builder
# ---------------------------------------------------------------------------

def build_display(
    massive_rows: List[Dict[str, Any]],
    yf_rows: List[Dict[str, Any]],
    cfg: Config,
) -> Columns:
    parts: List[Any] = [_header(cfg)]

    if massive_rows:
        parts.append(_massive_table(massive_rows))
    else:
        if cfg.has_massive_key():
            parts.append(
                Panel(
                    "[yellow]Massive: no data returned (check tier / market hours)[/yellow]",
                    title="Massive API",
                )
            )
        else:
            parts.append(
                Panel(
                    "[yellow]Set MASSIVE_API_KEY in .env to enable Massive real-time data.[/yellow]",
                    title="Massive API",
                )
            )

    if yf_rows:
        parts.append(_yf_table(yf_rows))

    parts.append(_footer(cfg.refresh_seconds))
    return Columns(parts, equal=False, expand=True)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_terminal(
    cfg: Config,
    massive_tickers: Optional[List[str]] = None,
    yf_tickers: Optional[List[str]] = None,
    once: bool = False,
) -> None:
    massive_tickers = massive_tickers or cfg.default_massive_tickers
    yf_tickers = yf_tickers or cfg.default_yf_tickers
    yf_client = FreeMarketClient(yf_tickers)

    # Graceful shutdown on SIGINT / SIGTERM
    _stop = {"flag": False}

    def _signal_handler(sig: int, frame: Any) -> None:
        _stop["flag"] = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    def _fetch_all():
        m_rows = _fetch_massive(cfg, massive_tickers)
        y_rows = _fetch_yf(yf_client)
        return m_rows, y_rows

    if once:
        m_rows, y_rows = _fetch_all()
        console.print(build_display(m_rows, y_rows, cfg))
        return

    with Live(console=console, refresh_per_second=1, screen=True) as live:
        while not _stop["flag"]:
            m_rows, y_rows = _fetch_all()
            live.update(build_display(m_rows, y_rows, cfg))
            for _ in range(cfg.refresh_seconds * 10):
                if _stop["flag"]:
                    break
                time.sleep(0.1)

    console.print("[bold green]Terminal closed.[/bold green]")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Real-time futures trading terminal (Massive API + Yahoo Finance).",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Print a single snapshot and exit (non-interactive).",
    )
    p.add_argument(
        "--refresh",
        type=int,
        metavar="SECONDS",
        help="Override the auto-refresh interval (default: from .env or 5).",
    )
    p.add_argument(
        "--massive-tickers",
        metavar="LIST",
        help="Comma-separated Massive futures tickers, e.g. ES1!,NQ1!",
    )
    p.add_argument(
        "--yf-tickers",
        metavar="LIST",
        help="Comma-separated Yahoo Finance futures tickers, e.g. ES=F,NQ=F",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose/debug logging.",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    cfg = default_config
    if args.refresh is not None:
        cfg.refresh_seconds = args.refresh

    m_tickers = [t.strip() for t in args.massive_tickers.split(",")] if args.massive_tickers else None
    y_tickers = [t.strip() for t in args.yf_tickers.split(",")] if args.yf_tickers else None

    run_terminal(cfg, massive_tickers=m_tickers, yf_tickers=y_tickers, once=args.once)


if __name__ == "__main__":
    main()
