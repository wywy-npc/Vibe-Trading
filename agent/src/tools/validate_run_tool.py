"""Re-evaluate ai-quant-lab gates against an existing run_dir.

Lets the agent re-run gates after n_trials has grown (deflated Sharpe gets
stricter) or after additional survivors have been accepted (correlation +
PCA gates change). No new engine work — only reads the existing artifacts.

Strict mode (default): refuses to re-evaluate runs that weren't produced by
``research_loop`` — i.e. runs without ``via="loop"`` and a ``loop_run_id`` in
config.json. The hard-gate invariant is that only the deterministic loop
produces loop-gated results; post-hoc replay on ad-hoc runs is structurally
prevented. Pass ``allow_non_loop=true`` for analyst re-checks.
"""

from __future__ import annotations

import json

from src.agent.tools import BaseTool
from src.tools.path_utils import safe_run_dir

try:
    from backtest import research_memory as _research_memory
    from backtest import validation_aql as _validation_aql

    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


def _read_origin(run_path) -> tuple[str | None, str | None]:
    """Return (via, loop_run_id) from config.json; (None, None) if absent."""
    config_path = run_path / "config.json"
    if not config_path.exists():
        return None, None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, None
    return config.get("via"), config.get("loop_run_id")


class ValidateRunTool(BaseTool):
    """Run the ai-quant-lab gate stack against a finished run's artifacts."""

    name = "validate_run"
    description = (
        "Re-evaluate ai-quant-lab gates (critic+DSR+correlation+PCA) against a "
        "finished run_dir without re-running the engine. Strict by default: "
        "refuses runs not produced by research_loop. Pass allow_non_loop=true "
        "to override for analyst re-checks. Emits a fresh gates.json."
    )
    parameters = {
        "type": "object",
        "properties": {
            "run_dir": {"type": "string", "description": "Path to a run directory containing artifacts/equity.csv."},
            "annualization": {
                "type": "integer",
                "description": "Bars per year for Sharpe annualization. Defaults to settings (typically 252).",
            },
            "allow_non_loop": {
                "type": "boolean",
                "description": (
                    "Override the hard-gate invariant and re-evaluate a run that "
                    "was not produced by research_loop. Default false."
                ),
                "default": False,
            },
        },
        "required": ["run_dir"],
    }
    repeatable = True
    is_readonly = True

    @classmethod
    def check_available(cls) -> bool:
        return _AVAILABLE

    def execute(self, **kwargs) -> str:
        try:
            run_path = safe_run_dir(kwargs["run_dir"])
        except ValueError as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

        annualization = kwargs.get("annualization")
        allow_non_loop = bool(kwargs.get("allow_non_loop", False))

        via, loop_run_id = _read_origin(run_path)
        if not allow_non_loop and (via != "loop" or not loop_run_id):
            return json.dumps({
                "status": "error",
                "code": "not_loop_gated",
                "message": (
                    "validate_run refuses non-loop runs by default. This run "
                    "was not produced by research_loop (via="
                    f"{via!r}, loop_run_id={loop_run_id!r}). Re-run through "
                    "research_loop, or pass allow_non_loop=true to override."
                ),
                "via": via,
                "loop_run_id": loop_run_id,
                "run_dir": str(run_path),
            }, ensure_ascii=False)

        try:
            with _research_memory.get_memory() as memory:
                outcome = _validation_aql.gates_from_artifacts(
                    run_path,
                    memory=memory,
                    critic_verdict=None,
                    annualization=annualization,
                )
                n_trials = memory.n_trials()
                gate_extras = {
                    "n_trials_at_gate": n_trials,
                    "via": via if via else "unknown",
                    "revalidated": True,
                }
                if loop_run_id:
                    gate_extras["loop_run_id"] = loop_run_id
                if allow_non_loop and (via != "loop" or not loop_run_id):
                    gate_extras["allow_non_loop_override"] = True
                artifact_path = _validation_aql.write_gates_artifact(
                    run_path, outcome, extras=gate_extras,
                )
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"Gate evaluation failed: {exc}"}, ensure_ascii=False)

        return json.dumps({
            "status": "ok",
            "run_dir": str(run_path),
            "gates_artifact": str(artifact_path),
            "gates": _validation_aql.gate_outcome_to_dict(outcome),
            "n_trials": n_trials,
            "via": via,
            "loop_run_id": loop_run_id,
        }, ensure_ascii=False)
