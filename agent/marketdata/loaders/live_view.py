"""Unified read API over the marketdata cache.

This module is the single entry point for code that needs "give me bars
from the cache" without caring whether they came from a historical
backfill or the live stream. It is **read-only** — it never writes to
DuckDB.

Use cases:
  * Agents (via MCP tools) asking for the last N bars of a symbol.
  * Backtest engines reading already-cached data when offline.
  * Monitoring rules walking recent bars.

Anything that needs to *fetch* missing data should go through the
``DataLoader`` in :mod:`marketdata.loaders.alpaca_loader`.
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable, Mapping

import pandas as pd

from marketdata.cache import DuckDBStore
from marketdata.config import MarketDataConfig, load_config


def _to_utc_naive(value) -> dt.datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").to_pydatetime().replace(tzinfo=None)


def _normalize_symbol(code: str) -> str:
    upper = code.strip().upper()
    if upper.endswith(".US"):
        return upper[:-3]
    return upper


def query_bars(
    symbol: str,
    *,
    start,
    end,
    interval: str = "1d",
    config: MarketDataConfig | None = None,
) -> pd.DataFrame:
    """Return bars for ``symbol`` in ``[start, end]`` from the cache.

    Returns an empty DataFrame if the cache file does not exist or has no
    rows for the query. Does *not* hit the network.
    """
    cfg = config or load_config()
    if not cfg.db_path.exists():
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    start_ts = _to_utc_naive(start)
    end_ts = _to_utc_naive(end)
    with DuckDBStore.reader(cfg.db_path) as store:
        df = store.fetch_bars_df(_normalize_symbol(symbol), start_ts, end_ts, interval=interval)
    if df is None or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = df.set_index("ts")
    df.index = pd.to_datetime(df.index)
    df.index.name = "trade_date"
    return df[["open", "high", "low", "close", "volume"]].sort_index()


def latest_quote(symbol: str, *, config: MarketDataConfig | None = None) -> dict | None:
    """Return the most recent top-of-book quote stored for ``symbol``."""
    cfg = config or load_config()
    if not cfg.db_path.exists():
        return None
    sym = _normalize_symbol(symbol)
    with DuckDBStore.reader(cfg.db_path) as store:
        row = store.conn.execute(
            """
            SELECT ts, bid, ask, bid_size, ask_size, source
            FROM quotes
            WHERE symbol = ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            [sym],
        ).fetchone()
    if not row:
        return None
    return {
        "symbol": sym,
        "ts": row[0],
        "bid": row[1],
        "ask": row[2],
        "bid_size": row[3],
        "ask_size": row[4],
        "source": row[5],
    }


def latest_portfolio(
    account_id: str | None = None,
    *,
    config: MarketDataConfig | None = None,
) -> dict | None:
    """Return the most recent account snapshot + positions as a single dict."""
    cfg = config or load_config()
    if not cfg.db_path.exists():
        return None
    with DuckDBStore.reader(cfg.db_path) as store:
        if account_id is None:
            row = store.conn.execute(
                "SELECT account_id FROM accounts ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            account_id = row[0]
        acct = store.conn.execute(
            """
            SELECT ts, cash, equity, buying_power, portfolio_value, currency, status
            FROM accounts
            WHERE account_id = ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            [account_id],
        ).fetchone()
        if not acct:
            return None
        ts = acct[0]
        positions_rows = store.conn.execute(
            """
            SELECT symbol, asset_class, qty, avg_entry, market_price, market_value, unrealized_pl
            FROM positions
            WHERE account_id = ? AND ts = ?
            ORDER BY symbol
            """,
            [account_id, ts],
        ).fetchall()
    return {
        "account_id": account_id,
        "ts": ts,
        "cash": acct[1],
        "equity": acct[2],
        "buying_power": acct[3],
        "portfolio_value": acct[4],
        "currency": acct[5],
        "status": acct[6],
        "positions": [
            {
                "symbol": r[0], "asset_class": r[1], "qty": r[2],
                "avg_entry": r[3], "market_price": r[4],
                "market_value": r[5], "unrealized_pl": r[6],
            }
            for r in positions_rows
        ],
    }


def option_chain_snapshot(
    underlying: str,
    *,
    expiry: dt.date | None = None,
    config: MarketDataConfig | None = None,
) -> list[dict]:
    """Return enumerated option contracts for an underlying, optionally
    filtered to a single expiry. Quotes (if any) are merged in.
    """
    cfg = config or load_config()
    if not cfg.db_path.exists():
        return []
    sym = _normalize_symbol(underlying)
    params: list = [sym]
    where = "underlying = ?"
    if expiry is not None:
        where += " AND expiry = ?"
        params.append(expiry)
    with DuckDBStore.reader(cfg.db_path) as store:
        contracts = store.conn.execute(
            f"""
            SELECT contract_symbol, expiry, strike, option_type, exercise_style, last_seen
            FROM options_chains
            WHERE {where}
            ORDER BY expiry, strike
            """,
            params,
        ).fetchall()
        if not contracts:
            return []
        # Pull the latest quote for each contract.
        symbols = tuple(r[0] for r in contracts)
        placeholders = ",".join(["?"] * len(symbols))
        quote_rows = store.conn.execute(
            f"""
            SELECT contract_symbol, bid, ask, last, iv, delta, gamma, theta, vega, source, ts
            FROM (
                SELECT *,
                       row_number() OVER (PARTITION BY contract_symbol ORDER BY ts DESC) rn
                FROM option_quotes
                WHERE contract_symbol IN ({placeholders})
            )
            WHERE rn = 1
            """,
            list(symbols),
        ).fetchall()
    quotes = {q[0]: q for q in quote_rows}
    out = []
    for c in contracts:
        q = quotes.get(c[0])
        out.append({
            "contract_symbol": c[0],
            "underlying": sym,
            "expiry": c[1],
            "strike": c[2],
            "option_type": c[3],
            "exercise_style": c[4],
            "last_seen": c[5],
            "quote": None if q is None else {
                "bid": q[1], "ask": q[2], "last": q[3], "iv": q[4],
                "delta": q[5], "gamma": q[6], "theta": q[7], "vega": q[8],
                "source": q[9], "ts": q[10],
            },
        })
    return out


__all__ = [
    "query_bars",
    "latest_quote",
    "latest_portfolio",
    "option_chain_snapshot",
]
