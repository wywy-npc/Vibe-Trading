"""Tests for the deployment registry: state transitions, heartbeat, persistence."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from live.deployment_registry import (
    DeploymentRecord,
    DeploymentRegistry,
    get_registry,
)


@pytest.fixture()
def tmp_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DeploymentRegistry:
    db = tmp_path / "test_deployments.db"
    monkeypatch.setenv("VIBE_TRADING_DEPLOYMENTS_PATH", str(db))
    return get_registry()


def _make_record(deployment_id: str, state: str = "PAPER") -> DeploymentRecord:
    return DeploymentRecord(
        deployment_id=deployment_id,
        strategy_name="Test Strategy",
        run_dir="/tmp/run_test",
        state=state,
        broker="alpaca",
        account_type="paper",
        symbols=["SPY"],
        interval="1D",
        cadence="daily",
    )


def test_create_and_get(tmp_registry: DeploymentRegistry) -> None:
    with tmp_registry as reg:
        rec = _make_record("dep_001")
        reg.create(rec)
        fetched = reg.get("dep_001")
    assert fetched is not None
    assert fetched.deployment_id == "dep_001"
    assert fetched.state == "PAPER"
    assert fetched.symbols == ["SPY"]


def test_state_transitions(tmp_registry: DeploymentRegistry) -> None:
    """PAPER → PENDING_APPROVAL → LIVE → HALTED."""
    with tmp_registry as reg:
        reg.create(_make_record("dep_002", "PAPER"))
        reg.update_state("dep_002", "PENDING_APPROVAL")
        assert reg.get("dep_002").state == "PENDING_APPROVAL"
        reg.update_state("dep_002", "LIVE")
        assert reg.get("dep_002").state == "LIVE"
        reg.update_state("dep_002", "HALTED", rejection_reason="drawdown")
        r = reg.get("dep_002")
        assert r.state == "HALTED"
        assert r.rejection_reason == "drawdown"


def test_heartbeat_updates(tmp_registry: DeploymentRegistry) -> None:
    with tmp_registry as reg:
        reg.create(_make_record("dep_003"))
        assert reg.get("dep_003").last_heartbeat is None
        reg.heartbeat("dep_003", pnl_realized=123.45, n_trades=5)
        r = reg.get("dep_003")
        assert r.last_heartbeat is not None
        assert r.pnl_realized == pytest.approx(123.45)
        assert r.n_trades == 5


def test_list_active_filters_halted(tmp_registry: DeploymentRegistry) -> None:
    with tmp_registry as reg:
        reg.create(_make_record("dep_paper", "PAPER"))
        reg.create(_make_record("dep_halted", "HALTED"))
        reg.create(_make_record("dep_live", "LIVE"))
        active = reg.list_active()
        ids = {r.deployment_id for r in active}
        assert "dep_paper" in ids
        assert "dep_live" in ids
        assert "dep_halted" not in ids


def test_invalid_state_raises(tmp_registry: DeploymentRegistry) -> None:
    with tmp_registry as reg:
        reg.create(_make_record("dep_err"))
        with pytest.raises(ValueError):
            reg.update_state("dep_err", "INVALID_STATE")


def test_pid_update(tmp_registry: DeploymentRegistry) -> None:
    with tmp_registry as reg:
        reg.create(_make_record("dep_pid"))
        reg.update_pid("dep_pid", 12345, remote_host="ec2-1-2-3-4.compute.amazonaws.com")
        r = reg.get("dep_pid")
        assert r.pid == 12345
        assert "ec2" in r.remote_host
