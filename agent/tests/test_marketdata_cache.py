"""Tests for marketdata.cache.duckdb_store — schema, upserts, read-only access."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from marketdata.cache import DuckDBStore
from marketdata.cache.duckdb_store import CURRENT_SCHEMA_VERSION


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "marketdata.duckdb"


def _sample_bar_rows(symbol: str = "AAPL") -> list[tuple]:
    return [
        (symbol, "1d", dt.datetime(2026, 1, 2), 100.0, 105.0, 99.0, 104.0, 1_000, "test"),
        (symbol, "1d", dt.datetime(2026, 1, 3), 104.0, 108.0, 103.0, 107.0, 2_000, "test"),
        (symbol, "1d", dt.datetime(2026, 1, 6), 107.0, 110.0, 106.0, 109.0, 1_500, "test"),
    ]


class TestSchemaMigration:
    def test_migrate_records_version(self, db_path: Path) -> None:
        with DuckDBStore.writer(db_path) as store:
            v = store.migrate()
            assert v == CURRENT_SCHEMA_VERSION
            assert store.schema_version() == CURRENT_SCHEMA_VERSION

    def test_migrate_is_idempotent(self, db_path: Path) -> None:
        with DuckDBStore.writer(db_path) as store:
            store.migrate()
            store.migrate()
            store.migrate()
        # Only one row per version
        with DuckDBStore.reader(db_path) as r:
            count = r.conn.execute(
                "SELECT count(*) FROM schema_version WHERE version = ?",
                [CURRENT_SCHEMA_VERSION],
            ).fetchone()[0]
            assert count == 1


class TestBarUpserts:
    def test_upsert_then_read(self, db_path: Path) -> None:
        rows = _sample_bar_rows()
        with DuckDBStore.writer(db_path) as store:
            store.migrate()
            store.upsert_bars(rows)
        with DuckDBStore.reader(db_path) as r:
            count = r.conn.execute("SELECT count(*) FROM bars").fetchone()[0]
            assert count == len(rows)

    def test_upsert_is_idempotent(self, db_path: Path) -> None:
        rows = _sample_bar_rows()
        with DuckDBStore.writer(db_path) as store:
            store.migrate()
            store.upsert_bars(rows)
            store.upsert_bars(rows)
            store.upsert_bars(rows)
            count = store.conn.execute("SELECT count(*) FROM bars").fetchone()[0]
            assert count == len(rows)

    def test_upsert_overwrites_same_key(self, db_path: Path) -> None:
        original = _sample_bar_rows()
        updated = [
            ("AAPL", "1d", dt.datetime(2026, 1, 3), 999.0, 999.0, 999.0, 999.0, 9_999, "fresh")
        ]
        with DuckDBStore.writer(db_path) as store:
            store.migrate()
            store.upsert_bars(original)
            store.upsert_bars(updated)
            row = store.conn.execute(
                "SELECT close, source FROM bars WHERE symbol='AAPL' AND ts = ?",
                [dt.datetime(2026, 1, 3)],
            ).fetchone()
            assert row == (999.0, "fresh")

    def test_last_bar_ts(self, db_path: Path) -> None:
        with DuckDBStore.writer(db_path) as store:
            store.migrate()
            store.upsert_bars(_sample_bar_rows())
            assert store.last_bar_ts("AAPL", "1d") == dt.datetime(2026, 1, 6)
            assert store.last_bar_ts("MISSING", "1d") is None


class TestReadOnlyEnforcement:
    def test_reader_blocked_from_writing(self, db_path: Path) -> None:
        # Create the file first.
        with DuckDBStore.writer(db_path) as store:
            store.migrate()
        with DuckDBStore.reader(db_path) as r:
            with pytest.raises(RuntimeError, match="read-only"):
                r.upsert_bars(_sample_bar_rows())

    def test_reader_fails_if_no_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            DuckDBStore.reader(tmp_path / "nope.duckdb")


class TestAccountAndPositions:
    def test_account_and_position_roundtrip(self, db_path: Path) -> None:
        ts = dt.datetime(2026, 5, 18, 14, 30, 0)
        with DuckDBStore.writer(db_path) as store:
            store.migrate()
            store.upsert_account(
                ("acct-1", ts, 1000.0, 25_000.0, 50_000.0, 25_000.0, "USD", "ACTIVE")
            )
            store.upsert_positions(
                "acct-1", ts,
                [
                    ("AAPL", "us_equity", 10.0, 150.0, 160.0, 1600.0, 100.0),
                    ("SPY",  "us_equity", 5.0,  400.0, 405.0, 2025.0, 25.0),
                ],
            )
        with DuckDBStore.reader(db_path) as r:
            acct = r.conn.execute("SELECT * FROM accounts").fetchall()
            positions = r.conn.execute("SELECT symbol, qty FROM positions ORDER BY symbol").fetchall()
        assert len(acct) == 1
        assert positions == [("AAPL", 10.0), ("SPY", 5.0)]

    def test_position_snapshot_replace(self, db_path: Path) -> None:
        ts = dt.datetime(2026, 5, 18, 14, 30, 0)
        with DuckDBStore.writer(db_path) as store:
            store.migrate()
            store.upsert_positions("acct-1", ts, [("AAPL", "us_equity", 10.0, 150.0, 160.0, 1600.0, 100.0)])
            # Re-upserting for same (account, ts) replaces wholesale.
            store.upsert_positions("acct-1", ts, [("MSFT", "us_equity", 7.0, 300.0, 310.0, 2170.0, 70.0)])
            rows = store.conn.execute("SELECT symbol FROM positions ORDER BY symbol").fetchall()
            assert [r[0] for r in rows] == ["MSFT"]
