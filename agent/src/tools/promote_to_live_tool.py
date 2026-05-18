"""Propose a paper strategy for promotion to live trading.

Live trading ALWAYS requires explicit human approval (HITL). This tool:
  1. Validates the deployment is in PAPER state and running
  2. Updates registry to PENDING_APPROVAL
  3. Returns instructions for the human to approve via /live/{id}/promote/decide

No automation path to live. Never.
"""

from __future__ import annotations

import json

from src.agent.tools import BaseTool

try:
    from live.deployment_registry import get_registry

    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


class PromoteToLiveTool(BaseTool):
    """Request HITL approval to promote a paper deployment to live trading."""

    name = "promote_to_live"
    description = (
        "Propose a paper-trading deployment for promotion to live. Sets state to "
        "PENDING_APPROVAL and returns instructions for the human to approve or reject. "
        "Live trading ALWAYS requires explicit human approval — no automation path."
    )
    parameters = {
        "type": "object",
        "properties": {
            "deployment_id": {"type": "string", "description": "The paper deployment to promote"},
            "rationale": {
                "type": "string",
                "description": "Why this strategy should go live. Include paper trading duration, realized metrics, and any deviations from backtest.",
            },
        },
        "required": ["deployment_id", "rationale"],
    }
    repeatable = False
    is_readonly = False

    @classmethod
    def check_available(cls) -> bool:
        return _AVAILABLE

    def execute(self, **kwargs) -> str:
        deployment_id = kwargs["deployment_id"]
        rationale = kwargs.get("rationale", "")

        try:
            with get_registry() as reg:
                record = reg.get(deployment_id)
                if record is None:
                    return json.dumps({
                        "status": "error",
                        "error": f"Deployment {deployment_id!r} not found",
                    })
                if record.state != "PAPER":
                    return json.dumps({
                        "status": "error",
                        "error": f"Only PAPER deployments can be promoted. Current state: {record.state}",
                    })

                reg.update_state(deployment_id, "PENDING_APPROVAL")

                summary = {
                    "deployment_id": deployment_id,
                    "strategy_name": record.strategy_name,
                    "broker": record.broker,
                    "symbols": record.symbols,
                    "cadence": record.cadence,
                    "paper_pnl": record.pnl_realized,
                    "paper_n_trades": record.n_trades,
                    "paper_since": record.created_at,
                    "rationale": rationale,
                }

        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)})

        return json.dumps({
            "status": "ok",
            "state": "PENDING_APPROVAL",
            "deployment_id": deployment_id,
            "summary": summary,
            "human_action_required": (
                f"To APPROVE live trading: POST /live/{deployment_id}/promote/decide "
                f"with {{\"approved\": true}}. "
                f"To REJECT: POST with {{\"approved\": false}}. "
                "REMINDER: live trading involves real money — review paper metrics carefully."
            ),
        }, ensure_ascii=False)
