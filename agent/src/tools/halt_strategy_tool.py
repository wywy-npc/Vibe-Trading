"""Halt a running strategy deployment cleanly (SIGTERM + registry update)."""

from __future__ import annotations

import json
import os
import signal

from src.agent.tools import BaseTool

try:
    from live.deployment_registry import get_registry

    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


class HaltStrategyTool(BaseTool):
    """Immediately halt a running paper or live deployment."""

    name = "halt_strategy"
    description = (
        "Halt a running strategy. Sends SIGTERM to the live_runner process, "
        "updates the deployment_registry to HALTED, and returns final PnL."
    )
    parameters = {
        "type": "object",
        "properties": {
            "deployment_id": {"type": "string", "description": "The deployment_id to halt"},
            "reason": {"type": "string", "description": "Optional reason for halting (logged in registry)"},
        },
        "required": ["deployment_id"],
    }
    repeatable = True
    is_readonly = False

    @classmethod
    def check_available(cls) -> bool:
        return _AVAILABLE

    def execute(self, **kwargs) -> str:
        deployment_id = kwargs["deployment_id"]
        reason = kwargs.get("reason", "manual_halt")

        try:
            with get_registry() as reg:
                record = reg.get(deployment_id)
                if record is None:
                    return json.dumps({
                        "status": "error",
                        "error": f"Deployment {deployment_id!r} not found",
                    })
                if record.state == "HALTED":
                    return json.dumps({
                        "status": "ok",
                        "deployment_id": deployment_id,
                        "state": "HALTED",
                        "note": "Already halted",
                        "pnl_realized": record.pnl_realized,
                    })

                # SIGTERM to the runner process
                if record.pid:
                    try:
                        os.kill(record.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass  # process already gone
                    except PermissionError as exc:
                        return json.dumps({
                            "status": "error",
                            "error": f"Cannot halt process {record.pid}: {exc}",
                        })

                reg.update_state(deployment_id, "HALTED", rejection_reason=reason)
                final_pnl = record.pnl_realized

        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)})

        return json.dumps({
            "status": "ok",
            "deployment_id": deployment_id,
            "state": "HALTED",
            "reason": reason,
            "pnl_realized": final_pnl,
        }, ensure_ascii=False)
