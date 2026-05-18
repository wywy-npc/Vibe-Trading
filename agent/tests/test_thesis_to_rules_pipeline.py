"""Smoke tests for the thesis-to-rules pipeline work nodes.

Tests verify each node's stub-fallback path runs without LLM credentials and
emits the structured payload shape that the checkpoint plumbing expects.
LLM-driven happy paths are covered by the end-to-end integration test, not
here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PIPELINE_PATH = Path(__file__).resolve().parent.parent / "src" / "skills" / "thesis-to-rules" / "pipeline.py"


@pytest.fixture(scope="module")
def pipeline_mod():
    """Load the hyphenated-skill-name pipeline module via importlib."""
    spec = importlib.util.spec_from_file_location("_thesis_pipeline", _PIPELINE_PATH)
    assert spec and spec.loader, "spec.loader is None"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_thesis_pipeline"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def fake_state(tmp_path: Path, pipeline_mod):
    """A GraphState dataclass instance with a tmp run_dir."""
    from src.checkpoint.graph import GraphState

    return GraphState(
        run_dir=str(tmp_path),
        skill_name="thesis-to-rules",
        session_id="test-session",
        attempt_id="test-attempt",
    )


def test_parse_thesis_stub_fallback(fake_state, monkeypatch, pipeline_mod):
    """Without LLM credentials, _parse_thesis emits a clearly-marked stub payload."""
    monkeypatch.setattr(pipeline_mod, "_run_agent", lambda *a, **k: None)

    out = pipeline_mod._parse_thesis(fake_state)
    payload = out["pending_payload"]
    assert "thesis_text" in payload
    assert "identified_drivers" in payload
    assert "asset_universe" in payload
    assert "time_horizon" in payload
    assert "regime_assumptions" in payload


def test_codify_rules_stub_fallback(fake_state, monkeypatch, pipeline_mod):
    """Without LLM credentials, _codify_rules emits a parseable stub SignalEngine."""
    monkeypatch.setattr(pipeline_mod, "_run_agent", lambda *a, **k: None)
    fake_state.pending_payload = {"asset_universe": ["SPY.US"]}

    out = pipeline_mod._codify_rules(fake_state)
    payload = out["pending_payload"]
    assert "rules_dsl" in payload
    assert "class SignalEngine" in payload["rules_dsl"]

    # The stub must be parseable Python.
    import ast
    ast.parse(payload["rules_dsl"])


def test_codify_rules_uses_pm_overrides(fake_state, monkeypatch, pipeline_mod):
    """The codification node respects PM-edited thesis_interpretation values."""
    captured: dict = {}
    def fake_agent(prompt, _run_dir, _session_id):
        captured["prompt"] = prompt
        return None  # forces stub fallback
    monkeypatch.setattr(pipeline_mod, "_run_agent", fake_agent)

    fake_state.checkpoint_overrides = {
        "thesis_interpretation": {
            "identified_drivers": ["PM-edited-driver"],
            "asset_universe": ["AAPL.US", "MSFT.US"],
        },
    }
    pipeline_mod._codify_rules(fake_state)
    assert "PM-edited-driver" in captured["prompt"]
    assert "AAPL.US" in captured["prompt"]


def test_propose_sizing_falls_back_to_max_pos_pct(fake_state, pipeline_mod):
    """No equity.csv → no realized vol → proposed_alloc_pct == max_pos_pct."""
    out = pipeline_mod._propose_sizing(fake_state)
    payload = out["pending_payload"]
    assert payload["proposed_alloc_pct"] == payload["max_pos_pct"]
    assert payload["realized_vol"] == 0.0


def test_propose_sizing_uses_realized_vol(fake_state, pipeline_mod, tmp_path):
    """When equity.csv exists, realized vol drives the alloc decision."""
    import numpy as np
    import pandas as pd

    backtest_dir = tmp_path / "backtest" / "artifacts"
    backtest_dir.mkdir(parents=True)
    rng = np.random.default_rng(0)
    idx = pd.date_range("2020-01-01", periods=252, freq="D")
    rets = pd.Series(rng.normal(0.0, 0.02, 252), index=idx, name="ret")
    pd.DataFrame({"ret": rets}).to_csv(backtest_dir / "equity.csv", index_label="timestamp")

    fake_state.pending_payload = {"_asset_universe": ["SPY.US"], "sharpe": 0.5}
    out = pipeline_mod._propose_sizing(fake_state)
    payload = out["pending_payload"]
    assert payload["realized_vol"] > 0
    assert 0 < payload["proposed_alloc_pct"] <= payload["max_pos_pct"]
    # Backtest context is carried into the sizing checkpoint payload.
    assert payload["sharpe"] == 0.5


def test_deploy_stages_signal_engine_and_gates(fake_state, pipeline_mod, tmp_path):
    """The deploy node copies the codified signal_engine and writes gates.json."""
    import json

    # Seed a staged signal_engine.py under backtest/code/ to mimic _run_backtest output.
    (tmp_path / "backtest" / "code").mkdir(parents=True)
    backtest_engine_src = "class SignalEngine:\n    def generate(self, data_map):\n        return {}\n"
    (tmp_path / "backtest" / "code" / "signal_engine.py").write_text(backtest_engine_src, encoding="utf-8")

    fake_state.checkpoint_overrides = {
        "thesis_interpretation": {"asset_universe": ["AAPL.US", "MSFT.US"]},
    }
    out = pipeline_mod._deploy(fake_state)
    payload = out["pending_payload"]
    assert payload["broker"] == "alpaca"
    assert payload["symbols"] == ["AAPL.US", "MSFT.US"]
    assert payload["strategy_name"].startswith("thesis-")
    assert payload["deployment_id"] is None  # filled in after pm_go_live approval

    # The deploy node writes signal_engine.py at the run_dir root for deploy_strategy_tool.
    assert (tmp_path / "signal_engine.py").exists()
    assert (tmp_path / "gates.json").exists()

    gates = json.loads((tmp_path / "gates.json").read_text())
    assert gates["source"] == "thesis_pm_approval"
    assert gates["via"] == "thesis"
    assert gates["passes"] is True
    assert isinstance(gates["approval_ids"], list)


def test_build_graph_compiles(pipeline_mod, tmp_path):
    """The skill's build_graph factory compiles a real LangGraph instance."""
    import sqlite3

    from src.checkpoint.service import ApprovalService
    from src.session.search import SessionSearchIndex

    sqlite_path = tmp_path / "sessions.db"
    # Use the session-search initializer so the approvals table exists.
    SessionSearchIndex(sqlite_path)
    conn = sqlite3.connect(str(sqlite_path), isolation_level=None, check_same_thread=False)
    svc = ApprovalService(connection=conn)

    graph = pipeline_mod.build_graph(svc, sqlite_connection=str(sqlite_path))
    assert graph is not None
