"""Trust Layer data models.

ResearchArtifact is the top-level epistemic object produced by every research run.
It is the structured answer to "should I believe this result, and under what
conditions would it be wrong?" — distinct from the trace.jsonl, which answers
"what mechanical steps were taken?"
"""

from __future__ import annotations

import time
import uuid
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class DataSource(BaseModel):
    """One external information source consulted during research."""

    tool: str
    query_or_path: str
    url: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)
    snippet: str = ""


class Assumption(BaseModel):
    """An explicit prior the hypothesis depends on.

    invalidation_trigger is machine-readable so the Research Autopilot can
    monitor for conditions that require re-evaluation.
    """

    statement: str
    basis: str = ""
    invalidation_trigger: str = ""


class Evidence(BaseModel):
    """A source-attributed piece of supporting or contradicting evidence."""

    claim: str
    source_tool: str = ""
    source_ref: str = ""
    polarity: Literal["supporting", "contradicting", "neutral"] = "neutral"
    strength: Literal["strong", "moderate", "weak"] = "moderate"


class ValidationResult(BaseModel):
    """Backtest output pinned to a specific code version via hash.

    Multiple ValidationResults can attach to one artifact (e.g. different
    time windows or parameter sweeps). If strategy code changes, a new
    hash is required — stale validations are never silently overwritten.
    """

    run_id: str
    strategy_code_hash: str = ""
    data_range: str = ""
    sharpe: Optional[float] = None
    max_drawdown: Optional[float] = None
    win_rate: Optional[float] = None
    trade_count: Optional[int] = None
    statistical_significance: Optional[float] = None
    passed: bool = False


class FailureMode(BaseModel):
    """A named condition under which the hypothesis would be falsified.

    monitoring_signal tells downstream systems (Research Autopilot) what
    observable to watch to detect this condition before it materialises.
    """

    condition: str
    probability: Literal["high", "medium", "low"] = "medium"
    monitoring_signal: str = ""


class PMDecision(BaseModel):
    """A portfolio manager's recorded decision on a research artifact."""

    decided_at: float = Field(default_factory=time.time)
    decision: Literal["approved", "rejected", "needs_more_research"]
    rationale: str = ""
    conditions: List[str] = Field(default_factory=list)


class ResearchArtifact(BaseModel):
    """The complete provenance record for one research result.

    Lifecycle:
        proposed  — hypothesis stated, no validation yet
        testing   — backtest or statistical test running
        validated — at least one passing ValidationResult attached
        live      — PM approved for trading consideration
        invalidated — PM rejected, or a failure mode condition triggered
    """

    artifact_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    run_id: str
    session_id: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    hypothesis: str = ""
    hypothesis_status: Literal[
        "proposed", "testing", "validated", "live", "invalidated"
    ] = "proposed"

    data_sources: List[DataSource] = Field(default_factory=list)
    assumptions: List[Assumption] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)

    strategy_code_path: Optional[str] = None
    strategy_code_hash: Optional[str] = None
    validation_results: List[ValidationResult] = Field(default_factory=list)

    failure_modes: List[FailureMode] = Field(default_factory=list)

    pm_decision: Optional[PMDecision] = None

    trace_path: str = ""

    # Incremented each time the artifact is updated in the store
    version: int = 1
    parent_artifact_id: Optional[str] = None

    # True once hypothesis + assumptions + failure_modes are all populated
    is_complete: bool = False
