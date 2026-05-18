"""Tests for the hard-gate invariant: validate_run refuses non-loop runs.

The invariant: only ``research_loop`` produces runs with ``via="loop"`` and a
``loop_run_id`` in config.json. ``validate_run`` refuses everything else by
default, returning ``{"status":"error","code":"not_loop_gated"}``. The
``allow_non_loop=true`` parameter is the analyst escape hatch.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("ai_quant_lab.orchestrator.gates")

from backtest import research_memory  # noqa: E402
from src.tools.validate_run_tool import ValidateRunTool  # noqa: E402


@pytest.fixture()
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "loop_gate_mem.db"
    monkeypatch.setenv(research_memory._DB_PATH_ENV, str(db_path))
    # ValidateRunTool uses safe_run_dir which rejects paths outside the
    # allowed run roots; whitelist tmp_path for the test.
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    return db_path


def _seed_run_dir(run_dir: Path, *, config: dict | None = None) -> None:
    """Materialize artifacts/equity.csv plus config.json with the given origin."""
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    idx = pd.date_range("2020-01-01", periods=300, freq="D")
    rets = pd.Series(rng.normal(0.0005, 0.01, 300), index=idx)
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

    if config is not None:
        (run_dir / "config.json").write_text(
            json.dumps(config, indent=2), encoding="utf-8"
        )


def test_validate_run_refuses_manual_origin(tmp_path: Path, tmp_memory: Path) -> None:
    """A backtest_tool-origin run (via=manual) must return not_loop_gated."""
    _seed_run_dir(tmp_path, config={"via": "manual", "source": "yfinance"})

    result = json.loads(
        ValidateRunTool().execute(run_dir=str(tmp_path))
    )
    assert result["status"] == "error"
    assert result["code"] == "not_loop_gated"
    assert result["via"] == "manual"
    assert result["loop_run_id"] is None


def test_validate_run_refuses_missing_config(tmp_path: Path, tmp_memory: Path) -> None:
    """No config.json at all → not_loop_gated (treated as unknown origin)."""
    _seed_run_dir(tmp_path, config=None)

    result = json.loads(
        ValidateRunTool().execute(run_dir=str(tmp_path))
    )
    assert result["status"] == "error"
    assert result["code"] == "not_loop_gated"


def test_validate_run_accepts_loop_origin(tmp_path: Path, tmp_memory: Path) -> None:
    """via=loop + loop_run_id present → gates re-evaluated, gates.json written."""
    _seed_run_dir(
        tmp_path,
        config={"via": "loop", "loop_run_id": "abc123", "source": "yfinance"},
    )

    result = json.loads(
        ValidateRunTool().execute(run_dir=str(tmp_path))
    )
    assert result["status"] == "ok", result
    assert result["loop_run_id"] == "abc123"
    assert result["via"] == "loop"

    gates_payload = json.loads((tmp_path / "gates.json").read_text())
    assert gates_payload["via"] == "loop"
    assert gates_payload["loop_run_id"] == "abc123"
    assert gates_payload["revalidated"] is True


def test_validate_run_escape_hatch_allow_non_loop(tmp_path: Path, tmp_memory: Path) -> None:
    """allow_non_loop=True bypasses the invariant but stamps the override."""
    _seed_run_dir(tmp_path, config={"via": "manual", "source": "yfinance"})

    result = json.loads(
        ValidateRunTool().execute(run_dir=str(tmp_path), allow_non_loop=True)
    )
    assert result["status"] == "ok", result
    assert result["via"] == "manual"

    gates_payload = json.loads((tmp_path / "gates.json").read_text())
    assert gates_payload["allow_non_loop_override"] is True
    assert gates_payload["via"] == "manual"


def test_runner_hook_propagates_via_and_loop_run_id(tmp_path: Path, tmp_memory: Path) -> None:
    """runner._run_post_engine_gates carries via + loop_run_id from raw_config into gates.json."""
    from backtest import runner as runner_module

    _seed_run_dir(tmp_path)
    raw_config = {
        "source": "yfinance",
        "codes": ["SPY"],
        "start_date": "2020-01-01",
        "end_date": "2021-12-31",
        "engine": "daily",
        "via": "loop",
        "loop_run_id": "xyz789",
    }
    runner_module._run_post_engine_gates(tmp_path, raw_config)

    payload = json.loads((tmp_path / "gates.json").read_text())
    assert payload["via"] == "loop"
    assert payload["loop_run_id"] == "xyz789"


def test_runner_hook_defaults_via_to_unknown(tmp_path: Path, tmp_memory: Path) -> None:
    """raw_config without `via` writes via=unknown rather than crashing."""
    from backtest import runner as runner_module

    _seed_run_dir(tmp_path)
    raw_config = {
        "source": "yfinance",
        "codes": ["SPY"],
        "start_date": "2020-01-01",
        "end_date": "2021-12-31",
        "engine": "daily",
    }
    runner_module._run_post_engine_gates(tmp_path, raw_config)

    payload = json.loads((tmp_path / "gates.json").read_text())
    assert payload["via"] == "unknown"
    assert "loop_run_id" not in payload
