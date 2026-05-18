"""Backtest execution tool: validates config.json + signal_engine.py and runs the built-in engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.core.runner import Runner
from src.tools.path_utils import safe_run_dir


def _persist_critic_verdict(config_path: Path, config: dict, critic_verdict: Any) -> None:
    """Write the verdict into config.json so runner.py threads it into evaluate_gates.

    The verdict is a small dict (passes/reasoning/kill_reasons) the agent
    received from the `critique` tool. We persist it before the engine runs
    so the post-engine gate hook can pick it up — critic verdict feeds the
    first gate inside ai_quant_lab.orchestrator.gates.evaluate_gates.
    """
    if not isinstance(critic_verdict, dict):
        return
    sanitized = {
        "passes": bool(critic_verdict.get("passes", False)),
        "reasoning": str(critic_verdict.get("reasoning", "")),
        "kill_reasons": [str(r) for r in critic_verdict.get("kill_reasons", []) or []],
    }
    config["critic_verdict"] = sanitized
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def run_backtest(run_dir: str, critic_verdict: Any = None) -> str:
    """Run backtest: validate config.json + signal_engine.py, invoke built-in engine.

    Args:
        run_dir: Path to the run directory.
        critic_verdict: Optional dict from the `critique` tool. Persisted into
            config.json so the post-engine gate hook threads it through
            evaluate_gates. None = no critic; the statistical gates still fire.

    Returns:
        JSON-formatted execution result.
    """
    try:
        run_path = safe_run_dir(run_dir)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

    config_path = run_path / "config.json"
    if not config_path.exists():
        return json.dumps({"status": "error", "error": "config.json not found"}, ensure_ascii=False)

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return json.dumps({"status": "error", "error": f"config.json parse error: {e}"}, ensure_ascii=False)

    if critic_verdict is not None:
        _persist_critic_verdict(config_path, config, critic_verdict)

    # Stamp origin so post-engine hook can propagate it to gates.json and
    # validate_run can refuse non-loop runs by default. Do not overwrite if
    # a caller (e.g. research_loop) has already set this.
    if "via" not in config:
        config["via"] = "manual"
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    if "source" not in config:
        return json.dumps({"status": "error", "error": "config.json missing 'source' field (tushare/okx/yfinance)"}, ensure_ascii=False)

    valid_sources = {"tushare", "okx", "yfinance", "akshare", "ccxt", "auto"}
    if config["source"] not in valid_sources:
        return json.dumps({"status": "error", "error": f"source must be one of {valid_sources}, got: {config['source']}"}, ensure_ascii=False)

    signal_path = run_path / "code" / "signal_engine.py"
    if not signal_path.exists():
        return json.dumps({"status": "error", "error": "code/signal_engine.py not found"}, ensure_ascii=False)

    agent_root = Path(__file__).resolve().parents[2]
    entry_script = agent_root / "backtest" / "runner.py"

    runner = Runner(timeout=300)
    result = runner.execute(
        entry_script,
        run_path,
        cwd=agent_root,
        cli_args=[str(run_path)],
    )

    artifacts_found = {name: str(path) for name, path in result.artifacts.items()}
    return json.dumps({
        "status": "ok" if result.success else "error",
        "exit_code": result.exit_code,
        "stdout": result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout,
        "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
        "artifacts": artifacts_found,
        "run_dir": run_dir,
    }, ensure_ascii=False)


class BacktestTool(BaseTool):
    """Backtest execution tool."""

    name = "backtest"
    description = (
        "Run backtest: validate config.json + signal_engine.py, invoke built-in engine. "
        "Optionally accepts a critic_verdict (from the `critique` tool) which is "
        "threaded through evaluate_gates after the engine runs. Without one, the "
        "statistical gates (Deflated Sharpe / correlation / PCA) still fire."
    )
    parameters = {
        "type": "object",
        "properties": {
            "run_dir": {"type": "string", "description": "Path to the run directory"},
            "critic_verdict": {
                "type": "object",
                "description": (
                    "Optional verdict object from a prior `critique` call: "
                    "{passes: bool, reasoning: str, kill_reasons: string[]}. "
                    "Persisted into config.json for the post-engine gate hook."
                ),
                "properties": {
                    "passes": {"type": "boolean"},
                    "reasoning": {"type": "string"},
                    "kill_reasons": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "required": ["run_dir"],
    }
    repeatable = True
    is_readonly = False

    def execute(self, **kwargs) -> str:
        """Execute backtest."""
        return run_backtest(kwargs["run_dir"], kwargs.get("critic_verdict"))
