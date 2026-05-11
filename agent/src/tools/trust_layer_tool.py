"""Trust Layer tool: structure_research and decide actions.

structure — model submits hypothesis, assumptions, evidence, failure_modes.
            Merges with passively extracted data and saves a complete artifact.
decide    — PM records an approval/rejection against an existing artifact.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.trust_layer.builder import TrustLayerBuilder
from src.trust_layer.models import PMDecision, ResearchArtifact
from src.trust_layer.store import HypothesisStore

logger = logging.getLogger(__name__)

_store = HypothesisStore()


def _resolve_run_dir(run_id: str) -> Path:
    """Locate the run directory for a given run_id."""
    from src.agent.loop import RUNS_DIR
    candidate = RUNS_DIR / run_id
    if candidate.exists():
        return candidate
    # Fallback: treat run_id as a literal path
    return Path(run_id)


class TrustLayerTool(BaseTool):
    """Attach provenance to a completed research result.

    Call structure_research at the end of every research or strategy session
    to formally record the hypothesis, assumptions (with invalidation triggers),
    evidence, and failure modes. The tool merges this with data already
    passively extracted during the run (sources, code hash, backtest metrics).

    Use the decide action to record a PM checkpoint decision against a prior artifact.
    """

    name = "structure_research"
    description = (
        "Attach provenance to a completed research result. "
        "action=structure: record hypothesis, assumptions (with invalidation_trigger), "
        "evidence (source-attributed), and failure modes for this run. "
        "action=decide: record a PM approval/rejection against an existing artifact."
    )
    is_readonly = False
    repeatable = True

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["structure", "decide"],
                "description": "structure: save research provenance. decide: record PM decision.",
            },
            "run_id": {
                "type": "string",
                "description": "Run directory name this research belongs to (for structure).",
            },
            "hypothesis": {
                "type": "string",
                "description": (
                    "One falsifiable sentence: what does this research claim and "
                    "under what conditions? Be specific about the signal, asset, regime, "
                    "and expected quantitative outcome."
                ),
            },
            "assumptions": {
                "type": "array",
                "description": "Explicit priors this hypothesis depends on.",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {
                            "type": "string",
                            "description": "The assumption being made.",
                        },
                        "basis": {
                            "type": "string",
                            "description": "Why this assumption is currently valid.",
                        },
                        "invalidation_trigger": {
                            "type": "string",
                            "description": (
                                "Observable condition that would require re-evaluating "
                                "this assumption (e.g. 'VIX > 25 for 5+ consecutive days')."
                            ),
                        },
                    },
                    "required": ["statement"],
                },
            },
            "evidence": {
                "type": "array",
                "description": "Supporting and contradicting evidence, each source-attributed.",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "source_tool": {
                            "type": "string",
                            "description": "Tool that produced this evidence (e.g. web_search, read_document).",
                        },
                        "source_ref": {
                            "type": "string",
                            "description": "Query string, file path, or URL.",
                        },
                        "polarity": {
                            "type": "string",
                            "enum": ["supporting", "contradicting", "neutral"],
                        },
                        "strength": {
                            "type": "string",
                            "enum": ["strong", "moderate", "weak"],
                        },
                    },
                    "required": ["claim", "polarity"],
                },
            },
            "failure_modes": {
                "type": "array",
                "description": "Named conditions under which this hypothesis would be falsified.",
                "items": {
                    "type": "object",
                    "properties": {
                        "condition": {
                            "type": "string",
                            "description": "What would make this hypothesis wrong.",
                        },
                        "probability": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                        "monitoring_signal": {
                            "type": "string",
                            "description": "Observable to watch to detect this condition early.",
                        },
                    },
                    "required": ["condition"],
                },
            },
            "artifact_id": {
                "type": "string",
                "description": "For decide: the artifact_id to record the PM decision against.",
            },
            "decision": {
                "type": "string",
                "enum": ["approved", "rejected", "needs_more_research"],
                "description": "For decide: the PM decision.",
            },
            "rationale": {
                "type": "string",
                "description": "For decide: why this decision was made.",
            },
            "conditions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "For decide: conditions attached to an approval.",
            },
        },
        "required": ["action"],
    }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "structure")
        if action == "structure":
            return self._structure(kwargs)
        if action == "decide":
            return self._decide(kwargs)
        return json.dumps({"status": "error", "error": f"Unknown action: {action}"})

    # ------------------------------------------------------------------

    def _structure(self, kwargs: dict) -> str:
        run_id = kwargs.get("run_id", "")
        if not run_id:
            return json.dumps({"status": "error", "error": "run_id is required for action=structure"})

        run_dir = _resolve_run_dir(run_id)

        # Load a partial artifact already written by the passive builder if present.
        tl_path = run_dir / "trust_layer.json"
        if tl_path.exists():
            try:
                existing = ResearchArtifact.model_validate_json(tl_path.read_text(encoding="utf-8"))
                builder = TrustLayerBuilder.__new__(TrustLayerBuilder)
                builder._artifact = existing
                builder._run_dir = run_dir
                builder._code_hash = existing.strategy_code_hash or ""
            except Exception as exc:
                logger.warning("Could not reload partial artifact: %s", exc)
                builder = TrustLayerBuilder(run_id=run_id, run_dir=run_dir)
        else:
            builder = TrustLayerBuilder(run_id=run_id, run_dir=run_dir)

        builder.merge_structured({
            "hypothesis": kwargs.get("hypothesis", ""),
            "assumptions": kwargs.get("assumptions", []),
            "evidence": kwargs.get("evidence", []),
            "failure_modes": kwargs.get("failure_modes", []),
        })

        out_path = builder.finalize()
        stored_path = _store.save(builder.artifact)

        a = builder.artifact
        return json.dumps({
            "status": "ok",
            "artifact_id": a.artifact_id,
            "hypothesis_status": a.hypothesis_status,
            "is_complete": a.is_complete,
            "trust_layer_path": str(out_path),
            "stored_path": str(stored_path),
            "sources_found": len(a.data_sources),
            "validation_runs": len(a.validation_results),
            "message": (
                "Research artifact saved. "
                + ("Artifact is complete." if a.is_complete
                   else "Artifact is partial — add assumptions and failure_modes to complete it.")
            ),
        }, ensure_ascii=False)

    def _decide(self, kwargs: dict) -> str:
        artifact_id = kwargs.get("artifact_id", "")
        decision_str = kwargs.get("decision", "")
        if not artifact_id or not decision_str:
            return json.dumps({"status": "error", "error": "artifact_id and decision are required for action=decide"})

        decision = PMDecision(
            decision=decision_str,
            rationale=kwargs.get("rationale", ""),
            conditions=kwargs.get("conditions", []),
        )
        ok = _store.record_pm_decision(artifact_id, decision)
        if not ok:
            return json.dumps({"status": "error", "error": f"Artifact not found: {artifact_id}"})

        new_status = {"approved": "live", "rejected": "invalidated", "needs_more_research": "proposed"}[decision_str]
        return json.dumps({
            "status": "ok",
            "artifact_id": artifact_id,
            "decision": decision_str,
            "new_hypothesis_status": new_status,
        }, ensure_ascii=False)
