"""Trust Layer: structured provenance for every research result.

Every research run produces a ResearchArtifact that records:
  - Data sources (which tools, what was queried, raw snippets)
  - Assumptions (explicit priors with machine-readable invalidation triggers)
  - Evidence (source-attributed, polarity-tagged supporting/contradicting findings)
  - Strategy code (hash-pinned to the validation that ran against it)
  - Validation results (backtest metrics tied to a specific code version)
  - Failure modes (conditions that would falsify the hypothesis)
  - PM decision record (approve/reject/needs-more-research with rationale)

The artifact is built in two passes:
  1. Passive extraction — TrustLayerBuilder hooks into every tool result automatically.
  2. Active structuring — the model calls structure_research() to fill in the
     hypothesis statement, assumptions, evidence, and failure modes explicitly.

Artifacts persist cross-session in ~/.vibe-trading/hypotheses/ via HypothesisStore.
"""

from src.trust_layer.builder import TrustLayerBuilder
from src.trust_layer.models import (
    Assumption,
    DataSource,
    Evidence,
    FailureMode,
    PMDecision,
    ResearchArtifact,
    ValidationResult,
)
from src.trust_layer.store import HypothesisStore

__all__ = [
    "TrustLayerBuilder",
    "HypothesisStore",
    "ResearchArtifact",
    "DataSource",
    "Assumption",
    "Evidence",
    "ValidationResult",
    "FailureMode",
    "PMDecision",
]
