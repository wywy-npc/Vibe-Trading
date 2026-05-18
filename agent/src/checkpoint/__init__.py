"""Human-in-the-loop checkpoint layer for per-skill autonomy contracts.

See ``docs/`` or the plan note in ``~/.claude/plans/`` for the design.
The package is import-safe without ``langgraph`` installed; the graph
builder imports it lazily so the data and service layers work
standalone.
"""

from src.checkpoint.models import (
    Approval,
    ApprovalStatus,
    AutonomyMode,
    AutonomySpec,
    CheckpointSpec,
    DecisionAction,
    parse_autonomy_spec,
)
from src.checkpoint.registry import (
    clear_cache,
    get_build_graph,
    load_skill_pipeline,
)
from src.checkpoint.service import ApprovalService, ConflictError, NotFoundError

__all__ = [
    "Approval",
    "ApprovalService",
    "ApprovalStatus",
    "AutonomyMode",
    "AutonomySpec",
    "CheckpointSpec",
    "ConflictError",
    "DecisionAction",
    "NotFoundError",
    "clear_cache",
    "get_build_graph",
    "load_skill_pipeline",
    "parse_autonomy_spec",
]
