"""Portfolio-level risk view across all active deployments."""

from __future__ import annotations

import json
from dataclasses import asdict

from src.agent.tools import BaseTool

try:
    from live.deployment_registry import get_registry
    from live.monitoring import PortfolioMonitor

    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


class PortfolioRiskTool(BaseTool):
    """Aggregate risk view: combined PnL, drawdown, correlation across deployments."""

    name = "portfolio_risk"
    description = (
        "Return combined risk metrics across all active (PAPER + LIVE) deployments: "
        "total PnL, combined drawdown, per-strategy breakdown, and return correlation "
        "matrix. Flags if combined drawdown is approaching the portfolio kill threshold."
    )
    parameters = {
        "type": "object",
        "properties": {
            "portfolio_max_drawdown_pct": {
                "type": "number",
                "description": "Portfolio-level drawdown limit (default 15%)",
                "default": 15.0,
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
        max_dd = float(kwargs.get("portfolio_max_drawdown_pct", 15.0)) / 100.0
        monitor = PortfolioMonitor(portfolio_max_drawdown=max_dd)

        try:
            with get_registry() as reg:
                snapshot = monitor.snapshot(reg)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)})

        return json.dumps({
            "status": "ok",
            "snapshot": {
                "timestamp": snapshot.timestamp,
                "n_active": snapshot.n_active,
                "total_pnl_realized": snapshot.total_pnl_realized,
                "combined_drawdown": snapshot.combined_drawdown,
                "portfolio_max_dd_breach": snapshot.portfolio_max_dd_breach,
                "per_strategy_pnl": snapshot.per_strategy_pnl,
                "per_strategy_state": snapshot.per_strategy_state,
                "correlation_matrix": snapshot.correlation_matrix,
            },
        }, ensure_ascii=False)
