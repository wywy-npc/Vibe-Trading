# `agent/marketdata/`

US-equity-focused market data layer: Alpaca provider + DuckDB cache, plugged into the existing `backtest.loaders` registry so backtests transparently read from a persistent cache.

## Layout

```
marketdata/
├── __init__.py        # Module-level design rules (see below)
├── config.py          # MarketDataConfig — env-driven (ALPACA_KEY_ID, etc.)
├── cache/
│   ├── duckdb_store.py  # Connection pooling (read-only + writer); batch upserts
│   └── schema.sql       # DuckDB schema: bars, quotes, options, accounts, etc.
├── providers/
│   └── alpaca_rest.py   # httpx-based Alpaca REST client (not alpaca-py)
└── loaders/
    ├── alpaca_loader.py # DataLoaderProtocol implementation — cache-first, fetch on miss
    └── live_view.py     # Read-only query API: query_bars, latest_quote, latest_portfolio
```

## Architecture

```
Provider (Alpaca REST)
    ↓
Loader (alpaca_loader, implements DataLoaderProtocol)
    ↓ (writes on cache miss; lock-tolerance fallback)
Cache (DuckDB: bars, quotes, accounts, positions, options, orders)
    ↓ (read-only)
Live View (live_view: query_bars, latest_quote, latest_portfolio, option_chain_snapshot)
```

## Current writer model

`alpaca_loader` is the only writer today. On a cache miss it:

1. Detects the gap by consulting the `ingestion_log` table.
2. Fetches the gap range via `providers.alpaca_rest`.
3. Persists to DuckDB via a best-effort writer context manager.
4. Tolerates lock contention gracefully — if another process holds the writer lock, returns the in-memory data without persisting.

A long-running asyncio daemon (sole-writer pattern, WebSocket streaming for live quotes/bars, account/position polling on a fixed cadence) is the natural next step when a streaming use case lands. Re-add `daemon/` and `monitor/` subpackages at that point; in the meantime, the loader-as-writer model is sufficient for a historical-data research harness.

## Schema (`cache/schema.sql`)

| Table | PK | Purpose |
|---|---|---|
| `bars` | `(symbol, interval, ts)` | OHLCV, idempotent upserts |
| `quotes` | `(symbol, ts)` | Top-of-book bid/ask |
| `options_chains` | `(underlying, strike, expiry, type)` | Contract enumeration |
| `option_quotes` | `(contract_id, ts)` | Greeks + bid/ask |
| `accounts` | `(account_id, ts)` | Snapshot of cash/equity/buying_power |
| `positions` | `(account_id, symbol, ts)` | Position snapshots |
| `orders` | `(order_id)` | Broker orders |
| `ingestion_log` | `(symbol, interval, range_start)` | Backfill audit trail; powers gap detection |

## Wiring

Registered in `backtest/loaders/registry.py:57` as `"marketdata.loaders.alpaca_loader"`. The fallback chain for `us_equity` (registry.py:74) is `["alpaca", "yfinance", "akshare"]` — `alpaca` is first, so `AAPL.US` defaults to Alpaca. Without `ALPACA_KEY_ID`/`ALPACA_SECRET_KEY` env vars, the chain falls through to yfinance silently.

## Configuration

| Env var | Purpose | Default |
|---|---|---|
| `ALPACA_KEY_ID` | Alpaca API key id | (required for Alpaca) |
| `ALPACA_SECRET_KEY` | Alpaca API secret | (required for Alpaca) |
| `ALPACA_BASE_URL` | REST base URL | paper API endpoint |
| `MARKETDATA_DB_PATH` | DuckDB cache path | `data/marketdata.duckdb` |
| `MARKETDATA_PAPER` | Paper trading toggle | `true` |

## Design rule

> Nothing under `marketdata/` imports from `src.session` or `src.agent`. Callbacks are injected at the application edge.

This keeps the data layer testable in isolation and lets the eventual daemon run as a separate process / systemd service without dragging in agent infrastructure.

## Adding a new provider

1. Create `providers/<name>.py` with the raw REST/streaming client.
2. Create `loaders/<name>_loader.py` implementing `backtest.loaders.base.DataLoaderProtocol`. Use `@register` to add to the global registry.
3. Add the module path to `backtest/loaders/registry.py:_loader_modules`.
4. Append the source name to the appropriate `FALLBACK_CHAINS` entry.
5. Add provider-specific schema (if needed) to `cache/schema.sql` and bump the migration version.
