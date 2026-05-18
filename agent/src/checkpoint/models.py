"""Data models for the per-skill autonomy contract and approval records."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AutonomyMode(str, Enum):
    """How the skill's workflow handles human gates."""

    AUTO = "auto"          # runs to completion (still respects the universal pm_go_live gate if declared)
    HITL = "hitl"          # human-in-the-loop at one or more checkpoints
    SHADOW = "shadow"      # auto, but writes to a shadow portfolio instead of live


class ApprovalStatus(str, Enum):
    """Lifecycle of an `approvals` row."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    EXPIRED = "expired"


class DecisionAction(str, Enum):
    """What the PM did at the checkpoint."""

    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"     # approve with edits to the payload
    DEFER = "defer"       # park with a condition


@dataclass(frozen=True)
class CheckpointSpec:
    """One checkpoint declared in a skill's frontmatter."""

    id: str
    after_node: str
    prompt: str = ""
    payload_schema: Dict[str, Any] = field(default_factory=dict)
    allowed_edits: List[str] = field(default_factory=list)
    decision_types: List[DecisionAction] = field(default_factory=lambda: [DecisionAction.APPROVE, DecisionAction.REJECT])
    requires_role: Optional[str] = None
    ttl_hours: Optional[float] = None


@dataclass(frozen=True)
class AutonomySpec:
    """A skill's full autonomy contract, parsed from frontmatter."""

    mode: AutonomyMode = AutonomyMode.AUTO
    checkpoints: List[CheckpointSpec] = field(default_factory=list)

    def checkpoint(self, checkpoint_id: str) -> Optional[CheckpointSpec]:
        for cp in self.checkpoints:
            if cp.id == checkpoint_id:
                return cp
        return None


def parse_autonomy_spec(frontmatter_meta: Dict[str, Any]) -> AutonomySpec:
    """Build an ``AutonomySpec`` from a SKILL.md frontmatter mapping.

    Skills without an ``autonomy`` block default to ``mode=AUTO`` with no
    checkpoints, preserving fire-and-forget behavior for every existing skill.

    Raises ``ValueError`` if the autonomy block is structurally malformed
    (so a typo in a SKILL.md fails loud at load time, not at runtime).
    """
    raw = frontmatter_meta.get("autonomy")
    if raw is None:
        return AutonomySpec()

    if not isinstance(raw, dict):
        raise ValueError(f"autonomy must be a mapping, got {type(raw).__name__}")

    mode_str = raw.get("mode", "auto")
    try:
        mode = AutonomyMode(mode_str)
    except ValueError:
        raise ValueError(f"unknown autonomy.mode {mode_str!r}")

    checkpoints_raw = raw.get("checkpoints") or []
    if not isinstance(checkpoints_raw, list):
        raise ValueError("autonomy.checkpoints must be a list")

    seen_ids: set[str] = set()
    checkpoints: List[CheckpointSpec] = []
    for i, cp in enumerate(checkpoints_raw):
        if not isinstance(cp, dict):
            raise ValueError(f"autonomy.checkpoints[{i}] must be a mapping")
        if "id" not in cp or not cp["id"]:
            raise ValueError(f"autonomy.checkpoints[{i}] missing required 'id'")
        if "after_node" not in cp or not cp["after_node"]:
            raise ValueError(f"autonomy.checkpoints[{i}] missing required 'after_node'")
        if cp["id"] in seen_ids:
            raise ValueError(f"duplicate checkpoint id {cp['id']!r}")
        seen_ids.add(cp["id"])

        decisions_raw = cp.get("decision_types") or ["approve", "reject"]
        try:
            decision_types = [DecisionAction(d) for d in decisions_raw]
        except ValueError as e:
            raise ValueError(f"checkpoint {cp['id']!r} has invalid decision_types: {e}")

        checkpoints.append(
            CheckpointSpec(
                id=cp["id"],
                after_node=cp["after_node"],
                prompt=cp.get("prompt", ""),
                payload_schema=cp.get("payload_schema") or {},
                allowed_edits=list(cp.get("allowed_edits") or []),
                decision_types=decision_types,
                requires_role=cp.get("requires_role"),
                ttl_hours=cp.get("ttl_hours"),
            )
        )

    return AutonomySpec(mode=mode, checkpoints=checkpoints)


@dataclass
class Approval:
    """A single pending or resolved human checkpoint, persisted to ``approvals``.

    The thread_id is the LangGraph thread used for resume; we set
    thread_id == attempt_id so the existing Attempt lifecycle and the graph
    state stay in lockstep.
    """

    approval_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    thread_id: str = ""
    session_id: str = ""
    attempt_id: str = ""
    skill_name: str = ""
    checkpoint_id: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    prompt: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    allowed_edits: List[str] = field(default_factory=list)
    decision_types: List[DecisionAction] = field(default_factory=list)
    requires_role: Optional[str] = None
    decision: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    decided_at: Optional[float] = None

    @classmethod
    def from_checkpoint(
        cls,
        *,
        spec: CheckpointSpec,
        session_id: str,
        attempt_id: str,
        skill_name: str,
        payload: Dict[str, Any],
        thread_id: Optional[str] = None,
        now: Optional[float] = None,
    ) -> "Approval":
        """Build a pending Approval from a checkpoint spec + runtime payload.

        ``approval_id`` is deterministic over ``(thread_id, checkpoint_id)``
        so that LangGraph's idempotent re-execution of a checkpoint node on
        resume doesn't create duplicate rows.
        """
        now = now or time.time()
        thread = thread_id or attempt_id
        return cls(
            approval_id=f"{thread}__{spec.id}",
            thread_id=thread,
            session_id=session_id,
            attempt_id=attempt_id,
            skill_name=skill_name,
            checkpoint_id=spec.id,
            status=ApprovalStatus.PENDING,
            prompt=spec.prompt,
            payload=payload,
            allowed_edits=list(spec.allowed_edits),
            decision_types=list(spec.decision_types),
            requires_role=spec.requires_role,
            created_at=now,
            expires_at=(now + spec.ttl_hours * 3600.0) if spec.ttl_hours else None,
        )

    def to_row(self) -> tuple:
        """Serialize to the column tuple stored in the ``approvals`` table."""
        return (
            self.approval_id,
            self.thread_id,
            self.session_id,
            self.attempt_id,
            self.skill_name,
            self.checkpoint_id,
            self.status.value,
            self.prompt,
            json.dumps(self.payload),
            json.dumps(self.allowed_edits),
            json.dumps([d.value for d in self.decision_types]),
            self.requires_role,
            json.dumps(self.decision) if self.decision is not None else None,
            self.created_at,
            self.expires_at,
            self.decided_at,
        )

    @classmethod
    def from_row(cls, row: tuple) -> "Approval":
        """Inverse of ``to_row`` — hydrate from a SQLite row."""
        return cls(
            approval_id=row[0],
            thread_id=row[1],
            session_id=row[2],
            attempt_id=row[3],
            skill_name=row[4],
            checkpoint_id=row[5],
            status=ApprovalStatus(row[6]),
            prompt=row[7],
            payload=json.loads(row[8]) if row[8] else {},
            allowed_edits=json.loads(row[9]) if row[9] else [],
            decision_types=[DecisionAction(d) for d in (json.loads(row[10]) if row[10] else [])],
            requires_role=row[11],
            decision=json.loads(row[12]) if row[12] else None,
            created_at=row[13],
            expires_at=row[14],
            decided_at=row[15],
        )

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe shape for the HTTP API."""
        return {
            "approval_id": self.approval_id,
            "thread_id": self.thread_id,
            "session_id": self.session_id,
            "attempt_id": self.attempt_id,
            "skill_name": self.skill_name,
            "checkpoint_id": self.checkpoint_id,
            "status": self.status.value,
            "prompt": self.prompt,
            "payload": self.payload,
            "allowed_edits": self.allowed_edits,
            "decision_types": [d.value for d in self.decision_types],
            "requires_role": self.requires_role,
            "decision": self.decision,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "decided_at": self.decided_at,
        }
