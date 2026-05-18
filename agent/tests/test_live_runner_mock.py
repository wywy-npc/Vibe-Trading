"""Tests for the daily live runner using a mocked broker and signal engine."""

from __future__ import annotations

import importlib
import json
import os
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from live.broker_base import ExecutionResult, LivePosition, OrderSpec
from live.deployment_registry import DeploymentRecord, get_registry
from live.live_runner import LiveRunner, LiveRunnerConfig
from datetime import datetime, timezone


@pytest.fixture()
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from backtest import research_memory
    db = tmp_path / "rmem.db"
    monkeypatch.setenv(research_memory._DB_PATH_ENV, str(db))
    return db


@pytest.fixture()
def tmp_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from live.deployment_registry import _DB_PATH_ENV
    db = tmp_path / "deps.db"
    monkeypatch.setenv(_DB_PATH_ENV, str(db))
    return db


@pytest.fixture()
def signal_engine_dir(tmp_path: Path) -> Path:
    """Create a minimal run_dir with a signal_engine.py returning weight=1.0."""
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "signal_engine.py").write_text("""
import pandas as pd

class SignalEngine:
    def generate(self, data_map):
        return {sym: 1.0 for sym in data_map}
""")
    return tmp_path


def _make_broker_mock() -> MagicMock:
    broker = MagicMock()
    broker.get_account_equity.return_value = 100_000.0
    broker.get_positions.return_value = {}
    broker.is_market_open.return_value = True
    broker.place_order.return_value = ExecutionResult(
        order_id="ord_001", symbol="SPY", filled_qty=10.0,
        avg_price=450.0, timestamp=datetime.now(timezone.utc), side="buy",
    )
    return broker


def _spy_data() -> dict:
    idx = pd.date_range("2023-01-01", periods=300, freq="D")
    import numpy as np
    rng = np.random.default_rng(7)
    close = pd.Series(400 + rng.normal(0, 5, 300).cumsum(), index=idx)
    df = pd.DataFrame({"close": close, "open": close, "high": close * 1.01,
                       "low": close * 0.99, "volume": 1e6})
    return {"SPY": df}


def test_daily_loop_submits_orders(signal_engine_dir: Path, tmp_registry: Path) -> None:
    """A tick with weight=1.0 should call place_order at least once."""
    config = LiveRunnerConfig(
        deployment_id="test_daily",
        run_dir=str(signal_engine_dir),
        broker_name="alpaca",
        symbols=["SPY"],
        interval="1D",
        paper=True,
    )

    runner = LiveRunner(config)
    broker = _make_broker_mock()

    with (
        patch("live.live_runner._fetch_data", return_value=_spy_data()),
        patch("live.live_runner._make_broker", return_value=broker),
    ):
        runner.run(max_bars=1)

    broker.place_order.assert_called_once()
    call_spec: OrderSpec = broker.place_order.call_args[0][0]
    assert call_spec.side == "buy"
    assert call_spec.qty > 0


def test_kill_switch_halts_runner(signal_engine_dir: Path, tmp_registry: Path) -> None:
    """Simulated large drawdown trips the kill-switch and halts the runner."""
    config = LiveRunnerConfig(
        deployment_id="test_kill",
        run_dir=str(signal_engine_dir),
        broker_name="alpaca",
        symbols=["SPY"],
        interval="1D",
        paper=True,
        max_drawdown=0.05,  # 5% threshold
    )
    runner = LiveRunner(config)
    # Inject returns that produce >5% drawdown
    runner._live_returns = [0.02, 0.01, -0.08, -0.03]

    broker = _make_broker_mock()
    runner._check_kill_switch(broker)

    assert runner._halted is True
    broker.cancel_all_orders.assert_called_once()


def test_heartbeat_written_to_registry(signal_engine_dir: Path, tmp_registry: Path) -> None:
    """After a tick the registry should have a heartbeat for this deployment."""
    from live.deployment_registry import DeploymentRecord, get_registry

    config = LiveRunnerConfig(
        deployment_id="test_hb",
        run_dir=str(signal_engine_dir),
        broker_name="alpaca",
        symbols=["SPY"],
        interval="1D",
        paper=True,
    )

    with get_registry() as reg:
        reg.create(DeploymentRecord(
            deployment_id="test_hb",
            strategy_name="hb_test",
            run_dir=str(signal_engine_dir),
            state="PAPER",
            broker="alpaca",
            account_type="paper",
            symbols=["SPY"],
            interval="1D",
        ))

    runner = LiveRunner(config)
    broker = _make_broker_mock()

    with (
        patch("live.live_runner._fetch_data", return_value=_spy_data()),
        patch("live.live_runner._make_broker", return_value=broker),
    ):
        runner.run(max_bars=1)

    with get_registry() as reg:
        record = reg.get("test_hb")

    assert record is not None
    assert record.last_heartbeat is not None
