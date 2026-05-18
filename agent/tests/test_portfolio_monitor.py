"""Tests for PortfolioMonitor aggregation and portfolio kill-switch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from live.deployment_registry import DeploymentRecord, get_registry
from live.monitoring import PortfolioMonitor


@pytest.fixture()
def tmp_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from live.deployment_registry import _DB_PATH_ENV
    db = tmp_path / "deps.db"
    monkeypatch.setenv(_DB_PATH_ENV, str(db))
    return db


def _insert(record: DeploymentRecord, tmp_registry) -> None:
    with get_registry() as reg:
        reg.create(record)


def _record(dep_id: str, pnl: float = 0.0, returns: list[float] | None = None, state: str = "PAPER") -> DeploymentRecord:
    rj = ""
    if returns:
        rj = json.dumps({"values": returns})
    return DeploymentRecord(
        deployment_id=dep_id, strategy_name="test",
        run_dir="/tmp/r", state=state, broker="alpaca",
        account_type="paper", symbols=["SPY"], interval="1D",
        pnl_realized=pnl, returns_json=rj,
    )


def test_combined_pnl_aggregation(tmp_registry: Path) -> None:
    _insert(_record("dep_a", pnl=100.0), tmp_registry)
    _insert(_record("dep_b", pnl=200.0), tmp_registry)

    monitor = PortfolioMonitor()
    with get_registry() as reg:
        snap = monitor.snapshot(reg)

    assert snap.total_pnl_realized == pytest.approx(300.0)
    assert snap.n_active == 2
    assert snap.per_strategy_pnl["dep_a"] == pytest.approx(100.0)
    assert snap.per_strategy_pnl["dep_b"] == pytest.approx(200.0)


def test_no_active_deployments(tmp_registry: Path) -> None:
    monitor = PortfolioMonitor()
    with get_registry() as reg:
        snap = monitor.snapshot(reg)
    assert snap.n_active == 0
    assert snap.total_pnl_realized == 0.0


def test_correlation_matrix_populated(tmp_registry: Path) -> None:
    # Give each strategy distinct return series
    rets_a = [0.01, -0.01, 0.02, -0.02, 0.01] * 20
    rets_b = [-0.01, 0.01, -0.02, 0.02, -0.01] * 20
    _insert(_record("dep_c", returns=rets_a), tmp_registry)
    _insert(_record("dep_d", returns=rets_b), tmp_registry)

    monitor = PortfolioMonitor()
    with get_registry() as reg:
        snap = monitor.snapshot(reg)

    assert "dep_c" in snap.correlation_matrix
    assert "dep_d" in snap.correlation_matrix["dep_c"]
    corr = snap.correlation_matrix["dep_c"]["dep_d"]
    # Perfectly anti-correlated series → corr ≈ -1
    assert corr < -0.9


def test_portfolio_kill_breach_flag(tmp_registry: Path) -> None:
    """Severe combined drawdown trips portfolio_max_dd_breach."""
    bad_rets = [0.02, 0.01, -0.20, -0.15, -0.10] * 10
    _insert(_record("dep_e", returns=bad_rets), tmp_registry)

    monitor = PortfolioMonitor(portfolio_max_drawdown=0.05)  # 5% threshold
    with get_registry() as reg:
        snap = monitor.snapshot(reg)

    assert snap.portfolio_max_dd_breach is True
