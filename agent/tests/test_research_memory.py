"""Tests for the singleton ResearchMemory wrapper.

ai-quant-lab is required. These tests skip cleanly when it isn't installed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

aql = pytest.importorskip("ai_quant_lab.agents.memory")

from backtest import research_memory  # noqa: E402


@pytest.fixture()
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the memory wrapper at a tmp SQLite file for the duration of one test."""
    db_path = tmp_path / "test_memory.db"
    monkeypatch.setenv(research_memory._DB_PATH_ENV, str(db_path))
    return db_path


def test_n_trials_monotonic_across_processes(tmp_memory: Path) -> None:
    """Open / close memory twice; n_trials must grow only."""
    with research_memory.get_memory() as memory:
        assert memory.n_trials() == 0
        research_memory.record_run_trial(
            memory,
            run_id="run_a",
            hypothesis_text="hypothesis a",
            rationale="",
            code="",
            metrics={"sharpe": 0.5},
            accepted=True,
            rejection_reason=None,
            returns=pd.Series([0.01, -0.02, 0.005]),
        )

    # Re-open: state must persist
    with research_memory.get_memory() as memory:
        assert memory.n_trials() == 1
        research_memory.record_run_trial(
            memory,
            run_id="run_b",
            hypothesis_text="hypothesis b",
            rationale="",
            code="",
            metrics={"sharpe": 0.1},
            accepted=False,
            rejection_reason="dsr_pvalue",
            returns=None,
        )

    with research_memory.get_memory() as memory:
        assert memory.n_trials() == 2


def test_no_public_reset_path() -> None:
    """ResearchMemory exposes no reset method. That's the anti-cheat."""
    # Class-level introspection — no instance needed
    assert not hasattr(aql.ResearchMemory, "reset")
    assert not hasattr(aql.ResearchMemory, "delete_all")
    assert not hasattr(aql.ResearchMemory, "clear")


def test_returns_to_json_roundtrip(tmp_memory: Path) -> None:
    """Accepted trial's returns are stored as JSON the memory can decode back."""
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    returns = pd.Series([0.001, -0.002, 0.005, 0.0, -0.001], index=idx)
    with research_memory.get_memory() as memory:
        research_memory.record_run_trial(
            memory,
            run_id="rt_test",
            hypothesis_text="t",
            rationale="",
            code="",
            metrics={},
            accepted=True,
            rejection_reason=None,
            returns=returns,
        )
        accepted = memory.accepted_returns()
        assert len(accepted) == 1
        decoded = accepted[0]
        assert len(decoded) == 5
        assert pytest.approx(decoded.iloc[2]) == 0.005


def test_rejected_trial_stores_no_returns(tmp_memory: Path) -> None:
    """Rejected trials skip the returns blob to keep the DB compact."""
    with research_memory.get_memory() as memory:
        research_memory.record_run_trial(
            memory,
            run_id="rej",
            hypothesis_text="t",
            rationale="",
            code="",
            metrics={},
            accepted=False,
            rejection_reason="critic_kill",
            returns=pd.Series([0.01, 0.02]),
        )
        assert memory.n_trials() == 1
        assert memory.accepted_returns() == []
