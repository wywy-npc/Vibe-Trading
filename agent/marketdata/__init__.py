"""Market data pipeline for Vibe-Trading.

This package provides:
  * A DuckDB cache shared by historical loaders.
  * Alpaca REST provider for US equities and options.
  * Loaders implementing the existing ``backtest.loaders.base.DataLoaderProtocol``
    so backtests transparently read from the cache.

The Alpaca loader is the current cache writer. On a cache miss it fetches via
``providers.alpaca_rest``, persists to DuckDB best-effort (with lock-tolerance
fallback), and returns the data in-memory. Read-only siblings (``live_view``,
backtest engines) hit the cache through ``cache.duckdb_store.open_read_only``.

A long-running asyncio daemon (sole DuckDB writer pattern, WebSocket streaming
for quotes/bars, polling for account state) is the natural next step when a
streaming use case lands. Re-add a ``daemon/`` subpackage at that point.

Design rule: nothing under ``marketdata/`` imports from ``src.session`` or
``src.agent``. Callbacks are injected at the application edge.
"""

from __future__ import annotations

__all__ = ["config"]
