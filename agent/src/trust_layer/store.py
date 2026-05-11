"""HypothesisStore: cross-session persistent store for ResearchArtifacts.

Storage layout:
    ~/.vibe-trading/hypotheses/
    ├── index.json              — fast lookup index keyed by artifact_id
    ├── <artifact_id>.json      — full ResearchArtifact
    └── <artifact_id>_v<n>.json — archived prior version (never deleted)

Version history is append-only. When an artifact is updated, the old version
is archived before the new version overwrites the primary file. This ensures
a full audit trail of hypothesis evolution.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import List, Optional

from src.trust_layer.models import PMDecision, ResearchArtifact

logger = logging.getLogger(__name__)

HYPOTHESIS_BASE = Path.home() / ".vibe-trading" / "hypotheses"

_STATUS_AFTER_DECISION = {
    "approved": "live",
    "rejected": "invalidated",
    "needs_more_research": "proposed",
}


class HypothesisStore:
    """Persistent cross-session store for ResearchArtifacts."""

    def __init__(self, store_dir: Optional[Path] = None) -> None:
        self._dir = store_dir or HYPOTHESIS_BASE
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "index.json"

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save(self, artifact: ResearchArtifact) -> Path:
        """Persist an artifact, archiving the prior version if one exists."""
        primary = self._dir / f"{artifact.artifact_id}.json"

        if primary.exists():
            try:
                old = ResearchArtifact.model_validate_json(primary.read_text(encoding="utf-8"))
                archive = self._dir / f"{artifact.artifact_id}_v{old.version}.json"
                archive.write_text(old.model_dump_json(indent=2), encoding="utf-8")
                artifact = artifact.model_copy(update={"version": old.version + 1})
            except Exception as exc:
                logger.debug("Version archive failed for %s: %s", artifact.artifact_id, exc)

        primary.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        self._update_index(artifact)
        return primary

    def record_pm_decision(self, artifact_id: str, decision: PMDecision) -> bool:
        """Attach a PM decision to an existing artifact and update its status."""
        artifact = self.get(artifact_id)
        if not artifact:
            return False
        new_status = _STATUS_AFTER_DECISION.get(decision.decision, artifact.hypothesis_status)
        updated = artifact.model_copy(update={
            "pm_decision": decision,
            "hypothesis_status": new_status,
            "updated_at": time.time(),
        })
        self.save(updated)
        return True

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, artifact_id: str) -> Optional[ResearchArtifact]:
        path = self._dir / f"{artifact_id}.json"
        if not path.exists():
            return None
        try:
            return ResearchArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load artifact %s: %s", artifact_id, exc)
            return None

    def list_by_status(self, status: str) -> List[dict]:
        """Return index summaries for all artifacts with a given hypothesis_status."""
        return [v for v in self._load_index().values() if v.get("hypothesis_status") == status]

    def list_all(self) -> List[dict]:
        """Return all index summaries, sorted by updated_at descending."""
        entries = list(self._load_index().values())
        entries.sort(key=lambda e: e.get("updated_at", 0), reverse=True)
        return entries

    def get_for_run(self, run_id: str) -> Optional[ResearchArtifact]:
        """Return the artifact for a specific run_id if it exists."""
        for entry in self._load_index().values():
            if entry.get("run_id") == run_id:
                return self.get(entry["artifact_id"])
        return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_index(self) -> dict:
        if not self._index_path.exists():
            return {}
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _update_index(self, artifact: ResearchArtifact) -> None:
        index = self._load_index()
        index[artifact.artifact_id] = {
            "artifact_id": artifact.artifact_id,
            "run_id": artifact.run_id,
            "hypothesis": artifact.hypothesis[:200],
            "hypothesis_status": artifact.hypothesis_status,
            "is_complete": artifact.is_complete,
            "updated_at": artifact.updated_at,
            "version": artifact.version,
        }
        self._index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )
