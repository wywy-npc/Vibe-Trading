"""List all deployed strategies from the deployment registry."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.agent.tools import BaseTool

try:
    from live.deployment_registry import get_registry

    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


class ListLiveTool(BaseTool):
    """List live and paper strategy deployments with PnL and status."""

    name = "list_live"
    description = (
        "List all deployed strategies (paper, live, halted) from the deployment "
        "registry. Shows state, broker, PnL, last heartbeat, and symbols."
    )
    parameters = {
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "enum": ["PAPER", "LIVE", "HALTED", "PENDING_APPROVAL", "all"],
                "description": "Filter by state. Default 'all'.",
            },
        },
        "required": [],
    }
    repeatable = True
    is_readonly = True

    @classmethod
    def check_available(cls) -> bool:
        return _AVAILABLE

    def execute(self, **kwargs) -> str:
        state_filter = kwargs.get("state", "all")

        try:
            with get_registry() as reg:
                if state_filter == "all":
                    records = reg.list_all()
                else:
                    records = reg.list_all(state=state_filter)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)})

        now = datetime.now(timezone.utc).isoformat()
        results = []
        for r in records:
            heartbeat_age = None
            if r.last_heartbeat:
                try:
                    hb = datetime.fromisoformat(r.last_heartbeat)
                    now_dt = datetime.fromisoformat(now)
                    heartbeat_age = int((now_dt - hb).total_seconds())
                except Exception:
                    pass
            results.append({
                "deployment_id": r.deployment_id,
                "strategy_name": r.strategy_name,
                "state": r.state,
                "broker": r.broker,
                "account_type": r.account_type,
                "symbols": r.symbols,
                "cadence": r.cadence,
                "pnl_realized": r.pnl_realized,
                "n_trades": r.n_trades,
                "pid": r.pid,
                "remote_host": r.remote_host,
                "heartbeat_age_seconds": heartbeat_age,
                "created_at": r.created_at,
            })

        return json.dumps({
            "status": "ok",
            "count": len(results),
            "deployments": results,
        }, ensure_ascii=False)
