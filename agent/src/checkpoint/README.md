# `agent/src/checkpoint/`

LangGraph-based human-in-the-loop (HITL) approval system. Pauses skill execution at declared checkpoints, persists pending decisions to SQLite, and resumes on PM approval.

## Layout

```
checkpoint/
├── models.py    # AutonomyMode, ApprovalStatus, CheckpointSpec, Approval, parse_autonomy_spec
├── service.py   # ApprovalService: CRUD + Inbox queries + submit_decision (resume callback)
├── graph.py     # CheckpointGraphBuilder: wires per-skill LangGraph state machines
└── registry.py  # Dynamic loader for skills/*/pipeline.py modules (hyphenated names)
```

## When to use

A skill needs the checkpoint module when its workflow has *qualitative→quantitative seams* where a PM (or other human role) must confirm or override an autonomous step. Examples:

- "Did the agent interpret my thesis correctly?" — `thesis-to-rules` `thesis_interpretation` gate.
- "Are these the right systematic rules?" — same skill's `rule_codification` gate.
- "Is this position size right given the rest of the book?" — `position_sizing` gate.

If the skill is a single autonomous pipeline with no human seam (e.g. `strategy-discovery` → `research_loop`), you don't need the checkpoint module.

## Autonomy frontmatter

Each HITL skill declares its approval contract in `SKILL.md` frontmatter:

```yaml
---
name: thesis-to-rules
autonomy:
  mode: hitl
  checkpoints:
    - id: thesis_interpretation
      after_node: parse_thesis
      prompt: "Confirm the agent's interpretation of your thesis."
      payload_schema:
        thesis_text: string
        identified_drivers: list[string]
      allowed_edits: [identified_drivers, time_horizon]
      decision_types: [approve, reject, modify]
      ttl_hours: 72
---
```

`parse_autonomy_spec(meta)` in `models.py` validates this block. `frontmatter.parse_frontmatter` now uses `yaml.safe_load` (rather than the older line-by-line parser) so nested mappings and lists work natively.

## Authoring a skill `pipeline.py`

A skill's `pipeline.py` exports two things:

1. **One `WorkFn` per node**, taking `state: GraphState` and returning a dict containing `pending_payload` (what the PM sees at the next checkpoint) and optionally `last_artifact_paths` (where the next node should read inputs from). See `thesis-to-rules/pipeline.py` for the canonical example.
2. **`build_graph(approval_service, sqlite_connection)`** — calls `CheckpointGraphBuilder` to wire the nodes against the autonomy spec.

```python
def _my_node(state: GraphState) -> Dict[str, Any]:
    return {
        "pending_payload": {"sharpe": 0.9, "max_dd": -0.12},
        "last_artifact_paths": {"report": str(Path(state.run_dir) / "report.html")},
    }

def build_graph(approval_service, sqlite_connection):
    meta, _ = parse_frontmatter(SKILL_MD.read_text())
    autonomy = parse_autonomy_spec(meta)
    return CheckpointGraphBuilder(
        skill_name=meta["name"],
        autonomy=autonomy,
        work_nodes={"my_node": _my_node, ...},
        node_order=["my_node", ...],
        approval_service=approval_service,
        sqlite_connection=sqlite_connection,
    ).build()
```

## Data flow

1. User triggers `POST /skills/{skill_name}/run` with initial state.
2. `registry.get_build_graph(skill_name)` dynamically loads `pipeline.py`.
3. The compiled graph invokes work nodes until it hits a checkpoint.
4. The checkpoint node calls `interrupt(payload)`; LangGraph's `SqliteSaver` persists state.
5. The API returns `{"approval_id": ..., "status": "waiting"}`.
6. Frontend `Inbox.tsx` shows the pending approval; PM submits a decision via `POST /approvals/{id}/decide`.
7. `ApprovalService.submit_decision` atomically resolves the row and fires `resume_callback`.
8. The callback re-builds the graph and invokes `Command(resume={action, edits})`.
9. The graph runs to the next checkpoint (or completion); the cycle repeats.

## SQLite co-location

The `approvals` table lives in `sessions.db` alongside the rest of the session/attempt state. `SessionSearchIndex._init_db()` creates the schema; `SessionSearchIndex.connection` exposes the shared connection.

LangGraph's `SqliteSaver` needs its own dedicated connection (it manages BEGIN/COMMIT manually) — `CheckpointGraphBuilder` opens a fresh autocommit connection against the same file rather than sharing the approvals connection's transaction state.

## HITL feature flag

All approval endpoints in `api_server.py` are gated by `ENABLE_HITL=true` (default off). Without the flag, `GET /approvals` and `POST /approvals/{id}/decide` return 501. The frontend `Inbox` detects 501 and renders a banner explaining how to enable.

## `SwarmTask.waiting_user` status

The swarm runtime has a `waiting_user` task status (`src/swarm/models.py:24`) for swarm-orchestrated skills that pause at HITL checkpoints. Resume via PM decision → swarm task transitions back to `in_progress`.

## Canonical example

[`agent/src/skills/thesis-to-rules/pipeline.py`](../../skills/thesis-to-rules/pipeline.py) is the reference implementation. It exercises all four checkpoint types (approve, reject, modify, defer), uses real `AgentLoop` calls for the LLM-driven parse/codify nodes, and dispatches to the existing backtest runner for `_run_backtest`.

## Note on `gates.json` produced by thesis-to-rules

`thesis-to-rules` writes **two** `gates.json` files at different paths and they mean different things:

- `<run_dir>/backtest/gates.json` — the real AQL gate output (Deflated Sharpe / correlation / PCA / leakage) from the post-engine hook on the thesis-backtest. Read by `validate_run`. `via="thesis"`.
- `<run_dir>/gates.json` — a *substitute gate stamp* (`source="thesis_pm_approval"`) emitted by the deploy node, recording the chain of PM approval IDs as the audit trail. Read by `deploy_strategy_tool`, which skips the survivor-memory check when this source is present.

When copying `thesis-to-rules` as a template, decide which gate model your skill follows: statistical (write only the inner `gates.json`) or PM-approval (write the root file with `source`). Don't write both at the same path or `deploy_strategy_tool` and `validate_run` will trip over each other.
