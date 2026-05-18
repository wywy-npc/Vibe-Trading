"""Persistent catalog of all deployed strategies.

Mirrors the research_memory.py pattern: singleton SQLite handle at
~/.vibe-trading/deployments.db, context-managed, autocommit.

State machine:
    PAPER → PENDING_APPROVAL → LIVE
    PAPER | LIVE → HALTED
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DB_PATH_ENV = "VIBE_TRADING_DEPLOYMENTS_PATH"
_DEFAULT_DB = Path.home() / ".vibe-trading" / "deployments.db"

VALID_STATES = {"PAPER", "LIVE", "HALTED", "PENDING_APPROVAL"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deployments (
    deployment_id   TEXT PRIMARY KEY,
    strategy_name   TEXT NOT NULL,
    run_dir         TEXT NOT NULL,
    state           TEXT NOT NULL,
    broker          TEXT NOT NULL,
    account_type    TEXT NOT NULL,
    symbols         TEXT NOT NULL,
    interval        TEXT NOT NULL,
    cadence         TEXT NOT NULL DEFAULT 'daily',
    pid             INTEGER,
    remote_host     TEXT,
    created_at      TEXT NOT NULL,
    last_heartbeat  TEXT,
    pnl_realized    REAL NOT NULL DEFAULT 0.0,
    n_trades        INTEGER NOT NULL DEFAULT 0,
    rejection_reason TEXT,
    returns_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_state ON deployments(state);
"""


@dataclass
class DeploymentRecord:
    deployment_id: str
    strategy_name: str
    run_dir: str
    state: str
    broker: str
    account_type: str          # "paper" | "live"
    symbols: list[str]
    interval: str
    cadence: str = "daily"
    pid: int | None = None
    remote_host: str | None = None
    created_at: str = field(default_factory=lambda: _now())
    last_heartbeat: str | None = None
    pnl_realized: float = 0.0
    n_trades: int = 0
    rejection_reason: str | None = None
    returns_json: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def deployments_db_path() -> Path:
    override = os.environ.get(_DB_PATH_ENV)
    if override:
        return Path(override).expanduser()
    return _DEFAULT_DB


class DeploymentRegistry:
    """CRUD for DeploymentRecord + state transitions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        for stmt in _SCHEMA.strip().split(";"):
            if stmt.strip():
                self._conn.execute(stmt)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DeploymentRegistry:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def create(self, record: DeploymentRecord) -> None:
        if record.state not in VALID_STATES:
            raise ValueError(f"Invalid state {record.state!r}")
        self._conn.execute(
            """
            INSERT OR REPLACE INTO deployments (
                deployment_id, strategy_name, run_dir, state, broker,
                account_type, symbols, interval, cadence, pid, remote_host,
                created_at, last_heartbeat, pnl_realized, n_trades,
                rejection_reason, returns_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record.deployment_id, record.strategy_name, record.run_dir,
                record.state, record.broker, record.account_type,
                json.dumps(record.symbols), record.interval, record.cadence,
                record.pid, record.remote_host, record.created_at,
                record.last_heartbeat, record.pnl_realized, record.n_trades,
                record.rejection_reason, record.returns_json,
            ),
        )

    def get(self, deployment_id: str) -> DeploymentRecord | None:
        row = self._conn.execute(
            "SELECT * FROM deployments WHERE deployment_id=?", (deployment_id,)
        ).fetchone()
        return _row_to_record(row) if row else None

    def update_state(
        self,
        deployment_id: str,
        state: str,
        *,
        rejection_reason: str | None = None,
    ) -> None:
        if state not in VALID_STATES:
            raise ValueError(f"Invalid state {state!r}")
        self._conn.execute(
            "UPDATE deployments SET state=?, rejection_reason=? WHERE deployment_id=?",
            (state, rejection_reason, deployment_id),
        )

    def update_pid(self, deployment_id: str, pid: int | None, remote_host: str | None = None) -> None:
        self._conn.execute(
            "UPDATE deployments SET pid=?, remote_host=? WHERE deployment_id=?",
            (pid, remote_host, deployment_id),
        )

    def heartbeat(
        self,
        deployment_id: str,
        *,
        pnl_realized: float | None = None,
        n_trades: int | None = None,
        returns_json: str | None = None,
    ) -> None:
        parts = ["last_heartbeat=?"]
        vals: list[Any] = [_now()]
        if pnl_realized is not None:
            parts.append("pnl_realized=?")
            vals.append(pnl_realized)
        if n_trades is not None:
            parts.append("n_trades=?")
            vals.append(n_trades)
        if returns_json is not None:
            parts.append("returns_json=?")
            vals.append(returns_json)
        vals.append(deployment_id)
        self._conn.execute(
            f"UPDATE deployments SET {', '.join(parts)} WHERE deployment_id=?",
            vals,
        )

    def list_active(self) -> list[DeploymentRecord]:
        rows = self._conn.execute(
            "SELECT * FROM deployments WHERE state IN ('PAPER','LIVE','PENDING_APPROVAL') ORDER BY created_at"
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def list_all(self, state: str | None = None) -> list[DeploymentRecord]:
        if state:
            rows = self._conn.execute(
                "SELECT * FROM deployments WHERE state=? ORDER BY created_at", (state,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM deployments ORDER BY created_at"
            ).fetchall()
        return [_row_to_record(r) for r in rows]


def _row_to_record(row: sqlite3.Row) -> DeploymentRecord:
    d = dict(row)
    d["symbols"] = json.loads(d.get("symbols") or "[]")
    return DeploymentRecord(**{k: v for k, v in d.items() if k in DeploymentRecord.__dataclass_fields__})


def get_registry() -> DeploymentRegistry:
    """Open a DeploymentRegistry handle. Use as a context manager."""
    return DeploymentRegistry(deployments_db_path())
