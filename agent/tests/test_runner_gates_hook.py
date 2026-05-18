"""Tests that runner.py's post-engine hook emits gates.json + records a trial.

We don't run a full engine here — we call the hook helper directly with a
prepared run_dir containing a minimal artifacts/equity.csv. That gives us
coverage of the gate path without spinning up tushare / yfinance / engine code.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("ai_quant_lab.orchestrator.gates")

from backtest import research_memory  # noqa: E402
from backtest import runner as runner_module  # noqa: E402


@pytest.fixture()
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "rmem.db"
    monkeypatch.setenv(research_memory._DB_PATH_ENV, str(db_path))
    return db_path


def _seed_run_dir(run_dir: Path, n: int = 300, drift: float = 0.0005) -> None:
    """Materialize artifacts/equity.csv with deterministic returns."""
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    rets = pd.Series(rng.normal(drift, 0.01, n), index=idx)
    equity = (1.0 + rets).cumprod()
    pd.DataFrame(
        {
            "ret": rets,
            "equity": equity,
            "drawdown": equity / equity.cummax() - 1.0,
            "benchmark_equity": equity,
            "active_ret": rets,
        },
        index=idx,
    ).rename_axis("timestamp").to_csv(artifacts / "equity.csv")


def test_run_post_engine_gates_writes_gates_json(tmp_path: Path, tmp_memory: Path) -> None:
    _seed_run_dir(tmp_path)
    raw_config = {
        "source": "yfinance",
        "codes": ["SPY"],
        "start_date": "2020-01-01",
        "end_date": "2021-12-31",
        "engine": "daily",
    }
    runner_module._run_post_engine_gates(tmp_path, raw_config)

    out = tmp_path / "gates.json"
    assert out.exists(), "gates.json was not emitted"
    payload = json.loads(out.read_text())
    assert "passes" in payload
    assert "n_trials_at_gate" in payload
    assert "critic_verdict" in payload  # synthetic pass-verdict when no critic call


def test_post_engine_gates_records_trial(tmp_path: Path, tmp_memory: Path) -> None:
    _seed_run_dir(tmp_path)
    raw_config = {
        "source": "yfinance", "codes": ["SPY"],
        "start_date": "2020-01-01", "end_date": "2021-12-31",
        "engine": "daily",
    }
    runner_module._run_post_engine_gates(tmp_path, raw_config)

    with research_memory.get_memory() as memory:
        assert memory.n_trials() == 1


def test_critic_verdict_threaded_when_present(tmp_path: Path, tmp_memory: Path) -> None:
    """When config.json carries a critic_verdict, the hook threads it through."""
    _seed_run_dir(tmp_path)
    raw_config = {
        "source": "yfinance", "codes": ["SPY"],
        "start_date": "2020-01-01", "end_date": "2021-12-31",
        "engine": "daily",
        "critic_verdict": {
            "passes": True,
            "reasoning": "explicit critic verdict for test",
            "kill_reasons": [],
        },
    }
    runner_module._run_post_engine_gates(tmp_path, raw_config)

    payload = json.loads((tmp_path / "gates.json").read_text())
    assert payload["critic_verdict"]["reasoning"] == "explicit critic verdict for test"
