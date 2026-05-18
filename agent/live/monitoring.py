"""Per-strategy and portfolio-level risk monitoring.

Wraps ai-quant-lab's KillSwitch + LiveDiagnostic for per-strategy checks.
PortfolioMonitor aggregates across all active deployments.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from live.deployment_registry import DeploymentRegistry, DeploymentRecord
    from live.live_runner import LiveRunner

logger = logging.getLogger(__name__)

try:
    from ai_quant_lab.production.kill_switch import (
        KillSwitch,
        drawdown_trigger,
        daily_loss_trigger,
        sharpe_collapse_trigger,
    )
    from ai_quant_lab.production.paper_trading import LiveDiagnostic

    _AQL_AVAILABLE = True
except ImportError:
    _AQL_AVAILABLE = False


@dataclass
class PortfolioSnapshot:
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    total_pnl_realized: float = 0.0
    combined_drawdown: float = 0.0
    per_strategy_pnl: dict[str, float] = field(default_factory=dict)
    per_strategy_state: dict[str, str] = field(default_factory=dict)
    correlation_matrix: dict[str, dict[str, float]] = field(default_factory=dict)
    n_active: int = 0
    portfolio_max_dd_breach: bool = False


class LiveMonitor:
    """Per-strategy monitor wrapping KillSwitch + LiveDiagnostic."""

    def __init__(
        self,
        deployment_id: str,
        *,
        backtest_returns: pd.Series | None = None,
        max_drawdown: float = 0.10,
        daily_loss_limit: float = 0.02,
        sharpe_collapse_threshold: float = -0.5,
        sharpe_window: int = 60,
    ) -> None:
        self.deployment_id = deployment_id
        self._kill_switch: KillSwitch | None = None
        self._diagnostic: LiveDiagnostic | None = None

        if _AQL_AVAILABLE:
            self._kill_switch = KillSwitch(triggers=[
                drawdown_trigger(max_drawdown),
                daily_loss_trigger(daily_loss_limit),
                sharpe_collapse_trigger(sharpe_collapse_threshold, sharpe_window),
            ])
            if backtest_returns is not None:
                self._diagnostic = LiveDiagnostic(
                    backtest_returns=backtest_returns,
                    window_days=sharpe_window,
                )

    def check_and_halt(
        self,
        live_returns: pd.Series,
        runner: "LiveRunner",
    ) -> bool:
        """Check triggers; halt runner if any trip.

        Returns True if halt was triggered.
        """
        if self._kill_switch is None:
            return False

        self._kill_switch.update(live_returns)
        if self._kill_switch.is_tripped:
            reason = "kill_switch"
            logger.warning("[%s] KillSwitch tripped", self.deployment_id)
            runner.halt(runner._make_broker(runner.config), reason=reason)  # type: ignore[attr-defined]
            return True
        return False

    def diagnostic_summary(self, live_returns: pd.Series) -> dict:
        if self._diagnostic is None:
            return {}
        try:
            report = self._diagnostic.report(live_returns)
            return {
                "live_sharpe": float(report.get("live_sharpe", 0)),
                "backtest_sharpe": float(report.get("backtest_sharpe", 0)),
                "regime_drift": float(report.get("regime_drift", 0)),
            }
        except Exception:
            return {}


class PortfolioMonitor:
    """Aggregate risk view across all active deployments."""

    def __init__(self, portfolio_max_drawdown: float = 0.15) -> None:
        self.portfolio_max_drawdown = portfolio_max_drawdown

    def snapshot(self, registry: "DeploymentRegistry") -> PortfolioSnapshot:
        active = registry.list_active()
        if not active:
            return PortfolioSnapshot()

        snap = PortfolioSnapshot(n_active=len(active))
        returns_by_id: dict[str, pd.Series] = {}

        for record in active:
            snap.per_strategy_pnl[record.deployment_id] = record.pnl_realized
            snap.per_strategy_state[record.deployment_id] = record.state
            snap.total_pnl_realized += record.pnl_realized

            if record.returns_json:
                try:
                    payload = json.loads(record.returns_json)
                    vals = payload.get("values") or payload.get("values", [])
                    if vals:
                        returns_by_id[record.deployment_id] = pd.Series(vals)
                except Exception:
                    pass

        # Combined equity curve for drawdown
        if returns_by_id:
            combined = pd.concat(list(returns_by_id.values()), axis=1).mean(axis=1)
            equity = (1.0 + combined.fillna(0)).cumprod()
            peak = equity.cummax()
            dd = float(((equity - peak) / peak.clip(lower=1e-9)).min())
            snap.combined_drawdown = dd
            snap.portfolio_max_dd_breach = abs(dd) > self.portfolio_max_drawdown

        # Pairwise correlation
        if len(returns_by_id) > 1:
            df = pd.concat(
                {k: v for k, v in returns_by_id.items()}, axis=1
            ).dropna(how="all")
            corr = df.corr()
            snap.correlation_matrix = {
                col: {row: float(corr.loc[row, col]) for row in corr.index}
                for col in corr.columns
            }

        return snap

    def halt_all_if_breached(
        self,
        registry: "DeploymentRegistry",
        process_table: dict[str, object],
    ) -> bool:
        """Halt all LIVE/PAPER strategies if portfolio drawdown exceeds limit."""
        snap = self.snapshot(registry)
        if not snap.portfolio_max_dd_breach:
            return False

        logger.critical(
            "Portfolio drawdown %.2f%% exceeds limit %.2f%% — halting ALL strategies",
            abs(snap.combined_drawdown) * 100,
            self.portfolio_max_drawdown * 100,
        )
        import signal as _signal
        import os as _os

        for record in registry.list_active():
            registry.update_state(
                record.deployment_id, "HALTED",
                rejection_reason=f"portfolio_drawdown={abs(snap.combined_drawdown):.3f}",
            )
            proc = process_table.get(record.deployment_id)
            if proc is not None:
                try:
                    _os.kill(getattr(proc, "pid", 0), _signal.SIGTERM)
                except Exception:
                    pass

        return True
