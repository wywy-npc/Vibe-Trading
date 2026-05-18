"""Tests for DeployStrategyTool validation gates."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.tools.deploy_strategy_tool import DeployStrategyTool


@pytest.fixture()
def passing_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a minimal run_dir with passing gates.json and a signal_engine.py."""
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "signal_engine.py").write_text("""
class SignalEngine:
    def generate(self, data_map):
        return {sym: 1.0 for sym in data_map}
""")
    (tmp_path / "gates.json").write_text(json.dumps({
        "passes": True,
        "rejection_reason": None,
        "dsr": {"pvalue": 0.02},
        "n_trials_at_gate": 5,
    }))
    (tmp_path / "config.json").write_text(json.dumps({
        "source": "yfinance", "codes": ["SPY"],
        "start_date": "2022-01-01", "end_date": "2023-12-31",
        "engine": "daily",
    }))

    # Register as allowed run root
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path.parent))

    return tmp_path


@pytest.fixture()
def tmp_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from live.deployment_registry import _DB_PATH_ENV
    monkeypatch.setenv(_DB_PATH_ENV, str(tmp_path / "deps.db"))


@pytest.fixture()
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backtest import research_memory
    monkeypatch.setenv(research_memory._DB_PATH_ENV, str(tmp_path / "rmem.db"))


def test_requires_passing_gates_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_registry, tmp_memory) -> None:
    """Deploy tool must reject a run_dir with passes=false in gates.json."""
    run_dir = tmp_path / "failing_run"
    run_dir.mkdir()
    (run_dir / "gates.json").write_text(json.dumps({
        "passes": False, "rejection_reason": "deflated_sharpe_pvalue=0.61>=0.05",
    }))
    (run_dir / "config.json").write_text("{}")

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))

    result = json.loads(DeployStrategyTool().execute(
        run_dir=str(run_dir), broker="alpaca", symbols=["SPY"]
    ))
    assert result["status"] == "error"
    assert "gates" in result["error"].lower() or "gate" in result["error"].lower()


def test_requires_gates_json_to_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_registry, tmp_memory) -> None:
    """Deploy tool must reject a run_dir with no gates.json."""
    run_dir = tmp_path / "no_gates"
    run_dir.mkdir()
    (run_dir / "config.json").write_text("{}")

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))

    result = json.loads(DeployStrategyTool().execute(
        run_dir=str(run_dir), broker="alpaca", symbols=["SPY"]
    ))
    assert result["status"] == "error"
    assert "gates.json" in result["error"]


def test_deploy_creates_registry_record(
    passing_run_dir: Path, tmp_registry, tmp_memory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful deploy creates a PAPER record in the registry."""
    # Seed the run_dir name as a survivor in research_memory so the deploy
    # tool's survivor check passes
    import pandas as pd
    from backtest.research_memory import get_memory, record_run_trial
    with get_memory() as memory:
        idx = pd.date_range("2022-01-01", periods=100, freq="D")
        returns = pd.Series([0.001] * 100, index=idx)
        record_run_trial(
            memory,
            run_id=passing_run_dir.name,
            hypothesis_text="test hypothesis",
            rationale="",
            code="",
            metrics={"sharpe": 0.9},
            accepted=True,
            rejection_reason=None,
            returns=returns,
        )

    # Mock subprocess.Popen so we don't actually fork a process
    mock_proc = type("P", (), {"pid": 99999})()
    with patch("subprocess.Popen", return_value=mock_proc):
        result = json.loads(DeployStrategyTool().execute(
            run_dir=str(passing_run_dir),
            broker="alpaca",
            symbols=["SPY"],
        ))

    assert result["status"] == "ok", result.get("error")
    assert result["state"] == "PAPER"
    assert result["deployment_id"]

    from live.deployment_registry import get_registry
    with get_registry() as reg:
        record = reg.get(result["deployment_id"])
    assert record is not None
    assert record.state == "PAPER"
    assert record.broker == "alpaca"
