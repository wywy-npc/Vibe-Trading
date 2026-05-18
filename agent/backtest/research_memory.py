"""Singleton wrapper around ai_quant_lab.agents.memory.ResearchMemory.

The Deflated Sharpe gate is only as honest as the trial counter feeding it.
Every backtest run anywhere in Vibe-Trading — the agent's exploratory backtests
via backtest_tool, the deterministic research_loop, ad-hoc critique calls —
records a TrialRecord here. There is no reset API.

The DB file lives at ``agent/research_memory.db`` so the count is colocated
with the rest of the project's durable state. Set the
``VIBE_TRADING_RESEARCH_MEMORY_PATH`` env var to override (shared deployments,
tests). The file is in .gitignore — do not delete it between sessions.

Migration note (May 2026): older installs kept the DB at
``~/.vibe-trading/research_memory.db``. If that legacy file exists and the
new in-tree default does not, ``memory_db_path()`` returns the legacy path
so accumulated ``n_trials`` is preserved. Migrate by ``mv``-ing the file
once. We DO NOT auto-migrate to avoid surprising the user.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from ai_quant_lab.agents.memory import ResearchMemory, TrialRecord
except ImportError as exc:
    raise ImportError(
        "ai-quant-lab is required for trial-counted validation. "
        "Install: pip install -r agent/requirements.txt"
    ) from exc


logger = logging.getLogger(__name__)

_DB_PATH_ENV = "VIBE_TRADING_RESEARCH_MEMORY_PATH"
# Default: agent/research_memory.db (next to backtest/, runs/, src/, etc.)
_DEFAULT_DB = Path(__file__).resolve().parent.parent / "research_memory.db"
# Pre-2026-05 location. Honored as a fallback so existing n_trials counts
# don't silently reset on upgrade.
_LEGACY_DB = Path.home() / ".vibe-trading" / "research_memory.db"
_legacy_warned = False


def memory_db_path() -> Path:
    """Resolve the SQLite path.

    Resolution order:
    1. ``VIBE_TRADING_RESEARCH_MEMORY_PATH`` env override (for tests / shared deployments).
    2. The new in-tree default if it exists.
    3. The legacy ``~/.vibe-trading/`` path if it exists (with a one-time WARNING).
    4. The new in-tree default (will be created on first write).
    """
    override = os.environ.get(_DB_PATH_ENV)
    if override:
        return Path(override).expanduser()

    if _DEFAULT_DB.exists():
        return _DEFAULT_DB

    if _LEGACY_DB.exists():
        global _legacy_warned
        if not _legacy_warned:
            logger.warning(
                "Using legacy research_memory.db at %s. Move it to %s to "
                "match the post-2026-05 default. n_trials is preserved either way.",
                _LEGACY_DB, _DEFAULT_DB,
            )
            _legacy_warned = True
        return _LEGACY_DB

    return _DEFAULT_DB


def get_memory() -> ResearchMemory:
    """Open a ResearchMemory handle. Use as a context manager:

        with get_memory() as memory:
            memory.record(trial)
            n = memory.n_trials()

    The connection is opened fresh per call so callers in different processes
    (CLI, API workers, MCP) don't share a sqlite handle. ResearchMemory uses
    autocommit (isolation_level=None) so writes are durable on close.
    """
    return ResearchMemory(memory_db_path())


def returns_to_json(returns: pd.Series) -> str:
    """Encode a returns series for storage in TrialRecord.returns_json.

    Matches the schema ResearchMemory.accepted_returns() decodes:
    {"index": [iso strings], "values": [floats]}.
    """
    if returns is None or returns.empty:
        return ""
    s = returns.dropna()
    if s.empty:
        return ""
    idx = [str(t) for t in s.index]
    values = [float(v) for v in s.values]
    return json.dumps({"index": idx, "values": values}, separators=(",", ":"))


def record_run_trial(
    memory: ResearchMemory,
    *,
    run_id: str,
    hypothesis_text: str,
    rationale: str,
    code: str,
    metrics: dict[str, float],
    accepted: bool,
    rejection_reason: str | None,
    returns: pd.Series | None,
    iteration: int = 0,
) -> int:
    """Convenience: build a TrialRecord and insert. Returns the row id.

    Used by runner.py post-engine hook and by the standalone critique tool.
    `n_trials_at_time` is captured before insert so it reflects the count
    *prior* to this trial — that's the value the deflated_sharpe gate used.
    """
    n_at_time = memory.n_trials()
    trial = TrialRecord(
        hypothesis_id=run_id,
        hypothesis_text=hypothesis_text or "",
        rationale=rationale or "",
        code=code or "",
        metrics={k: float(v) for k, v in (metrics or {}).items() if _is_scalar(v)},
        accepted=bool(accepted),
        rejection_reason=rejection_reason,
        n_trials_at_time=n_at_time,
        iteration=int(iteration),
        returns_json=returns_to_json(returns) if accepted and returns is not None else "",
    )
    return memory.record(trial)


def _is_scalar(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)
