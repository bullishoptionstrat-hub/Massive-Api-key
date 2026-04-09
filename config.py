"""
Configuration management for the trading terminal.

Loads settings from environment variables (or a .env file) and provides
validated defaults used throughout the application.
"""

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # --- API keys ---
    massive_api_key: str = field(default_factory=lambda: os.getenv("MASSIVE_API_KEY", ""))
    alpha_vantage_api_key: str = field(
        default_factory=lambda: os.getenv("ALPHA_VANTAGE_API_KEY", "")
    )

    # --- Terminal behaviour ---
    refresh_seconds: int = field(
        default_factory=lambda: int(os.getenv("TERMINAL_REFRESH_SECONDS", "5"))
    )

    # --- Default futures tickers ---
    # Massive (Polygon-style) continuous-contract notation: ES1!, NQ1!, …
    default_massive_tickers: List[str] = field(
        default_factory=lambda: _parse_tickers(
            os.getenv("FUTURES_TICKERS", "ES1!,NQ1!,YM1!,RTY1!,CL1!,GC1!,SI1!,ZB1!")
        )
    )

    # Yahoo Finance continuous-contract notation (appended "=F")
    default_yf_tickers: List[str] = field(
        default_factory=lambda: [
            "ES=F",   # S&P 500 E-mini
            "NQ=F",   # Nasdaq 100 E-mini
            "YM=F",   # Dow Jones E-mini
            "RTY=F",  # Russell 2000 E-mini
            "CL=F",   # Crude Oil WTI
            "GC=F",   # Gold
            "SI=F",   # Silver
            "ZB=F",   # US 30-Year T-Bond
            "6E=F",   # Euro FX
            "BTC=F",  # Bitcoin CME
        ]
    )

    def has_massive_key(self) -> bool:
        return bool(self.massive_api_key and self.massive_api_key != "your_massive_api_key_here")

    def has_alpha_vantage_key(self) -> bool:
        return bool(
            self.alpha_vantage_api_key
            and self.alpha_vantage_api_key != "your_alpha_vantage_key_here"
        )


def _parse_tickers(raw: str) -> List[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


# Module-level singleton
config = Config()
