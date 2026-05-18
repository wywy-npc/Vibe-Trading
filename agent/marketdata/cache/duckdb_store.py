"""DuckDB cache store for the marketdata package.

Connection rules
----------------
The marketdata daemon is the **sole writer** to the cache file. Everyone
else (FastAPI server, backtest runs, CLI inspection, tests in another
process) must open the database with ``read_only=True``. DuckDB enforces
this with a file lock; violating the rule yields a "could not set lock on
file" error at open time.

Helpers
-------
* :func:`open_writer` — exclusive read/write connection. Use only inside
  the daemon (or in tests that own the file).
* :func:`open_read_only` — read-only connection. Safe to call from any
  number of concurrent processes.
* :class:`DuckDBStore` — thin wrapper exposing schema migration, batch
  upserts, and the ``conn`` for ad-hoc queries.
"""

from __future__ import annotations

import logging
import sqlite3  # noqa: F401 — kept available for tests that compare backends
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import duckdb

logger = logging.getLogger(__name__)


CURRENT_SCHEMA_VERSION = 1
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def open_writer(db_path: Path) -> duckdb.DuckDBPyConnection:
    """Open the cache for read/write. Caller is responsible for closing."""
    _ensure_parent(db_path)
    return duckdb.connect(str(db_path), read_only=False)


def open_read_only(db_path: Path) -> duckdb.DuckDBPyConnection:
    """Open the cache read-only. Safe to call from non-daemon processes."""
    if not db_path.exists():
        raise FileNotFoundError(
            f"marketdata cache not found at {db_path}. "
            "Start the daemon (or run an initial backfill) to create it."
        )
    return duckdb.connect(str(db_path), read_only=True)


class DuckDBStore:
    """Lightweight handle around a DuckDB connection.

    Use as a context manager so the connection is closed deterministically::

        with DuckDBStore.writer(cfg.db_path) as store:
            store.migrate()
            store.upsert_bars(rows)
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection, *, writable: bool):
        self._conn = conn
        self._writable = writable

    # ---- construction ----------------------------------------------------
    @classmethod
    def writer(cls, db_path: Path) -> "DuckDBStore":
        return cls(open_writer(db_path), writable=True)

    @classmethod
    def reader(cls, db_path: Path) -> "DuckDBStore":
        return cls(open_read_only(db_path), writable=False)

    # ---- context manager -------------------------------------------------
    def __enter__(self) -> "DuckDBStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ---- raw access ------------------------------------------------------
    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        return self._conn

    @property
    def writable(self) -> bool:
        return self._writable

    def _require_writable(self) -> None:
        if not self._writable:
            raise RuntimeError(
                "DuckDBStore is read-only; only the marketdata daemon may write."
            )

    # ---- schema ----------------------------------------------------------
    def migrate(self) -> int:
        """Apply schema.sql idempotently and record the schema version.

        Returns the resulting ``CURRENT_SCHEMA_VERSION``.
        """
        self._require_writable()
        ddl = _SCHEMA_PATH.read_text(encoding="utf-8")
        self._conn.execute(ddl)
        row = self._conn.execute(
            "SELECT max(version) FROM schema_version"
        ).fetchone()
        current = row[0] if row and row[0] is not None else 0
        if current < CURRENT_SCHEMA_VERSION:
            self._conn.execute(
                "INSERT INTO schema_version(version) VALUES (?)",
                [CURRENT_SCHEMA_VERSION],
            )
        return CURRENT_SCHEMA_VERSION

    def schema_version(self) -> int:
        row = self._conn.execute(
            "SELECT coalesce(max(version), 0) FROM schema_version"
        ).fetchone()
        return int(row[0]) if row else 0

    # ---- upserts ---------------------------------------------------------
    def upsert_bars(self, rows: Sequence[tuple]) -> int:
        """Insert/update bars. Rows: (symbol, interval, ts, o, h, l, c, v, source).

        DuckDB doesn't support per-statement upsert as cleanly as Postgres,
        so we DELETE-then-INSERT inside a transaction keyed on the PK
        (symbol, interval, ts). This is idempotent and matches the
        backfill-overwrites-stream semantics described in the plan.
        """
        if not rows:
            return 0
        self._require_writable()
        with self._tx():
            self._conn.executemany(
                "DELETE FROM bars WHERE symbol = ? AND interval = ? AND ts = ?",
                [(r[0], r[1], r[2]) for r in rows],
            )
            self._conn.executemany(
                """
                INSERT INTO bars(symbol, interval, ts, open, high, low, close, volume, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def upsert_quotes(self, rows: Sequence[tuple]) -> int:
        """Rows: (symbol, ts, bid, ask, bid_size, ask_size, source)."""
        if not rows:
            return 0
        self._require_writable()
        with self._tx():
            self._conn.executemany(
                "DELETE FROM quotes WHERE symbol = ? AND ts = ?",
                [(r[0], r[1]) for r in rows],
            )
            self._conn.executemany(
                """
                INSERT INTO quotes(symbol, ts, bid, ask, bid_size, ask_size, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def upsert_chain_contracts(self, rows: Sequence[tuple]) -> int:
        """Rows: (contract_symbol, underlying, expiry, strike, option_type,
        exercise_style, last_seen).
        """
        if not rows:
            return 0
        self._require_writable()
        with self._tx():
            self._conn.executemany(
                "DELETE FROM options_chains WHERE contract_symbol = ?",
                [(r[0],) for r in rows],
            )
            self._conn.executemany(
                """
                INSERT INTO options_chains(
                    contract_symbol, underlying, expiry, strike,
                    option_type, exercise_style, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def upsert_option_quotes(self, rows: Sequence[tuple]) -> int:
        if not rows:
            return 0
        self._require_writable()
        with self._tx():
            self._conn.executemany(
                "DELETE FROM option_quotes WHERE contract_symbol = ? AND ts = ?",
                [(r[0], r[1]) for r in rows],
            )
            self._conn.executemany(
                """
                INSERT INTO option_quotes(
                    contract_symbol, ts, bid, ask, last, iv,
                    delta, gamma, theta, vega, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def upsert_account(self, row: tuple) -> None:
        """Row: (account_id, ts, cash, equity, buying_power,
        portfolio_value, currency, status).
        """
        self._require_writable()
        with self._tx():
            self._conn.execute(
                "DELETE FROM accounts WHERE account_id = ? AND ts = ?",
                [row[0], row[1]],
            )
            self._conn.execute(
                """
                INSERT INTO accounts(
                    account_id, ts, cash, equity, buying_power,
                    portfolio_value, currency, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )

    def upsert_positions(self, account_id: str, ts, rows: Sequence[tuple]) -> int:
        """Replace the position snapshot for (account_id, ts).

        Rows: (symbol, asset_class, qty, avg_entry, market_price,
        market_value, unrealized_pl).
        """
        self._require_writable()
        with self._tx():
            self._conn.execute(
                "DELETE FROM positions WHERE account_id = ? AND ts = ?",
                [account_id, ts],
            )
            if rows:
                self._conn.executemany(
                    """
                    INSERT INTO positions(
                        account_id, ts, symbol, asset_class, qty,
                        avg_entry, market_price, market_value, unrealized_pl
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [(account_id, ts, *r) for r in rows],
                )
        return len(rows)

    def upsert_orders(self, rows: Sequence[tuple]) -> int:
        """Rows: (order_id, account_id, symbol, side, qty, filled_qty,
        order_type, limit_price, stop_price, status, submitted_at, updated_at).
        """
        if not rows:
            return 0
        self._require_writable()
        with self._tx():
            self._conn.executemany(
                "DELETE FROM orders WHERE order_id = ?",
                [(r[0],) for r in rows],
            )
            self._conn.executemany(
                """
                INSERT INTO orders(
                    order_id, account_id, symbol, side, qty, filled_qty,
                    order_type, limit_price, stop_price, status,
                    submitted_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def record_ingestion(
        self,
        *,
        symbol: str | None,
        interval: str | None,
        range_start,
        range_end,
        source: str,
        rows_count: int,
    ) -> None:
        self._require_writable()
        self._conn.execute(
            """
            INSERT INTO ingestion_log(symbol, interval, range_start, range_end, source, rows)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [symbol, interval, range_start, range_end, source, rows_count],
        )

    # ---- read helpers ----------------------------------------------------
    def last_bar_ts(self, symbol: str, interval: str):
        """Return the most recent ``ts`` for ``(symbol, interval)`` or ``None``."""
        row = self._conn.execute(
            "SELECT max(ts) FROM bars WHERE symbol = ? AND interval = ?",
            [symbol, interval],
        ).fetchone()
        return row[0] if row else None

    def latest_ingestion_range_end(self, symbol: str, interval: str):
        """Return the most recent ``range_end`` we recorded for ``(symbol, interval)``.

        Authoritative answer to "have we queried the source for this window?";
        more robust than ``last_bar_ts`` because empty responses (weekends,
        holidays, halts) are still recorded.
        """
        row = self._conn.execute(
            """
            SELECT max(range_end)
            FROM ingestion_log
            WHERE symbol = ? AND interval = ?
            """,
            [symbol, interval],
        ).fetchone()
        return row[0] if row else None

    def fetch_bars_df(
        self,
        symbol: str,
        start_ts,
        end_ts,
        *,
        interval: str = "1d",
    ):
        """Return bars as a pandas DataFrame indexed by ts."""
        return self._conn.execute(
            """
            SELECT ts, open, high, low, close, volume
            FROM bars
            WHERE symbol = ? AND interval = ? AND ts BETWEEN ? AND ?
            ORDER BY ts
            """,
            [symbol, interval, start_ts, end_ts],
        ).fetch_df()

    # ---- internals -------------------------------------------------------
    @contextmanager
    def _tx(self) -> Iterator[None]:
        self._conn.execute("BEGIN")
        try:
            yield
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DuckDBStore",
    "open_read_only",
    "open_writer",
]
