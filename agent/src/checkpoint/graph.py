"""Per-skill LangGraph wiring that pauses at autonomy checkpoints.

The graph builder sits **above** the existing ``AgentLoop`` and ``SwarmRuntime``
runtimes — those are called from work nodes as black-box workers. Checkpoint
nodes call ``langgraph.interrupt`` to pause; the SqliteSaver persists state
to the shared ``sessions.db``.

``langgraph`` is imported lazily so this module is importable in environments
that haven't installed it yet (the data + service layers don't need it).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING, Union
from typing_extensions import TypedDict

from src.checkpoint.models import (
    Approval,
    AutonomySpec,
    CheckpointSpec,
    DecisionAction,
)
from src.checkpoint.service import ApprovalService

if TYPE_CHECKING:  # pragma: no cover
    from langgraph.graph import StateGraph
    from langgraph.checkpoint.sqlite import SqliteSaver


# Lazy import sentinels — populated by _load_langgraph() on first use.
_StateGraph: Any = None
_END: Any = None
_START: Any = None
_interrupt: Any = None
_Command: Any = None
_SqliteSaver: Any = None


def _load_langgraph() -> None:
    """Import langgraph on demand. Raises a clear error if not installed."""
    global _StateGraph, _END, _START, _interrupt, _Command, _SqliteSaver
    if _StateGraph is not None:
        return
    try:
        from langgraph.graph import StateGraph, END, START
        from langgraph.types import interrupt, Command
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:  # pragma: no cover — environment-dependent
        raise RuntimeError(
            "langgraph is not installed. Add 'langgraph>=0.2.50,<0.3' and "
            "'langgraph-checkpoint>=2.0.0' to your environment to build "
            "checkpoint graphs."
        ) from exc
    _StateGraph = StateGraph
    _END = END
    _START = START
    _interrupt = interrupt
    _Command = Command
    _SqliteSaver = SqliteSaver


# The graph's persistent state is intentionally small — the AgentLoop message
# buffer can be 40k+ tokens and we do NOT want to round-trip it through the
# checkpointer on every super-step. Heavy artifacts live under ``run_dir``.
@dataclass
class GraphState:
    run_dir: str
    skill_name: str
    session_id: str
    attempt_id: str
    current_checkpoint: Optional[str] = None
    last_artifact_paths: Dict[str, str] = None
    pending_payload: Dict[str, Any] = None
    checkpoint_overrides: Dict[str, Dict[str, Any]] = None  # checkpoint_id -> edits
    completed: bool = False
    rejected_at: Optional[str] = None

    def __post_init__(self) -> None:
        if self.last_artifact_paths is None:
            self.last_artifact_paths = {}
        if self.pending_payload is None:
            self.pending_payload = {}
        if self.checkpoint_overrides is None:
            self.checkpoint_overrides = {}

    def as_dict(self) -> Dict[str, Any]:
        return {
            "run_dir": self.run_dir,
            "skill_name": self.skill_name,
            "session_id": self.session_id,
            "attempt_id": self.attempt_id,
            "current_checkpoint": self.current_checkpoint,
            "last_artifact_paths": self.last_artifact_paths,
            "pending_payload": self.pending_payload,
            "checkpoint_overrides": self.checkpoint_overrides,
            "completed": self.completed,
            "rejected_at": self.rejected_at,
        }


WorkFn = Callable[[GraphState], Dict[str, Any]]
"""A work-node function. Takes the current state, returns a state-update dict.

Implementations call into ``AgentLoop.run()`` or ``SwarmRuntime`` as needed.
Returning ``{"pending_payload": {...}}`` stages what the next checkpoint
will show the PM. Returning ``{"last_artifact_paths": {...}}`` records
artifact locations the next node should read from disk.
"""


class CheckpointGraphBuilder:
    """Builds a ``StateGraph`` for one skill from its frontmatter autonomy spec.

    Wiring contract:
        node sequence = [START, work_node_1, (checkpoint?), work_node_2, ...]

    Each ``CheckpointSpec.after_node`` names the work node whose output the
    checkpoint inspects. We insert a checkpoint node immediately after that
    work node; the checkpoint node calls ``interrupt(payload)`` and waits.

    Resume contract: ``Command(resume={"action": "approve"|"reject"|"modify",
    "edits": {...}})`` is the payload caller passes to ``graph.invoke`` after a
    decision; the checkpoint node returns a state delta accordingly.
    """

    def __init__(
        self,
        *,
        skill_name: str,
        autonomy: AutonomySpec,
        work_nodes: Dict[str, WorkFn],
        node_order: List[str],
        approval_service: ApprovalService,
        sqlite_connection: Union[sqlite3.Connection, str, Path],
    ) -> None:
        """Build a per-skill checkpoint graph.

        ``sqlite_connection`` may be either a ``sqlite3.Connection`` (must be
        configured with ``isolation_level=None`` so LangGraph's SqliteSaver
        can manage its own transactions) or a DB path/string — in which case
        the builder opens a fresh dedicated connection. The DB-path form is
        the recommended one: it shares the file (and thus the ``approvals``
        table) with the rest of the app without sharing transaction state.
        """
        self.skill_name = skill_name
        self.autonomy = autonomy
        self.work_nodes = work_nodes
        self.node_order = node_order
        self.approval_service = approval_service
        if isinstance(sqlite_connection, (str, Path)):
            self._conn = sqlite3.connect(
                str(sqlite_connection),
                check_same_thread=False,
                isolation_level=None,
            )
        else:
            self._conn = sqlite_connection
        self._validate()

    def _validate(self) -> None:
        missing = [n for n in self.node_order if n not in self.work_nodes]
        if missing:
            raise ValueError(f"node_order references undefined work nodes: {missing}")
        for cp in self.autonomy.checkpoints:
            if cp.after_node not in self.work_nodes:
                raise ValueError(
                    f"checkpoint {cp.id!r} after_node {cp.after_node!r} "
                    f"is not in work_nodes"
                )

    def build(self):
        """Compile a LangGraph ``StateGraph`` with a SqliteSaver checkpointer.

        Uses a TypedDict schema so per-node returns shallow-merge into state
        (a plain ``dict`` schema would replace state entirely each tick).
        """
        _load_langgraph()

        class _State(TypedDict, total=False):
            run_dir: str
            skill_name: str
            session_id: str
            attempt_id: str
            current_checkpoint: Optional[str]
            last_artifact_paths: Dict[str, str]
            pending_payload: Dict[str, Any]
            checkpoint_overrides: Dict[str, Dict[str, Any]]
            completed: bool
            rejected_at: Optional[str]

        graph = _StateGraph(_State)

        for node_name in self.node_order:
            graph.add_node(node_name, _wrap_work(self.work_nodes[node_name]))

        # Map after_node -> checkpoint spec so we can splice checkpoint nodes in.
        by_after = {cp.after_node: cp for cp in self.autonomy.checkpoints}

        # Wire START -> first node, then for each pair: prev -> [optional checkpoint] -> next
        graph.add_edge(_START, self.node_order[0])
        for i, node_name in enumerate(self.node_order):
            cp = by_after.get(node_name)
            next_target = self.node_order[i + 1] if i + 1 < len(self.node_order) else _END

            if cp is None:
                graph.add_edge(node_name, next_target)
                continue

            cp_node = f"_checkpoint_{cp.id}"
            graph.add_node(
                cp_node,
                _make_checkpoint_node(
                    spec=cp,
                    skill_name=self.skill_name,
                    approval_service=self.approval_service,
                ),
            )
            graph.add_edge(node_name, cp_node)
            # Conditional routing: rejection ends the run, approval/modify continue.
            graph.add_conditional_edges(
                cp_node,
                _route_after_checkpoint,
                {"continue": next_target if next_target != _END else _END, "end": _END},
            )

        saver = _SqliteSaver(self._conn)
        return graph.compile(checkpointer=saver)


def _wrap_work(fn: WorkFn) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Adapt a WorkFn to LangGraph's (state_dict) -> state_delta_dict shape."""

    def _node(state: Dict[str, Any]) -> Dict[str, Any]:
        gs = GraphState(
            run_dir=state["run_dir"],
            skill_name=state["skill_name"],
            session_id=state["session_id"],
            attempt_id=state["attempt_id"],
            current_checkpoint=state.get("current_checkpoint"),
            last_artifact_paths=dict(state.get("last_artifact_paths") or {}),
            pending_payload=dict(state.get("pending_payload") or {}),
            checkpoint_overrides=dict(state.get("checkpoint_overrides") or {}),
            completed=bool(state.get("completed")),
            rejected_at=state.get("rejected_at"),
        )
        delta = fn(gs) or {}
        return delta

    return _node


def _make_checkpoint_node(
    *,
    spec: CheckpointSpec,
    skill_name: str,
    approval_service: ApprovalService,
):
    """Build the node function that raises a checkpoint via ``interrupt()``.

    The node:
        1. Writes an ``Approval`` row (status=pending) so the Inbox sees it.
        2. Calls ``interrupt(payload)`` — graph pauses, state is checkpointed.
        3. On resume, returns a state delta that records the decision/edits.

    Reject returns ``{"rejected_at": spec.id}`` so the conditional edge ends
    the run; the runtime will mark the Attempt FAILED via the resume callback.
    """

    def _node(state: Dict[str, Any]) -> Dict[str, Any]:
        _load_langgraph()
        session_id = state["session_id"]
        attempt_id = state["attempt_id"]
        payload = dict(state.get("pending_payload") or {})

        approval = Approval.from_checkpoint(
            spec=spec,
            session_id=session_id,
            attempt_id=attempt_id,
            skill_name=skill_name,
            payload=payload,
            thread_id=attempt_id,
        )
        approval_service.create(approval)

        # PAUSE — LangGraph will persist the state and return control to the
        # API caller. When ApprovalService.submit_decision resumes the graph,
        # the value passed via Command(resume=...) becomes the return value.
        resume_value = _interrupt({  # type: ignore[misc]
            "approval_id": approval.approval_id,
            "checkpoint_id": spec.id,
            "prompt": spec.prompt,
            "payload": payload,
            "allowed_edits": list(spec.allowed_edits),
            "decision_types": [d.value for d in spec.decision_types],
        })

        action = (resume_value or {}).get("action")
        edits = (resume_value or {}).get("edits") or {}

        delta: Dict[str, Any] = {"current_checkpoint": spec.id}
        if action == DecisionAction.REJECT.value:
            delta["rejected_at"] = spec.id
        elif edits:
            overrides = dict(state.get("checkpoint_overrides") or {})
            overrides[spec.id] = edits
            delta["checkpoint_overrides"] = overrides
        return delta

    return _node


def _route_after_checkpoint(state: Dict[str, Any]) -> str:
    """Conditional edge: end the run if the last checkpoint was rejected."""
    return "end" if state.get("rejected_at") else "continue"
