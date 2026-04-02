# Real-Time Futures Trading Terminal

A Python-based trading terminal that aggregates **real-time futures data**
from two sources and renders them in a colour-coded Rich CLI dashboard:

| Source | Data type | Requires key? |
|---|---|---|
| **[Massive API](https://massive.com)** (formerly Polygon.io) | Real-time REST snapshots + WebSocket streaming for futures contracts | Yes — [get a free key](https://massive.com/dashboard/api-keys) |
| **[Yahoo Finance](https://finance.yahoo.com)** via `yfinance` | ~15 min delayed OHLCV + 52-week range | No |

---

## Features

* **Live terminal** — auto-refreshing Rich table with colour-coded price
  changes (green ↑ / red ↓).
* **Massive API integration** — REST snapshots (`/v3/snapshot`) and a
  WebSocket streaming client (`FT.*` / `FQ.*` futures channels).
* **Free market data fallback** — Yahoo Finance via `yfinance`; works with
  zero configuration.
* **Configurable** — ticker lists, refresh interval, and API keys are all
  controlled through environment variables (`.env` file).
* **One-shot mode** — `--once` flag for scripting / CI pipelines.

---

## Quick start

```bash
# 1. Clone and enter the repo
git clone https://github.com/bullishoptionstrat-hub/Massive-Api-key.git
cd Massive-Api-key

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy the example env file and fill in your keys
cp .env.example .env
#  → set MASSIVE_API_KEY=<your key>  (optional but recommended)

# 4. Launch the live terminal
python terminal.py

# One-shot snapshot (no interactive mode)
python terminal.py --once

# Override refresh interval and tickers
python terminal.py --refresh 10 \
  --massive-tickers ES1!,NQ1!,CL1! \
  --yf-tickers     ES=F,NQ=F,CL=F
```

---

## Project structure

```
├── config.py            – Configuration (reads from .env)
├── massive_client.py    – Massive API REST + WebSocket client
├── free_market_client.py– Yahoo Finance client (yfinance)
├── terminal.py          – Rich CLI trading terminal
├── requirements.txt     – Python dependencies
├── .env.example         – Environment variable template
└── tests/
    └── test_clients.py  – Unit tests (no network required)
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `MASSIVE_API_KEY` | *(none)* | [Massive API key](https://massive.com/dashboard/api-keys) |
| `ALPHA_VANTAGE_API_KEY` | *(none)* | Optional Alpha Vantage key (reserved for future use) |
| `TERMINAL_REFRESH_SECONDS` | `5` | Auto-refresh interval |
| `FUTURES_TICKERS` | `ES1!,NQ1!,…` | Comma-separated Massive ticker list |

---

## Supported futures tickers

### Massive API (continuous-contract notation)
`ES1!` S&P 500 · `NQ1!` Nasdaq 100 · `YM1!` Dow Jones · `RTY1!` Russell 2000  
`CL1!` Crude Oil · `GC1!` Gold · `SI1!` Silver · `ZB1!` 30-yr T-Bond · `BTC1!` Bitcoin CME

### Yahoo Finance (append `=F` suffix)
`ES=F` · `NQ=F` · `YM=F` · `RTY=F` · `CL=F` · `GC=F` · `SI=F` · `ZB=F` · `6E=F` · `BTC=F`

---

## Running tests

```bash
pip install pytest
python -m pytest tests/ -v
```

All tests run entirely offline (external API calls are mocked).

---

## Using the Massive WebSocket stream

```python
from massive_client import MassiveFuturesClient
from typing import List

client = MassiveFuturesClient(api_key="<YOUR_KEY>")

def on_message(msgs: List) -> None:
    for m in msgs:
        print(m)

client.start_streaming(tickers=["ES1!", "NQ1!", "CL1!"], on_message=on_message)
# … runs on a daemon thread; call client.stop_streaming() to disconnect
```

---

## License

MIT

