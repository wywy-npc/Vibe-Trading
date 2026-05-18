"""Approval persistence + Inbox queries against the shared sessions SQLite DB."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

from src.checkpoint.models import (
    Approval,
    ApprovalStatus,
    DecisionAction,
)

logger = logging.getLogger(__name__)


class NotFoundError(LookupError):
    """Raised when an approval_id has no row."""


class ConflictError(RuntimeError):
    """Raised when a decision is submitted on an approval that is no longer pending.

    Maps to HTTP 409. Caused by a second PM acting on the same checkpoint, or
    by TTL expiry racing a decision.
    """


_COLUMNS = (
    "approval_id, thread_id, session_id, attempt_id, skill_name, checkpoint_id, "
    "status, prompt, payload_json, allowed_edits_json, decision_types_json, "
    "requires_role, decision_json, created_at, expires_at, decided_at"
)


class ApprovalService:
    """CRUD + Inbox queries for human checkpoints.

    Owns no schema migration of its own — the ``approvals`` table is created
    by ``SessionSearchIndex._init_db`` so we share one WAL connection.

    Callbacks (all optional):
    - ``pause_callback(approval)`` — fired when a *new* approval row is truly
      inserted (INSERT OR IGNORE on existing rows is a no-op, no callback).
      Use this to flip Attempt.status → WAITING_USER.
    - ``resume_callback(approval)`` — fired after a successful approve / modify /
      defer.  Drives ``graph.invoke(Command(resume=...))`` and returns metadata
      surfaced to the API caller.
    - ``reject_callback(approval)`` — fired after a successful reject.  Use this
      to flip Attempt.status → FAILED and stop the graph.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        resume_callback: Optional[Callable[[Approval], Dict[str, Any]]] = None,
        pause_callback: Optional[Callable[[Approval], None]] = None,
        reject_callback: Optional[Callable[[Approval], None]] = None,
    ) -> None:
        self._conn = connection
        self._resume_callback = resume_callback
        self._pause_callback = pause_callback
        self._reject_callback = reject_callback

    def create(self, approval: Approval) -> Approval:
        """Persist a pending approval row.

        Uses ``INSERT OR IGNORE`` so the LangGraph idempotent-node retry
        pattern (where a checkpoint node re-executes on resume) doesn't
        explode with duplicate-PK errors. When a row with this approval_id
        already exists we silently keep the original — its status reflects
        the prior decision and the graph's saved interrupt resolves
        immediately, so no work is lost.

        ``pause_callback`` is only invoked when a row was *truly* inserted
        (rowcount == 1), not on the no-op re-execution path.
        """
        cursor = self._conn.execute(
            f"INSERT OR IGNORE INTO approvals ({_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            approval.to_row(),
        )
        self._conn.commit()
        if cursor.rowcount == 1 and self._pause_callback is not None:
            try:
                self._pause_callback(approval)
            except Exception:
                logger.exception("pause_callback failed for approval %s", approval.approval_id)
        return approval

    def get(self, approval_id: str) -> Approval:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(approval_id)
        return Approval.from_row(row)

    def list_pending(
        self,
        *,
        session_id: Optional[str] = None,
        requires_role: Optional[str] = None,
        limit: int = 50,
    ) -> List[Approval]:
        """Inbox query — pending approvals ordered newest first."""
        clauses = ["status = ?"]
        params: List[Any] = [ApprovalStatus.PENDING.value]
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if requires_role:
            clauses.append("(requires_role IS NULL OR requires_role = ?)")
            params.append(requires_role)
        params.append(int(limit))

        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM approvals WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [Approval.from_row(r) for r in rows]

    def submit_decision(
        self,
        approval_id: str,
        action: DecisionAction,
        *,
        edits: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
        decided_by: str = "",
        defer_condition: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve a pending approval and (on approve/modify/defer) resume the run.

        Race semantics: a single ``UPDATE ... WHERE status='pending'`` in WAL
        mode is atomic. If another decision landed first, rowcount==0 and we
        raise ConflictError → HTTP 409.

        Modify validates ``edits ⊆ allowed_edits`` before resuming.
        """
        approval = self.get(approval_id)

        if action not in approval.decision_types:
            raise ValueError(
                f"action {action.value!r} not permitted; allowed: "
                f"{[d.value for d in approval.decision_types]}"
            )

        edits = edits or {}
        if action == DecisionAction.MODIFY:
            if not edits:
                raise ValueError("modify action requires non-empty edits")
            disallowed = set(edits.keys()) - set(approval.allowed_edits)
            if disallowed:
                raise ValueError(
                    f"edits to {sorted(disallowed)} are not in allowed_edits "
                    f"{approval.allowed_edits}"
                )

        new_status = {
            DecisionAction.APPROVE: ApprovalStatus.APPROVED,
            DecisionAction.MODIFY: ApprovalStatus.APPROVED,
            DecisionAction.REJECT: ApprovalStatus.REJECTED,
            DecisionAction.DEFER: ApprovalStatus.DEFERRED,
        }[action]

        decision = {
            "action": action.value,
            "edits": edits,
            "reason": reason,
            "decided_by": decided_by,
            "decided_at": time.time(),
        }
        if defer_condition:
            decision["defer_condition"] = defer_condition

        now = time.time()
        cursor = self._conn.execute(
            "UPDATE approvals SET status = ?, decision_json = ?, decided_at = ? "
            "WHERE approval_id = ? AND status = ?",
            (new_status.value, json.dumps(decision), now, approval_id, ApprovalStatus.PENDING.value),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            raise ConflictError(f"approval {approval_id} is no longer pending")

        approval.status = new_status
        approval.decision = decision
        approval.decided_at = now

        # Hand back to the runtime so it can update_state + resume the graph.
        # On reject we call reject_callback (not resume_callback) so the
        # runtime can mark the Attempt FAILED before returning.
        resume_result: Dict[str, Any] = {"approval": approval.to_dict()}
        if action == DecisionAction.REJECT:
            if self._reject_callback is not None:
                try:
                    self._reject_callback(approval)
                except Exception:
                    logger.exception("reject_callback failed for approval %s", approval_id)
        else:
            if self._resume_callback is not None:
                try:
                    runtime_result = self._resume_callback(approval) or {}
                    resume_result.update(runtime_result)
                except Exception as exc:
                    logger.exception("resume_callback failed for approval %s", approval_id)
                    resume_result["resume_error"] = str(exc)
        resume_result.setdefault(
            "status", "terminated" if action == DecisionAction.REJECT else "resumed"
        )
        return resume_result

    def expire_stale(self, *, now: Optional[float] = None) -> int:
        """Flip pending approvals past their ``expires_at`` to ``expired``.

        Returns the number of rows expired. Safe to call repeatedly from a
        background tick. For each expired row we synthesize a reject-style
        decision JSON so the audit trail records WHY it expired.
        """
        now = now or time.time()
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM approvals "
            "WHERE status = ? AND expires_at IS NOT NULL AND expires_at <= ?",
            (ApprovalStatus.PENDING.value, now),
        ).fetchall()
        if not rows:
            return 0

        decision = json.dumps({
            "action": DecisionAction.REJECT.value,
            "reason": "ttl_expired",
            "decided_by": "system",
            "decided_at": now,
        })
        ids = [r[0] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        self._conn.execute(
            f"UPDATE approvals SET status = ?, decision_json = ?, decided_at = ? "
            f"WHERE approval_id IN ({placeholders}) AND status = ?",
            [ApprovalStatus.EXPIRED.value, decision, now, *ids, ApprovalStatus.PENDING.value],
        )
        self._conn.commit()
        return len(rows)
