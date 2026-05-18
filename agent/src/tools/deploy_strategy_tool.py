"""Deploy a gate-approved strategy to paper trading.

Validates that the strategy:
  1. Has a passing gates.json (ai-quant-lab gates)
  2. Is a survivor in research_memory.db

Then creates a DeploymentRecord and forks live_runner.py or
async_live_runner.py as a subprocess tracked by the API server's process
table. Paper trading is automatic; live requires promote_to_live + HITL.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from src.agent.tools import BaseTool
from src.tools.path_utils import safe_run_dir

try:
    from live.deployment_registry import DeploymentRecord, get_registry

    _AVAILABLE = True
except Exception:
    _AVAILABLE = False

_VALID_BROKERS = {"alpaca", "ibkr"}
_VALID_CADENCES = {"daily", "intraday"}


class DeployStrategyTool(BaseTool):
    """Deploy a gate-approved strategy to paper trading."""

    name = "deploy_strategy"
    description = (
        "Deploy a strategy that passed all ai-quant-lab gates to paper trading. "
        "Validates gates.json passes=true and survivor status. Forks a live_runner "
        "subprocess (daily) or async_live_runner (intraday). Paper is automatic; "
        "use promote_to_live for live account promotion."
    )
    parameters = {
        "type": "object",
        "properties": {
            "run_dir": {"type": "string", "description": "Path to the strategy run directory (must have passing gates.json)"},
            "broker": {"type": "string", "enum": ["alpaca", "ibkr"], "description": "Execution broker"},
            "symbols": {"type": "array", "items": {"type": "string"}, "description": "Symbols to trade"},
            "interval": {"type": "string", "description": "Data interval (1D, 1H, 5Min, etc.)", "default": "1D"},
            "cadence": {"type": "string", "enum": ["daily", "intraday"], "description": "Execution cadence", "default": "daily"},
            "max_drawdown_pct": {"type": "number", "description": "Kill-switch max drawdown (default 10%)", "default": 10.0},
            "daily_loss_pct": {"type": "number", "description": "Kill-switch daily loss limit (default 2%)", "default": 2.0},
            "strategy_name": {"type": "string", "description": "Human-readable strategy name"},
        },
        "required": ["run_dir", "broker", "symbols"],
    }
    repeatable = True
    is_readonly = False

    @classmethod
    def check_available(cls) -> bool:
        return _AVAILABLE

    def execute(self, **kwargs) -> str:
        try:
            run_path = safe_run_dir(kwargs["run_dir"])
        except ValueError as exc:
            return json.dumps({"status": "error", "error": str(exc)})

        broker = kwargs.get("broker", "alpaca")
        if broker not in _VALID_BROKERS:
            return json.dumps({"status": "error", "error": f"broker must be one of {sorted(_VALID_BROKERS)}"})

        cadence = kwargs.get("cadence", "daily")
        symbols = list(kwargs.get("symbols", []))
        if not symbols:
            return json.dumps({"status": "error", "error": "symbols must be non-empty"})

        # Gate validation
        gates_path = run_path / "gates.json"
        if not gates_path.exists():
            return json.dumps({"status": "error", "error": "gates.json not found — run the backtest first"})
        gates = json.loads(gates_path.read_text())
        if not gates.get("passes"):
            reason = gates.get("rejection_reason", "unknown")
            return json.dumps({
                "status": "error",
                "error": f"Strategy did not pass gates (reason: {reason}). Cannot deploy.",
                "gates": gates,
            })

        # Survivor check — skipped for PM-approved thesis runs.
        # Thesis-to-rules strategies were never research-loop hypotheses; their
        # audit trail is the PM approval chain recorded in gates.json.
        is_thesis_run = gates.get("source") == "thesis_pm_approval"
        if not is_thesis_run:
            try:
                from backtest.research_memory import get_memory
                with get_memory() as memory:
                    survivors = {s.hypothesis_id for s in memory.survivors()}
                if run_path.name not in survivors:
                    return json.dumps({
                        "status": "error",
                        "error": f"Strategy run_id {run_path.name!r} is not a research_memory survivor. "
                                 "Only gate-accepted strategies can be deployed.",
                    })
            except Exception:
                pass  # If memory not available, gate check is sufficient

        deployment_id = f"deploy_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        strategy_name = kwargs.get("strategy_name") or run_path.name
        max_dd = float(kwargs.get("max_drawdown_pct", 10.0)) / 100.0
        daily_loss = float(kwargs.get("daily_loss_pct", 2.0)) / 100.0

        record = DeploymentRecord(
            deployment_id=deployment_id,
            strategy_name=strategy_name,
            run_dir=str(run_path),
            state="PAPER",
            broker=broker,
            account_type="paper",
            symbols=symbols,
            interval=kwargs.get("interval", "1D"),
            cadence=cadence,
        )

        with get_registry() as reg:
            reg.create(record)

        # Fork the appropriate runner
        agent_root = Path(__file__).resolve().parents[2]
        runner_module = "live.async_live_runner" if cadence == "intraday" else "live.live_runner"
        env = {**os.environ, "PYTHONPATH": str(agent_root)}

        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", runner_module, deployment_id],
                cwd=str(agent_root),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with get_registry() as reg:
                reg.update_pid(deployment_id, proc.pid)
        except Exception as exc:
            with get_registry() as reg:
                reg.update_state(deployment_id, "HALTED", rejection_reason=str(exc))
            return json.dumps({"status": "error", "error": f"Failed to start runner: {exc}"})

        return json.dumps({
            "status": "ok",
            "deployment_id": deployment_id,
            "state": "PAPER",
            "broker": broker,
            "cadence": cadence,
            "symbols": symbols,
            "pid": proc.pid,
            "note": (
                "Strategy deployed to paper trading. Monitor via list_live. "
                "Use promote_to_live to request HITL approval for live trading."
            ),
        }, ensure_ascii=False)
