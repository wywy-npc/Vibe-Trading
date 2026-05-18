"""Alpaca-backed implementation of the existing ``DataLoaderProtocol``.

Reads bars from the marketdata DuckDB cache. On cache miss for any
requested ``(symbol, date)`` it fetches via :class:`AlpacaRest`, writes
the result back to the cache, then returns.

DuckDB writer contention
------------------------
The marketdata daemon is the canonical writer. When the daemon is running,
this loader prefers to *only read*: if the cache already has the requested
range it never opens a writer. If a backfill is required and the daemon is
running, the writer-open call will fail with a lock error; in that case
the loader transparently falls back to a *read-only, fetch-fresh* path —
the data is pulled from Alpaca, returned to the caller in-memory, but not
persisted. The next time the daemon runs its backfill it will catch up.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders.base import validate_date_range
from backtest.loaders.registry import register
from marketdata.cache import DuckDBStore
from marketdata.config import MarketDataConfig, load_config
from marketdata.providers.alpaca_rest import AlpacaRest, _project_to_alpaca_symbol

logger = logging.getLogger(__name__)

_INTERVAL_TO_CACHE_KEY = {
    "1D": "1d", "1d": "1d",
    "1H": "1h", "1h": "1h",
    "4H": "4h", "4h": "4h",
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
}

_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


def _normalize_interval(interval: str) -> str:
    return _INTERVAL_TO_CACHE_KEY.get(str(interval or "1d"), str(interval).lower())


def _to_utc_naive(value) -> dt.datetime:
    """Convert any pandas/python timestamp to naive-UTC datetime (DuckDB-friendly)."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").to_pydatetime().replace(tzinfo=None)


@register
class DataLoader:
    """Cache-first US-equity bar loader backed by Alpaca."""

    name = "alpaca"
    markets = {"us_equity"}
    requires_auth = True

    def __init__(self, config: MarketDataConfig | None = None) -> None:
        self._cfg = config or load_config()

    # ---- protocol --------------------------------------------------------
    def is_available(self) -> bool:
        """Available if credentials are present and the cache dir is writable.

        We deliberately do *not* require the cache file to already exist —
        first-use creates it.
        """
        if not self._cfg.has_credentials:
            return False
        try:
            self._cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
            return True
        except OSError:
            return False

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        fields: Optional[List[str]] = None,
        interval: str = "1D",
    ) -> Dict[str, pd.DataFrame]:
        del fields
        if not codes:
            return {}
        validate_date_range(start_date, end_date)

        cache_interval = _normalize_interval(interval)

        # Bucket project codes by Alpaca symbol so that ``AAPL`` and ``AAPL.US``
        # share one fetch.
        symbol_groups: Dict[str, List[str]] = defaultdict(list)
        for code in codes:
            symbol_groups[_project_to_alpaca_symbol(code)].append(code)

        unique_symbols = list(symbol_groups.keys())

        # 1) Read what's cached and figure out per-symbol gap windows.
        cached, gap_windows = self._read_and_plan_gaps(
            unique_symbols, start_date, end_date, cache_interval
        )

        # 2) Fetch missing windows. Each (gap_start, gap_end) pair is symbol-specific
        # because backfills accumulate at different rates; batching across symbols is
        # a phase-1 optimization.
        for sym, window in gap_windows.items():
            if window is None:
                continue
            gap_start, gap_end = window
            try:
                fresh = self._fetch_and_persist(
                    [sym], gap_start, gap_end, cache_interval
                )
            except Exception as exc:
                logger.warning(
                    "alpaca gap-fetch failed for %s [%s..%s]: %s",
                    sym, gap_start, gap_end, exc,
                )
                continue
            fresh_df = fresh.get(sym)
            if fresh_df is None or fresh_df.empty:
                continue
            existing = cached.get(sym)
            if existing is None or existing.empty:
                cached[sym] = fresh_df
            else:
                combined = pd.concat([existing, fresh_df])
                combined = combined[~combined.index.duplicated(keep="last")].sort_index()
                cached[sym] = combined

        # 3) Map each requested project code to a copy of its bucket frame.
        out: Dict[str, pd.DataFrame] = {}
        for alpaca_sym, project_codes in symbol_groups.items():
            df = cached.get(alpaca_sym)
            if df is None or df.empty:
                continue
            for original in project_codes:
                out[original] = df.copy()
        return out

    # ---- internals -------------------------------------------------------
    def _read_and_plan_gaps(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        cache_interval: str,
    ) -> tuple[
        Dict[str, pd.DataFrame],
        Dict[str, Optional[tuple[str, str]]],
    ]:
        """Read whatever the cache has for ``symbols`` and decide what (if any)
        range each symbol still needs.

        Returns
        -------
        (cached_frames, gap_windows)
            ``cached_frames[sym]`` is the canonical OHLCV frame for everything
            currently in the cache within ``[start_date, end_date]`` (may be
            empty / missing).

            ``gap_windows[sym]`` is either ``None`` (cache fully covers the
            requested window) or ``(gap_start_date, gap_end_date)`` — an
            ISO-date pair handed to the REST provider to fill the missing
            tail. Cache misses entirely return ``(start_date, end_date)``.

        Coverage rule
        -------------
        We consult ``ingestion_log`` rather than ``last_bar_ts`` because
        weekends, holidays, and trading halts can leave the cache *correct*
        even when no new bars have appeared. The log answers "have we ever
        asked the provider for this window?" — which is what we actually
        care about. The cache covers iff
        ``latest_ingestion_range_end(sym, interval) >= requested_end_ts``.
        """
        cached: Dict[str, pd.DataFrame] = {}
        gaps: Dict[str, Optional[tuple[str, str]]] = {}

        if not self._cfg.db_path.exists():
            for s in symbols:
                gaps[s] = (start_date, end_date)
            return cached, gaps

        start_ts = _to_utc_naive(start_date)
        end_ts = _to_utc_naive(end_date) + dt.timedelta(days=1)

        try:
            with DuckDBStore.reader(self._cfg.db_path) as store:
                for sym in symbols:
                    df = store.fetch_bars_df(
                        sym, start_ts, end_ts, interval=cache_interval
                    )
                    if df is not None and not df.empty:
                        cached[sym] = _to_canonical_frame(df)
                    last_ingested = store.latest_ingestion_range_end(
                        sym, cache_interval
                    )
                    if last_ingested is None:
                        gaps[sym] = (start_date, end_date)
                    elif last_ingested < end_ts:
                        # last_ingested is the *exclusive* upper bound we
                        # previously asked for (end_date_prev + 1 day),
                        # so its date is the first day we still owe.
                        gap_start = last_ingested.date().isoformat()
                        gaps[sym] = (gap_start, end_date)
                    else:
                        gaps[sym] = None
        except Exception as exc:
            logger.debug(
                "cache read failed (treating all symbols as cache miss): %s", exc
            )
            for s in symbols:
                gaps.setdefault(s, (start_date, end_date))

        return cached, gaps

    def _fetch_and_persist(
        self,
        alpaca_symbols: List[str],
        start_date: str,
        end_date: str,
        cache_interval: str,
    ) -> Dict[str, pd.DataFrame]:
        # Collect all bars from Alpaca and group by symbol.
        rows_by_symbol: Dict[str, List[tuple]] = defaultdict(list)
        with AlpacaRest(self._cfg) as client:
            for bar in client.fetch_bars(
                alpaca_symbols,
                start=start_date,
                end=end_date,
                interval=cache_interval,
            ):
                rows_by_symbol[bar.symbol].append((
                    bar.symbol, cache_interval, bar.ts,
                    bar.open, bar.high, bar.low, bar.close, bar.volume,
                    "alpaca_rest",
                ))

        # Persist (best-effort — daemon-held lock is non-fatal).
        # Always record the *requested* window per symbol so empty responses
        # (weekends, holidays, halts) still count as "we asked the provider".
        all_rows = [r for rows in rows_by_symbol.values() for r in rows]
        requested_start = _to_utc_naive(start_date)
        requested_end = _to_utc_naive(end_date) + dt.timedelta(days=1)
        try:
            with DuckDBStore.writer(self._cfg.db_path) as store:
                store.migrate()
                if all_rows:
                    store.upsert_bars(all_rows)
                for sym in alpaca_symbols:
                    store.record_ingestion(
                        symbol=sym, interval=cache_interval,
                        range_start=requested_start, range_end=requested_end,
                        source="alpaca_rest_loader",
                        rows_count=len(rows_by_symbol.get(sym, [])),
                    )
        except Exception as exc:
            logger.info(
                "could not persist Alpaca bars to cache (likely daemon holds the lock): %s. "
                "Returning fetched data in-memory; daemon backfill will catch up.",
                exc,
            )

        # Shape into the protocol-compliant return value.
        out: Dict[str, pd.DataFrame] = {}
        for sym, rows in rows_by_symbol.items():
            df = pd.DataFrame(
                [{
                    "trade_date": r[2],
                    "open": r[3], "high": r[4], "low": r[5],
                    "close": r[6], "volume": r[7],
                } for r in rows]
            )
            if df.empty:
                continue
            df = df.set_index("trade_date").sort_index()
            df.index.name = "trade_date"
            out[sym] = df[_OHLCV_COLUMNS]
        return out


def _to_canonical_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce a DuckDB fetch result into the project's canonical OHLCV frame."""
    df = df.copy()
    if "ts" in df.columns:
        df = df.set_index("ts")
    df.index = pd.to_datetime(df.index)
    df.index.name = "trade_date"
    df = df.sort_index()
    keep = [c for c in _OHLCV_COLUMNS if c in df.columns]
    return df[keep]


__all__ = ["DataLoader"]
