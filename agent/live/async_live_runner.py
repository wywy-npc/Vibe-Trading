"""Intraday async streaming runner.

Subscribes to a broker's bar stream and re-signals + rebalances on each bar.
Designed for crypto (24/7) and intraday equity strategies.

Usage:
    python -m live.async_live_runner <deployment_id>
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from live.broker_base import Bar, BaseBroker

logger = logging.getLogger(__name__)

_HEARTBEAT_BARS = 10   # write heartbeat every N bars


@dataclass
class AsyncRunnerConfig:
    deployment_id: str
    run_dir: str
    broker_name: str
    symbols: list[str]
    timeframe: str = "1Min"
    paper: bool = True
    max_drawdown: float = 0.10
    daily_loss_limit: float = 0.02
    window_bars: int = 300    # rolling history fed to signal_engine per bar


def _load_signal_engine(run_dir: Path):
    signal_path = run_dir / "code" / "signal_engine.py"
    if not signal_path.exists():
        raise FileNotFoundError(f"signal_engine.py not found in {run_dir}")
    spec = importlib.util.spec_from_file_location("signal_engine_live", signal_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SignalEngine()


def _make_broker(cfg: AsyncRunnerConfig) -> "BaseBroker":
    if cfg.broker_name == "alpaca":
        from live.alpaca_broker import AlpacaBroker
        return AlpacaBroker(paper=cfg.paper)
    elif cfg.broker_name == "ibkr":
        from live.ibkr_broker import IbkrBroker
        return IbkrBroker(paper=cfg.paper)
    raise ValueError(f"Unknown broker {cfg.broker_name!r}")


class AsyncLiveRunner:
    """WebSocket-driven intraday execution loop."""

    def __init__(self, config: AsyncRunnerConfig) -> None:
        self.config = config
        self._halted = False
        self._live_returns: list[float] = []
        self._bar_history: dict[str, list[dict]] = defaultdict(list)
        self._bar_count = 0
        self._last_equity: float = 0.0

    async def run(self, *, bar_stream=None) -> None:
        """Stream bars and rebalance.

        Args:
            bar_stream: Optional async iterable of Bar objects (for tests).
                        If None, uses the broker's subscribe_bars.
        """
        run_dir = Path(self.config.run_dir)
        signal_engine = _load_signal_engine(run_dir)
        broker = _make_broker(self.config)
        self._last_equity = broker.get_account_equity()

        stream = bar_stream or broker.subscribe_bars(self.config.symbols, self.config.timeframe)

        async for bar in stream:
            if self._halted:
                break
            await self._on_bar(bar, signal_engine, broker)

    async def _on_bar(self, bar: "Bar", signal_engine, broker: "BaseBroker") -> None:
        sym = bar.symbol
        self._bar_history[sym].append({
            "timestamp": bar.timestamp,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        })
        # Keep rolling window
        if len(self._bar_history[sym]) > self.config.window_bars:
            self._bar_history[sym].pop(0)

        self._bar_count += 1

        # Only signal when we have history for all symbols
        if not all(self._bar_history.get(s) for s in self.config.symbols):
            return

        data_map = {
            s: pd.DataFrame(self._bar_history[s]).set_index("timestamp")
            for s in self.config.symbols
        }

        try:
            target_weights = signal_engine.generate(data_map)
        except Exception as exc:
            logger.error("[%s] signal_engine error on bar: %s", self.config.deployment_id, exc)
            return

        from live.order_manager import compute_orders
        try:
            positions = broker.get_positions()
            equity = broker.get_account_equity()
            prices = {s: float(data_map[s]["close"].iloc[-1]) for s in self.config.symbols if s in data_map}
            orders = compute_orders(target_weights, positions, equity, prices)
            for order in orders:
                result = broker.place_order(order)
                logger.info("[%s] intraday fill %s %s @%.4f",
                            self.config.deployment_id, result.side,
                            result.symbol, result.avg_price)

            new_equity = broker.get_account_equity()
            if self._last_equity > 0:
                self._live_returns.append((new_equity - self._last_equity) / self._last_equity)
            self._last_equity = new_equity

        except Exception as exc:
            logger.error("[%s] Order/position error: %s", self.config.deployment_id, exc)

        self._check_kill_switch(broker)

        if self._bar_count % _HEARTBEAT_BARS == 0:
            self._write_heartbeat()

    def _check_kill_switch(self, broker: "BaseBroker") -> None:
        if len(self._live_returns) < 2:
            return
        returns = pd.Series(self._live_returns)
        equity_curve = (1.0 + returns).cumprod()
        peak = equity_curve.cummax()
        drawdown = float(((equity_curve - peak) / peak.clip(lower=1e-9)).min())

        if abs(drawdown) > self.config.max_drawdown:
            logger.warning("[%s] Kill-switch drawdown %.2f%%",
                           self.config.deployment_id, abs(drawdown) * 100)
            self._halt_sync(broker, reason=f"drawdown={abs(drawdown):.3f}")
            return

        if self._live_returns and self._live_returns[-1] < -self.config.daily_loss_limit:
            loss = self._live_returns[-1]
            logger.warning("[%s] Kill-switch daily loss %.2f%%",
                           self.config.deployment_id, abs(loss) * 100)
            self._halt_sync(broker, reason=f"daily_loss={loss:.3f}")

    def _halt_sync(self, broker: "BaseBroker", reason: str = "manual") -> None:
        if self._halted:
            return
        self._halted = True
        try:
            broker.cancel_all_orders()
        except Exception as exc:
            logger.warning("[%s] Cancel failed: %s", self.config.deployment_id, exc)
        try:
            from live.deployment_registry import get_registry
            with get_registry() as reg:
                reg.update_state(self.config.deployment_id, "HALTED", rejection_reason=reason)
        except Exception as exc:
            logger.warning("[%s] Registry halt failed: %s", self.config.deployment_id, exc)

    def _write_heartbeat(self) -> None:
        try:
            from live.deployment_registry import get_registry
            with get_registry() as reg:
                reg.heartbeat(
                    self.config.deployment_id,
                    pnl_realized=self._last_equity,
                    n_trades=len(self._live_returns),
                )
        except Exception as exc:
            logger.warning("[%s] Heartbeat failed: %s", self.config.deployment_id, exc)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m live.async_live_runner <deployment_id>")
        sys.exit(1)

    deployment_id = sys.argv[1]

    from live.deployment_registry import get_registry
    with get_registry() as reg:
        record = reg.get(deployment_id)

    if record is None:
        print(f"Deployment {deployment_id!r} not found")
        sys.exit(1)

    cfg = AsyncRunnerConfig(
        deployment_id=record.deployment_id,
        run_dir=record.run_dir,
        broker_name=record.broker,
        symbols=record.symbols,
        timeframe=record.interval,
        paper=(record.account_type == "paper"),
    )
    logging.basicConfig(level=logging.INFO)
    asyncio.run(AsyncLiveRunner(cfg).run())
