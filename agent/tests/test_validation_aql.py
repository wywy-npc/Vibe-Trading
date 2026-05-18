"""Tests for the validation_aql adapter.

Covers: gates pass on a clean strategy, gates fire DSR on lucky-best-of-many,
leakage detector catches a centered-window strategy, gate output schema.

No API key required — we mock the critic verdict and feed synthetic returns
into evaluate_gates directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("ai_quant_lab.orchestrator.gates")

from backtest import research_memory, validation_aql  # noqa: E402


@pytest.fixture()
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "vmem.db"
    monkeypatch.setenv(research_memory._DB_PATH_ENV, str(db_path))
    return db_path


def _write_equity_csv(run_dir: Path, returns: pd.Series) -> None:
    """Materialize a minimal artifacts/equity.csv that read_returns can parse."""
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    df = pd.DataFrame(
        {
            "ret": returns,
            "equity": equity,
            "drawdown": (equity / equity.cummax() - 1.0),
            "benchmark_equity": equity,
            "active_ret": returns,
        },
        index=returns.index,
    )
    df.index.name = "timestamp"
    df.to_csv(artifacts / "equity.csv")


def _write_positions_csv(run_dir: Path, positions: pd.DataFrame) -> None:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    positions.index.name = "timestamp"
    positions.to_csv(artifacts / "positions.csv")


def test_read_returns_round_trip(tmp_path: Path) -> None:
    idx = pd.date_range("2020-01-01", periods=10, freq="D")
    rets = pd.Series(np.linspace(-0.01, 0.01, 10), index=idx)
    _write_equity_csv(tmp_path, rets)

    out = validation_aql.read_returns(tmp_path)
    assert len(out) == 10
    assert pytest.approx(out.iloc[5]) == pytest.approx(rets.iloc[5])


def test_gates_kill_when_dsr_pvalue_too_high(tmp_path: Path, tmp_memory: Path) -> None:
    """Inflated trial count makes the deflated-Sharpe gate strict; a modest
    Sharpe should fail with high `n_trials`."""
    rng = np.random.default_rng(7)
    idx = pd.date_range("2018-01-01", periods=1000, freq="D")
    rets = pd.Series(rng.normal(loc=0.0005, scale=0.01, size=1000), index=idx)
    _write_equity_csv(tmp_path, rets)

    with research_memory.get_memory() as memory:
        for i in range(999):
            research_memory.record_run_trial(
                memory,
                run_id=f"prior_{i}",
                hypothesis_text="prior",
                rationale="",
                code="",
                metrics={},
                accepted=False,
                rejection_reason="prior",
                returns=None,
            )
        outcome = validation_aql.gates_from_artifacts(tmp_path, memory=memory)

    assert outcome.passes is False
    assert outcome.rejection_reason is not None
    assert "deflated_sharpe" in outcome.rejection_reason or "pvalue" in outcome.rejection_reason


def test_gates_pass_on_strong_clean_strategy(tmp_path: Path, tmp_memory: Path) -> None:
    """Strong drift + low vol + n_trials=1 → DSR should pass."""
    rng = np.random.default_rng(11)
    idx = pd.date_range("2018-01-01", periods=1500, freq="D")
    rets = pd.Series(rng.normal(loc=0.0015, scale=0.005, size=1500), index=idx)
    _write_equity_csv(tmp_path, rets)

    with research_memory.get_memory() as memory:
        outcome = validation_aql.gates_from_artifacts(tmp_path, memory=memory)

    assert outcome.passes is True, outcome.rejection_reason


def test_write_gates_artifact_schema(tmp_path: Path, tmp_memory: Path) -> None:
    rng = np.random.default_rng(3)
    idx = pd.date_range("2020-01-01", periods=200, freq="D")
    rets = pd.Series(rng.normal(0.0005, 0.01, 200), index=idx)
    _write_equity_csv(tmp_path, rets)

    with research_memory.get_memory() as memory:
        outcome = validation_aql.gates_from_artifacts(tmp_path, memory=memory)
        path = validation_aql.write_gates_artifact(
            tmp_path, outcome, extras={"n_trials_at_gate": memory.n_trials()},
        )

    payload = json.loads(path.read_text())
    assert "passes" in payload
    assert "rejection_reason" in payload
    assert "critic_verdict" in payload
    assert "n_trials_at_gate" in payload


def test_insufficient_data_short_circuits(tmp_path: Path, tmp_memory: Path) -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="D")
    rets = pd.Series([0.01, -0.01, 0.0, 0.005, -0.005], index=idx)
    _write_equity_csv(tmp_path, rets)

    with research_memory.get_memory() as memory:
        outcome = validation_aql.gates_from_artifacts(tmp_path, memory=memory)

    assert outcome.passes is False
    assert outcome.rejection_reason == "insufficient_data"


def test_leakage_scan_flags_forward_correlated_positions(tmp_path: Path) -> None:
    """Positions that correlate strongly with NEXT-bar returns are leaky."""
    rng = np.random.default_rng(0)
    n = 400
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    rets = pd.Series(rng.normal(0, 0.01, n), index=idx)

    # Position at t == sign of return at t+1: classic forward-reference leak.
    leaky = pd.DataFrame({"leaky_pos": np.sign(rets.shift(-1).fillna(0)).values}, index=idx)
    _write_equity_csv(tmp_path, rets)
    _write_positions_csv(tmp_path, leaky)

    report = validation_aql.leakage_scan(tmp_path)
    assert report.has_leakage is True
    assert any("leaky_pos" in p for p in report.problems)


def test_leakage_scan_clean_positions_pass(tmp_path: Path) -> None:
    """Positions derived from a 5-bar lagged return have no future info."""
    rng = np.random.default_rng(2)
    n = 400
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    rets = pd.Series(rng.normal(0, 0.01, n), index=idx)

    clean = pd.DataFrame(
        {"lagged_mom": np.sign(rets.shift(5).fillna(0)).values}, index=idx,
    )
    _write_equity_csv(tmp_path, rets)
    _write_positions_csv(tmp_path, clean)

    report = validation_aql.leakage_scan(tmp_path)
    # Note: shift(5) of i.i.d. noise has near-zero correlation with future
    # returns; no problems should be flagged.
    assert report.has_leakage is False, report.problems
