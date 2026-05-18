"""Pipeline for the ``thesis-to-rules`` skill.

Defines one ``WorkFn`` per graph node. Production-quality nodes call AgentLoop
for LLM-driven work (parse_thesis, codify_rules) and dispatch to the existing
backtest runner (run_backtest). Each node has a structured stub fallback so
the checkpoint plumbing can be tested in CI without LLM credentials or full
market-data access.

Runs produced here are stamped ``via="thesis"`` so the P0 hard-gate invariant
(only ``research_loop`` runs are loop-gated) is preserved. ``validate_run``
will refuse them by default; analysts can pass ``allow_non_loop=true`` for
re-checks. Thesis-to-rules has its own audit trail (the PM approval chain),
which is the canonical record.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

import pandas as pd

from src.agent.frontmatter import parse_frontmatter
from src.checkpoint.graph import CheckpointGraphBuilder, GraphState
from src.checkpoint.models import parse_autonomy_spec
from src.checkpoint.service import ApprovalService

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).parent
SKILL_MD = SKILL_DIR / "SKILL.md"

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_THESIS_PARSE_PROMPT = """\
You are reading a qualitative investment thesis. Extract and return a JSON object
with exactly these fields — no additional keys, no extra explanation:

{{
  "thesis_text": "<one-paragraph summary of the core thesis argument>",
  "identified_drivers": ["<driver 1>", "<driver 2>", ...],
  "time_horizon": "<e.g. 3-6 months, 12 months, multi-year>",
  "asset_universe": ["<ticker or instrument 1>", ...],
  "regime_assumptions": ["<macro or market regime the thesis requires>", ...]
}}

The thesis to parse:
---
{thesis}
---

Return ONLY the JSON object, no markdown fences.
"""

_CODIFY_RULES_PROMPT = """\
You are translating a qualitative investment thesis into a deterministic
systematic rule set. The PM-approved interpretation is:

```json
{interpretation}
```

Produce a JSON object with these fields and nothing else:

{{
  "rules_dsl": "<the full Python source of a SignalEngine class that implements the thesis. Must be parseable Python 3.10+. Must define `class SignalEngine` with `generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]`. Signals are -1/0/+1 per timestamp. Pure pandas/numpy, no I/O.>",
  "entry_logic": "<one-paragraph plain-english description of entry conditions>",
  "exit_logic": "<one-paragraph plain-english description of exit conditions>",
  "invalidation_triggers": ["<trigger 1>", "<trigger 2>", ...]
}}

The Python you write in `rules_dsl` will be executed against historical bars
for the asset universe. It must use only `pd.DataFrame.rolling`, `shift`,
arithmetic, and similar deterministic operations. Do NOT call external APIs,
read files, or use randomness.

Return ONLY the JSON object, no markdown fences.
"""

# ---------------------------------------------------------------------------
# AgentLoop helper
# ---------------------------------------------------------------------------


def _run_agent(prompt: str, run_dir: str, session_id: str) -> Optional[str]:
    """Invoke AgentLoop synchronously; return the response text or None on failure."""
    try:
        from src.tools import build_registry
        from src.providers.chat import ChatLLM
        from src.agent.loop import AgentLoop
        from src.memory.persistent import PersistentMemory

        pm = PersistentMemory()
        agent = AgentLoop(
            registry=build_registry(persistent_memory=pm),
            llm=ChatLLM(),
            max_iterations=10,
            persistent_memory=pm,
        )
        result = agent.run(user_message=prompt, session_id=session_id)
        return result.get("content") or result.get("summary") or ""
    except Exception as exc:
        logger.warning("AgentLoop call failed (%s) — falling back to stub output", exc)
        return None


def _extract_json_object(raw: str) -> Optional[Dict[str, Any]]:
    """Find the first top-level JSON object in `raw` and parse it."""
    if not raw:
        return None
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("Could not parse agent JSON response: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Work nodes
# ---------------------------------------------------------------------------


def _parse_thesis(state: GraphState) -> Dict[str, Any]:
    """Read the thesis material and emit a structured interpretation.

    Calls ``AgentLoop`` with a JSON-extraction prompt when the LLM
    environment is configured. On failure (missing API key, no model, etc.)
    returns a clearly-marked stub so the checkpoint plumbing can still be
    exercised in test environments.

    The PM reviews and corrects the interpretation at the
    ``thesis_interpretation`` checkpoint before any rules are written.
    """
    seed_payload = state.pending_payload or {}
    thesis_source = seed_payload.get("thesis_text", "")
    if state.last_artifact_paths.get("thesis_doc"):
        thesis_source = f"[Document: {state.last_artifact_paths['thesis_doc']}]\n{thesis_source}"

    if thesis_source.strip():
        prompt = _THESIS_PARSE_PROMPT.format(thesis=thesis_source[:8000])
        raw = _run_agent(prompt, state.run_dir, state.session_id)
    else:
        raw = None

    parsed = _extract_json_object(raw or "")
    if parsed:
        return {"pending_payload": {
            "thesis_text": parsed.get("thesis_text", thesis_source[:500]),
            "identified_drivers": parsed.get("identified_drivers", []),
            "time_horizon": parsed.get("time_horizon", ""),
            "asset_universe": parsed.get("asset_universe", []),
            "regime_assumptions": parsed.get("regime_assumptions", []),
        }}

    return {
        "pending_payload": {
            "thesis_text": thesis_source[:500] or "<<paste thesis text here>>",
            "identified_drivers": ["<<edit me>>"],
            "time_horizon": "<<edit me>>",
            "asset_universe": ["<<edit me>>"],
            "regime_assumptions": ["<<edit me>>"],
        }
    }


def _codify_rules(state: GraphState) -> Dict[str, Any]:
    """Translate the PM-approved interpretation into a SignalEngine + prose rules.

    Reads the PM-edited interpretation from ``checkpoint_overrides``, calls
    AgentLoop with a codification prompt, and emits ``rules_dsl`` (the
    SignalEngine source), ``entry_logic`` / ``exit_logic`` (plain-english),
    and ``invalidation_triggers``. PM reviews and edits at the
    ``rule_codification`` checkpoint before the backtest runs.
    """
    overrides = state.checkpoint_overrides.get("thesis_interpretation", {})
    # Use overrides where present; fall back to the parse_thesis payload that
    # this node received as the prior pending_payload.
    interp = {**(state.pending_payload or {}), **overrides}

    prompt = _CODIFY_RULES_PROMPT.format(interpretation=json.dumps(interp, indent=2))
    raw = _run_agent(prompt, state.run_dir, state.session_id)
    parsed = _extract_json_object(raw or "")

    if parsed and parsed.get("rules_dsl"):
        return {"pending_payload": {
            "rules_dsl": str(parsed["rules_dsl"]),
            "entry_logic": str(parsed.get("entry_logic", "")),
            "exit_logic": str(parsed.get("exit_logic", "")),
            "invalidation_triggers": list(parsed.get("invalidation_triggers", [])),
            "_carry_thesis_edits": overrides,
            "_asset_universe": interp.get("asset_universe", []),
        }}

    return {
        "pending_payload": {
            "rules_dsl": (
                "# <<stub: replace with a real SignalEngine class>>\n"
                "from typing import Dict\nimport pandas as pd\n\n"
                "class SignalEngine:\n"
                "    def generate(self, data_map):\n"
                "        return {sym: pd.Series(0, index=df.index) for sym, df in data_map.items()}\n"
            ),
            "entry_logic": "<<edit me>>",
            "exit_logic": "<<edit me>>",
            "invalidation_triggers": [],
            "_carry_thesis_edits": overrides,
            "_asset_universe": interp.get("asset_universe", []),
        }
    }


def _materialize_backtest_inputs(
    run_dir: Path,
    *,
    rules_dsl: str,
    asset_universe: list[str],
    start_date: str,
    end_date: str,
    initial_cash: float,
    commission: float,
) -> None:
    """Write config.json and code/signal_engine.py under run_dir."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "code").mkdir(parents=True, exist_ok=True)
    (run_dir / "code" / "signal_engine.py").write_text(rules_dsl, encoding="utf-8")

    config = {
        "source": "yfinance",
        "codes": [str(c) for c in asset_universe] or ["SPY.US"],
        "start_date": start_date,
        "end_date": end_date,
        "initial_cash": initial_cash,
        "commission": commission,
        "via": "thesis",
    }
    (run_dir / "config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8",
    )


def _read_metrics(run_dir: Path) -> Dict[str, float]:
    """Pull headline stats from artifacts/metrics.csv if it exists."""
    path = run_dir / "artifacts" / "metrics.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}

    # metrics.csv schema is two columns (metric, value) in our engines.
    out: Dict[str, float] = {}
    if {"metric", "value"}.issubset(df.columns):
        for _, row in df.iterrows():
            try:
                out[str(row["metric"])] = float(row["value"])
            except (TypeError, ValueError):
                continue
        return out

    # Fallback: single-row of named columns.
    if len(df) == 1:
        for col in df.columns:
            try:
                out[str(col)] = float(df.iloc[0][col])
            except (TypeError, ValueError):
                continue
    return out


def _run_backtest(state: GraphState) -> Dict[str, Any]:
    """Materialize a SignalEngine + config and invoke the backtest runner.

    Uses the PM-edited rules from ``checkpoint_overrides['rule_codification']``
    when present. Stamps ``via="thesis"`` in config.json so post-engine gates
    are recorded but the result is not treated as loop-gated.
    """
    overrides = state.checkpoint_overrides.get("rule_codification", {})
    prior = state.pending_payload or {}
    rules_dsl = overrides.get("rules_dsl") or prior.get("rules_dsl", "")
    asset_universe = prior.get("_asset_universe", []) or overrides.get("_asset_universe", []) or []

    # Date window: try thesis_interpretation overrides, then sensible defaults.
    thesis_overrides = state.checkpoint_overrides.get("thesis_interpretation", {})
    start_date = thesis_overrides.get("start_date", "2018-01-01")
    end_date = thesis_overrides.get("end_date", "2024-12-31")

    run_dir = Path(state.run_dir)
    backtest_dir = run_dir / "backtest"
    try:
        _materialize_backtest_inputs(
            backtest_dir,
            rules_dsl=rules_dsl,
            asset_universe=asset_universe,
            start_date=start_date,
            end_date=end_date,
            initial_cash=1_000_000.0,
            commission=0.001,
        )

        from backtest import runner as backtest_runner
        backtest_runner.main(backtest_dir)
    except Exception as exc:
        logger.warning("thesis-to-rules backtest dispatch failed: %s", exc)
        return {
            "pending_payload": {
                "sharpe": 0.0,
                "max_dd": 0.0,
                "win_rate": 0.0,
                "avg_hold_days": 0.0,
                "regime_fit": {},
                "equity_curve_path": str(backtest_dir / "artifacts" / "equity.csv"),
                "report_path": str(backtest_dir / "artifacts" / "metrics.csv"),
                "error": str(exc),
            },
            "last_artifact_paths": {"backtest_dir": str(backtest_dir)},
        }

    metrics = _read_metrics(backtest_dir)
    return {
        "pending_payload": {
            "sharpe": float(metrics.get("sharpe", 0.0)),
            "max_dd": float(metrics.get("max_dd", metrics.get("max_drawdown", 0.0))),
            "win_rate": float(metrics.get("win_rate", 0.0)),
            "avg_hold_days": float(metrics.get("avg_hold_days", 0.0)),
            "regime_fit": {},
            "equity_curve_path": str(backtest_dir / "artifacts" / "equity.csv"),
            "report_path": str(backtest_dir / "artifacts" / "metrics.csv"),
        },
        "last_artifact_paths": {
            "backtest_dir": str(backtest_dir),
            "metrics_csv": str(backtest_dir / "artifacts" / "metrics.csv"),
            "equity_csv": str(backtest_dir / "artifacts" / "equity.csv"),
            "gates_json": str(backtest_dir / "gates.json"),
        },
    }


def _propose_sizing(state: GraphState) -> Dict[str, Any]:
    """Propose alloc + vol target; build the first-order preview.

    Pulls realized vol from the backtest's equity.csv (annualized stdev of
    daily returns) and applies a simple vol-target rule:
    ``proposed_alloc_pct = min(max_pos_pct, vol_target / realized_vol)``.
    Without an existing book the correlation_to_book is 0.0; in production
    this hooks into the shadow-account / portfolio service.
    """
    backtest_dir = Path(state.run_dir) / "backtest"
    equity_csv = backtest_dir / "artifacts" / "equity.csv"
    vol_target = 0.10
    max_pos_pct = 0.05
    realized_vol = 0.0

    if equity_csv.exists():
        try:
            df = pd.read_csv(equity_csv, index_col=0, parse_dates=True)
            if "ret" in df.columns:
                realized_vol = float(df["ret"].astype(float).std() * (252 ** 0.5))
        except Exception as exc:
            logger.warning("Could not read equity.csv for sizing: %s", exc)

    if realized_vol > 0:
        proposed = min(max_pos_pct, vol_target / realized_vol)
    else:
        proposed = max_pos_pct  # fall back to the cap when vol can't be measured

    # Build the first-order preview from the first asset in the universe.
    overrides = state.checkpoint_overrides.get("thesis_interpretation", {})
    prior = state.pending_payload or {}
    asset_universe = (
        overrides.get("asset_universe")
        or prior.get("_asset_universe")
        or []
    )
    first_ticker = asset_universe[0] if asset_universe else None
    first_order_preview = (
        {
            "ticker": first_ticker,
            "side": "buy",
            "size_pct": round(proposed, 4),
            "order_type": "limit",
            "price_band_bps": 25,
        }
        if first_ticker
        else {}
    )

    # Pull backtest headline stats from the prior node's pending_payload so
    # the PM sees sharpe/drawdown alongside the sizing proposal — one decision
    # with full context, no separate backtest checkpoint.
    prior_backtest = state.pending_payload or {}
    return {
        "pending_payload": {
            # Backtest stats (read-only context for the PM at position_sizing).
            "sharpe": prior_backtest.get("sharpe", 0.0),
            "max_dd": prior_backtest.get("max_dd", 0.0),
            "win_rate": prior_backtest.get("win_rate", 0.0),
            "avg_hold_days": prior_backtest.get("avg_hold_days", 0.0),
            # Sizing proposal — PM may edit these via allowed_edits.
            "proposed_alloc_pct": round(proposed, 4),
            "vol_target": vol_target,
            "max_pos_pct": max_pos_pct,
            "realized_vol": round(realized_vol, 4),
            "correlation_to_book": 0.0,
        }
    }


def _deploy(state: GraphState) -> Dict[str, Any]:
    """Prepare the run directory for deploy_strategy_tool and stage it for pm_go_live.

    Writes signal_engine.py and a ``gates.json`` stamped
    ``source: thesis_pm_approval`` (the PM approval chain is this strategy's
    gate — it was never a research-loop hypothesis). The deploy_strategy_tool
    respects this stamp and skips the survivor-memory check.

    On pm_go_live approval, the resume callback calls deploy_strategy_tool
    directly to register in deployments.db and fork the paper runner.
    This node only stages; it does NOT yet fork any process.
    """
    run_dir = Path(state.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Collect the PM-approved rules and asset universe.
    rule_overrides = state.checkpoint_overrides.get("rule_codification", {})
    thesis_overrides = state.checkpoint_overrides.get("thesis_interpretation", {})
    prior = state.pending_payload or {}

    rules_dsl = rule_overrides.get("rules_dsl") or ""
    asset_universe = (
        thesis_overrides.get("asset_universe")
        or prior.get("_asset_universe")
        or []
    )

    # Write signal_engine.py at root of run_dir (deploy_strategy_tool expects it).
    engine_path = run_dir / "signal_engine.py"
    backtest_engine = run_dir / "backtest" / "code" / "signal_engine.py"
    if rules_dsl:
        engine_path.write_text(rules_dsl, encoding="utf-8")
    elif backtest_engine.exists():
        engine_path.write_text(backtest_engine.read_text(encoding="utf-8"), encoding="utf-8")

    # Collect approval IDs as the audit trail that substitutes for loop-gate.
    approval_ids = [
        f"{state.attempt_id}__thesis_interpretation",
        f"{state.attempt_id}__rule_codification",
        f"{state.attempt_id}__position_sizing",
    ]

    # Write gates.json stamped as thesis_pm_approval.
    # The survivor check in deploy_strategy_tool skips when this source is set.
    gates = {
        "passes": True,
        "source": "thesis_pm_approval",
        "approval_ids": approval_ids,
        "via": "thesis",
        "note": (
            "Gate satisfied by PM approval chain: thesis_interpretation + "
            "rule_codification + position_sizing checkpoints approved."
        ),
    }
    gates_path = run_dir / "gates.json"
    gates_path.write_text(json.dumps(gates, indent=2), encoding="utf-8")

    # Strategy name from session metadata.
    strategy_name = f"thesis-{state.attempt_id[:8]}"

    # Pull backtest stats for the pm_go_live summary.
    backtest_dir = run_dir / "backtest"
    bt_metrics = _read_metrics(backtest_dir)

    # Build a first-order preview from sizing overrides.
    sizing_overrides = state.checkpoint_overrides.get("position_sizing", {})
    prior = state.pending_payload or {}
    alloc = sizing_overrides.get("proposed_alloc_pct") or prior.get("proposed_alloc_pct", 0.0)
    first_order_preview = (
        {
            "ticker": (asset_universe or ["?"])[0],
            "side": "buy",
            "size_pct": round(float(alloc), 4),
            "order_type": "limit",
            "price_band_bps": 25,
        }
        if asset_universe
        else {}
    )

    return {
        "pending_payload": {
            # These fields match pm_go_live.payload_schema in SKILL.md.
            "strategy_name": strategy_name,
            "broker": "alpaca",
            "symbols": asset_universe,
            "backtest_sharpe": bt_metrics.get("sharpe", 0.0),
            "backtest_max_dd": bt_metrics.get("max_dd", bt_metrics.get("max_drawdown", 0.0)),
            "first_order_preview": first_order_preview,
            # Internal fields passed to on_pm_go_live_approved.
            "_run_dir": str(run_dir),
            "_gates_path": str(gates_path),
        },
        "last_artifact_paths": {
            "signal_engine": str(engine_path),
            "gates_json": str(gates_path),
        },
    }


def on_pm_go_live_approved(approval_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Called by the resume callback after pm_go_live is approved.

    Thesis-to-rules is a discretionary workflow. Edge is established by the
    thesis and confirmed by historical analogs / backtest. Paper trading adds
    no information. PM approval is the gate; this deploys live immediately.

    Calls deploy_strategy_tool (creates the audit record in deployments.db),
    then immediately promotes to LIVE by re-forking the runner with
    ALPACA_PAPER=false. The PAPER state exists in the registry for microseconds
    only — it's there for audit continuity, not for actual paper trading.

    If the live fork fails, the deployment stays in PAPER state and the error
    is surfaced so the PM can retry via /live/{deployment_id}/promote/decide.
    """
    run_dir = approval_payload.get("_run_dir", "")
    broker = approval_payload.get("broker", "alpaca")
    symbols = approval_payload.get("symbols", [])
    strategy_name = approval_payload.get("strategy_name", "thesis-strategy")

    if not run_dir or not symbols:
        return {"deploy_error": "run_dir or symbols missing from payload"}

    # Register in the deployment registry (audit record + paper runner as placeholder).
    try:
        from src.tools.deploy_strategy_tool import DeployStrategyTool
        result = json.loads(
            DeployStrategyTool().execute(
                run_dir=run_dir, broker=broker, symbols=symbols,
                strategy_name=strategy_name, cadence="daily",
            )
        )
    except Exception as exc:
        logger.exception("deploy_strategy_tool failed after pm_go_live approval")
        return {"deploy_error": str(exc)}

    if result.get("status") != "ok":
        return {"deploy_error": result.get("error"), "deploy_result": result}

    deployment_id = result.get("deployment_id", "")

    # Promote immediately to live — thesis trades don't paper trade.
    try:
        from live.deployment_registry import get_registry
        import os as _os, sys as _sys, subprocess as _sp
        from pathlib import Path as _Path
        agent_root = _Path(__file__).resolve().parents[3]  # agent/
        env = {**_os.environ, "PYTHONPATH": str(agent_root), "ALPACA_PAPER": "false"}
        proc = _sp.Popen(
            [_sys.executable, "-m", "live.live_runner", deployment_id],
            cwd=str(agent_root), env=env,
            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
        )
        with get_registry() as reg:
            reg.update_state(deployment_id, "LIVE")
            reg.update_pid(deployment_id, proc.pid)
        return {
            "deployment_id": deployment_id,
            "deployment_state": "LIVE",
            "halt_endpoint": f"/live/{deployment_id}/halt",
            "deploy_status": "ok",
            "pid": proc.pid,
        }
    except Exception as exc:
        logger.exception("live fork failed — deployment is in PAPER, retry via promote/decide")
        return {
            "deployment_id": deployment_id,
            "deployment_state": "PAPER",
            "promote_endpoint": f"/live/{deployment_id}/promote/decide",
            "deploy_error": f"live fork failed: {exc} — retry via promote/decide",
        }


WORK_NODES: Dict[str, Callable[[GraphState], Dict[str, Any]]] = {
    "parse_thesis": _parse_thesis,
    "codify_rules": _codify_rules,
    "run_backtest": _run_backtest,
    "propose_sizing": _propose_sizing,
    "deploy": _deploy,
}

NODE_ORDER = ["parse_thesis", "codify_rules", "run_backtest", "propose_sizing", "deploy"]


def build_graph(approval_service: ApprovalService, sqlite_connection: Union[str, Path]):
    """Compile the thesis-to-rules checkpoint graph.

    Args:
        approval_service: Service wired against the shared sessions.db.
        sqlite_connection: Path/string to the same SQLite DB file. The graph
            builder opens a fresh autocommit connection for LangGraph's
            SqliteSaver — sharing transaction state with the approvals
            connection breaks SqliteSaver's manual BEGIN/COMMIT.

    Returns:
        A compiled LangGraph ``StateGraph`` ready for ``invoke`` / resume.
    """
    meta, _body = parse_frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    autonomy = parse_autonomy_spec(meta)
    skill_name = meta["name"]

    builder = CheckpointGraphBuilder(
        skill_name=skill_name,
        autonomy=autonomy,
        work_nodes=WORK_NODES,
        node_order=NODE_ORDER,
        approval_service=approval_service,
        sqlite_connection=sqlite_connection,
    )
    return builder.build()
