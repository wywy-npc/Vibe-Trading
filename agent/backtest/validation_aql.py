"""Adapter between Vibe-Trading run artifacts and ai-quant-lab gates.

Vibe-Trading's engines write equity.csv / trades.csv / metrics.csv under
``<run_dir>/artifacts/``. ai-quant-lab's evaluate_gates expects a per-bar
return series, a CriticVerdict, and a ResearchMemory handle. This module
glues them.

The same evaluate_gates call is reused everywhere — the runner.py post-hook,
the validate_run tool, and (indirectly) the research_loop tool. There is no
parallel gate logic in Vibe-Trading.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from ai_quant_lab.agents.critic import CriticVerdict
    from ai_quant_lab.agents.memory import ResearchMemory
    from ai_quant_lab.config import settings
    from ai_quant_lab.features.leakage_detector import (
        LeakageReport,
        detect_leakage,
    )
    from ai_quant_lab.orchestrator.gates import GateOutcome, evaluate_gates
except ImportError as exc:
    raise ImportError(
        "ai-quant-lab is required for validation_aql. "
        "Install: pip install -r agent/requirements.txt"
    ) from exc


_ARTIFACTS_DIR = "artifacts"
_EQUITY_CSV = "equity.csv"
_GATES_JSON = "gates.json"
_POSITIONS_CSV = "positions.csv"


def read_returns(run_dir: Path) -> pd.Series:
    """Pull the per-bar return series from ``artifacts/equity.csv``.

    The CSV is written by ``BaseEngine._write_artifacts`` with a ``ret`` column
    indexed by timestamp. Empty series if the file is missing or malformed —
    callers decide whether that's fatal.
    """
    eq_path = run_dir / _ARTIFACTS_DIR / _EQUITY_CSV
    if not eq_path.exists():
        return pd.Series(dtype=float)
    try:
        df = pd.read_csv(eq_path, index_col=0, parse_dates=True)
    except Exception:
        return pd.Series(dtype=float)
    if "ret" not in df.columns:
        return pd.Series(dtype=float)
    return df["ret"].astype(float).dropna()


def synthetic_pass_verdict() -> CriticVerdict:
    """A 'pass' verdict for runs that never went through the critic.

    Lets evaluate_gates run on backtests originated outside the research loop
    (single-shot agent backtests, MCP, CLI). The DSR / correlation / PCA gates
    still fire; only the critic-kill path is skipped.
    """
    return CriticVerdict(
        passes=True,
        reasoning="No critic invoked for this run; statistical gates only.",
        kill_reasons=[],
    )


def gates_from_artifacts(
    run_dir: Path,
    *,
    memory: ResearchMemory,
    critic_verdict: CriticVerdict | None = None,
    annualization: int | None = None,
) -> GateOutcome:
    """Run evaluate_gates against a finished Vibe-Trading run.

    Args:
        run_dir: Run directory with ``artifacts/equity.csv``.
        memory: ResearchMemory handle (provides honest n_trials + accepted_returns).
        critic_verdict: Verdict from a prior critic call; if None, a synthetic
            pass-verdict is used so the statistical gates still apply.
        annualization: Override bars-per-year. Inferred when None: 252 default,
            falls back to settings.annualization in evaluate_gates.

    Returns:
        GateOutcome — `passes` is True only if every gate passed.
    """
    returns = read_returns(run_dir)
    verdict = critic_verdict if critic_verdict is not None else synthetic_pass_verdict()

    if returns.empty or len(returns) < 30:
        return GateOutcome(
            passes=False,
            rejection_reason="insufficient_data",
            critic_verdict=verdict,
            dsr_result=None,
            max_correlation=None,
        )

    accepted = memory.accepted_returns()
    return evaluate_gates(
        verdict,
        returns,
        memory=memory,
        accepted_returns=accepted,
        annualization=annualization,
    )


def gate_outcome_to_dict(outcome: GateOutcome) -> dict[str, Any]:
    """JSON-safe view of a GateOutcome, plus the carried critic verdict.

    Used for the gates.json artifact and for tool return payloads.
    """
    payload: dict[str, Any] = {
        "passes": bool(outcome.passes),
        "rejection_reason": outcome.rejection_reason,
        "max_correlation": _as_float(outcome.max_correlation),
        "pca_concentration": _as_float(outcome.pca_concentration),
    }
    if outcome.critic_verdict is not None:
        payload["critic_verdict"] = {
            "passes": bool(outcome.critic_verdict.passes),
            "reasoning": outcome.critic_verdict.reasoning,
            "kill_reasons": list(outcome.critic_verdict.kill_reasons),
        }
    if outcome.dsr_result is not None:
        payload["dsr"] = _dsr_to_dict(outcome.dsr_result)
    return payload


def write_gates_artifact(
    run_dir: Path,
    outcome: GateOutcome,
    *,
    extras: dict[str, Any] | None = None,
) -> Path:
    """Emit ``<run_dir>/gates.json`` capturing the gate outcome.

    Lives at the run root (next to config.json), not under artifacts/, so it
    sits alongside the canonical run metadata. ``extras`` lets the runner
    inject the trial-count snapshot.
    """
    payload = gate_outcome_to_dict(outcome)
    if extras:
        payload.update(extras)
    out = run_dir / _GATES_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def leakage_scan(
    run_dir: Path,
    *,
    future_horizon: int = 1,
    suspicious_future_correlation: float = 0.20,
) -> LeakageReport:
    """Correlation-based leakage audit on the positions vs forward returns.

    A clean signal should not correlate more strongly with future returns than
    with past returns. ai-quant-lab's detect_leakage flags it when it does.

    Args:
        run_dir: Finished run directory with positions.csv and equity.csv.
        future_horizon: Bars forward to compare against (1 = next-bar return).
        suspicious_future_correlation: Direct-future correlation that
            independently flags a column (catches forward-reference leaks).
    """
    pos_path = run_dir / _ARTIFACTS_DIR / _POSITIONS_CSV
    eq_path = run_dir / _ARTIFACTS_DIR / _EQUITY_CSV
    if not pos_path.exists() or not eq_path.exists():
        return LeakageReport(problems=["positions.csv or equity.csv missing"])

    positions = pd.read_csv(pos_path, index_col=0, parse_dates=True)
    equity = pd.read_csv(eq_path, index_col=0, parse_dates=True)
    if "ret" not in equity.columns:
        return LeakageReport(problems=["equity.csv has no 'ret' column"])

    target = equity["ret"].astype(float)
    aligned_positions = positions.reindex(target.index).astype(float)

    return detect_leakage(
        aligned_positions,
        target,
        future_horizon=future_horizon,
        suspicious_future_correlation=suspicious_future_correlation,
    )


def leakage_report_to_dict(report: LeakageReport) -> dict[str, Any]:
    """JSON-safe view of a LeakageReport for tool returns."""
    return {
        "has_leakage": report.has_leakage,
        "problems": list(report.problems),
        "column_scores": {k: _as_float(v) for k, v in report.column_scores.items()},
    }


def _dsr_to_dict(dsr: Any) -> dict[str, Any]:
    """Best-effort dict view of a DeflatedSharpeResult."""
    if is_dataclass(dsr):
        d = asdict(dsr)
    elif hasattr(dsr, "__dict__"):
        d = dict(dsr.__dict__)
    else:
        return {"repr": repr(dsr)}
    return {k: _as_float(v) if _is_numeric(v) else v for k, v in d.items()}


def _is_numeric(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
