"""Environment-driven configuration for the marketdata package.

Reads from environment variables (loaded via python-dotenv by callers) and
exposes a typed ``MarketDataConfig`` snapshot. No globals; pass the config
around explicitly so tests can swap it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_DB_PATH = "data/marketdata.duckdb"
DEFAULT_PARQUET_DIR = "data/parquet"
DEFAULT_FEED = "iex"  # Alpaca free tier
DEFAULT_BASE_URL = "https://paper-api.alpaca.markets"
DEFAULT_DATA_URL = "https://data.alpaca.markets"
DEFAULT_STREAM_URL = "wss://stream.data.alpaca.markets/v2/iex"


def _parse_watchlist(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


@dataclass(frozen=True)
class MarketDataConfig:
    """Resolved marketdata configuration snapshot."""

    alpaca_key_id: str | None
    alpaca_secret_key: str | None
    alpaca_base_url: str
    alpaca_data_url: str
    alpaca_stream_url: str
    alpaca_feed: str
    db_path: Path
    parquet_dir: Path
    watchlist: list[str] = field(default_factory=list)
    options_tier: str = "free"  # 'free' | 'algo_trader_plus'

    @property
    def has_credentials(self) -> bool:
        return bool(self.alpaca_key_id and self.alpaca_secret_key)

    @property
    def is_paper(self) -> bool:
        return "paper" in self.alpaca_base_url


def load_config(env: dict[str, str] | None = None) -> MarketDataConfig:
    """Build a ``MarketDataConfig`` from environment variables.

    Args:
        env: Optional mapping to read from (defaults to ``os.environ``).
            Useful for tests.
    """
    e = env if env is not None else os.environ
    db_path = Path(e.get("MARKETDATA_DB_PATH", DEFAULT_DB_PATH)).expanduser()
    parquet_dir = Path(e.get("MARKETDATA_PARQUET_DIR", DEFAULT_PARQUET_DIR)).expanduser()
    return MarketDataConfig(
        alpaca_key_id=e.get("ALPACA_KEY_ID") or e.get("APCA_API_KEY_ID"),
        alpaca_secret_key=e.get("ALPACA_SECRET_KEY") or e.get("APCA_API_SECRET_KEY"),
        alpaca_base_url=e.get("ALPACA_BASE_URL", DEFAULT_BASE_URL),
        alpaca_data_url=e.get("ALPACA_DATA_URL", DEFAULT_DATA_URL),
        alpaca_stream_url=e.get("ALPACA_STREAM_URL", DEFAULT_STREAM_URL),
        alpaca_feed=e.get("ALPACA_FEED", DEFAULT_FEED).lower(),
        db_path=db_path,
        parquet_dir=parquet_dir,
        watchlist=_parse_watchlist(e.get("MARKETDATA_WATCHLIST")),
        options_tier=e.get("ALPACA_OPTIONS_TIER", "free").lower(),
    )
