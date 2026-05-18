"""Daily polling live runner.

Fetches OHLCV once per bar close, runs signal_engine.generate(), sizes
positions, submits orders, checks kill-switch, writes heartbeat.
Managed as a subprocess by the deployment system.

Usage (via API server):
    python -m live.live_runner <deployment_id>

Or imported and driven programmatically in tests.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from live.broker_base import BaseBroker

logger = logging.getLogger(__name__)


@dataclass
class LiveRunnerConfig:
    deployment_id: str
    run_dir: str
    broker_name: str       # "alpaca" | "ibkr"
    symbols: list[str]
    interval: str = "1D"
    cadence: str = "daily"
    paper: bool = True
    max_drawdown: float = 0.10
    daily_loss_limit: float = 0.02
    sharpe_window: int = 60


def _load_signal_engine(run_dir: Path):
    signal_path = run_dir / "code" / "signal_engine.py"
    if not signal_path.exists():
        raise FileNotFoundError(f"signal_engine.py not found in {run_dir}")
    spec = importlib.util.spec_from_file_location("signal_engine_live", signal_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SignalEngine()


def _make_broker(config: LiveRunnerConfig) -> "BaseBroker":
    if config.broker_name == "alpaca":
        from live.alpaca_broker import AlpacaBroker
        return AlpacaBroker(paper=config.paper)
    elif config.broker_name == "ibkr":
        from live.ibkr_broker import IbkrBroker
        return IbkrBroker(paper=config.paper)
    else:
        raise ValueError(f"Unknown broker {config.broker_name!r}")


def _fetch_data(symbols: list[str], interval: str) -> dict:
    """Fetch most recent OHLCV data via Vibe-Trading loaders."""
    from backtest.loaders.registry import _ensure_registered, LOADER_REGISTRY
    from backtest.runner import _detect_market, _MARKET_TO_SOURCE

    _ensure_registered()
    end = pd.Timestamp.now().strftime("%Y-%m-%d")
    lookback_days = 300
    start = (pd.Timestamp.now() - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    data_map: dict = {}
    for symbol in symbols:
        market = _detect_market(symbol)
        source = _MARKET_TO_SOURCE.get(market, "yfinance")
        loader_cls = LOADER_REGISTRY.get(source)
        if loader_cls is None:
            logger.warning("No loader for market %s (symbol %s)", market, symbol)
            continue
        loader = loader_cls()
        result = loader.fetch([symbol], start, end, interval=interval)
        data_map.update(result)
    return data_map


class LiveRunner:
    """Daily execution loop for a single deployed strategy."""

    def __init__(self, config: LiveRunnerConfig) -> None:
        self.config = config
        self._halted = False
        self._live_returns: list[float] = []

    def run(self, *, max_bars: int | None = None) -> None:
        """Main loop. Blocks until halted, kill-switch trips, or max_bars reached.

        Args:
            max_bars: Used in tests to limit iterations without real scheduling.
        """
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger

        run_dir = Path(self.config.run_dir)
        signal_engine = _load_signal_engine(run_dir)
        broker = _make_broker(self.config)

        # For test/controlled mode
        if max_bars is not None:
            for _ in range(max_bars):
                if self._halted:
                    break
                self._tick(signal_engine, broker)
            return

        # Production: APScheduler at market close (16:00 ET for equities, 00:00 UTC for crypto)
        scheduler = BlockingScheduler()
        is_crypto = any("/" in s or "-" in s for s in self.config.symbols)
        if is_crypto:
            trigger = CronTrigger(hour=0, minute=0, timezone="UTC")
        else:
            trigger = CronTrigger(hour=16, minute=5, timezone="America/New_York", day_of_week="mon-fri")

        scheduler.add_job(
            lambda: self._tick(signal_engine, broker),
            trigger=trigger,
            id="live_tick",
        )
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self.halt(broker)

    def _tick(self, signal_engine, broker: "BaseBroker") -> None:
        try:
            data_map = _fetch_data(self.config.symbols, self.config.interval)
            if not data_map:
                logger.warning("[%s] No data fetched, skipping bar", self.config.deployment_id)
                return

            target_weights = signal_engine.generate(data_map)

            from live.order_manager import compute_orders
            positions = broker.get_positions()
            equity = broker.get_account_equity()
            prices = {sym: float(df["close"].iloc[-1]) for sym, df in data_map.items() if "close" in df.columns}

            orders = compute_orders(target_weights, positions, equity, prices)
            for order in orders:
                try:
                    result = broker.place_order(order)
                    logger.info("[%s] Filled %s %s qty=%.4f @%.4f",
                                self.config.deployment_id, result.side,
                                result.symbol, result.filled_qty, result.avg_price)
                except Exception as exc:
                    logger.error("[%s] Order failed for %s: %s",
                                 self.config.deployment_id, order.symbol, exc)

            # Track realized returns
            new_equity = broker.get_account_equity()
            if equity > 0:
                self._live_returns.append((new_equity - equity) / equity)

            self._check_kill_switch(broker)
            self._write_heartbeat(equity=new_equity)

        except Exception as exc:
            logger.error("[%s] Tick error: %s", self.config.deployment_id, exc)

    def _check_kill_switch(self, broker: "BaseBroker") -> None:
        if not self._live_returns:
            return
        import numpy as np
        returns = pd.Series(self._live_returns)
        equity_curve = (1.0 + returns).cumprod()
        peak = equity_curve.cummax()
        drawdown = float(((equity_curve - peak) / peak.clip(lower=1e-9)).min())

        if abs(drawdown) > self.config.max_drawdown:
            logger.warning("[%s] Kill-switch: drawdown %.2f%% > limit %.2f%%",
                           self.config.deployment_id, abs(drawdown) * 100,
                           self.config.max_drawdown * 100)
            self.halt(broker, reason=f"drawdown={abs(drawdown):.3f}")
            return

        if len(returns) >= 1:
            daily_loss = float(returns.iloc[-1])
            if daily_loss < -self.config.daily_loss_limit:
                logger.warning("[%s] Kill-switch: daily loss %.2f%%",
                               self.config.deployment_id, abs(daily_loss) * 100)
                self.halt(broker, reason=f"daily_loss={daily_loss:.3f}")

    def halt(self, broker: "BaseBroker", reason: str = "manual") -> None:
        if self._halted:
            return
        self._halted = True
        logger.info("[%s] Halting: %s", self.config.deployment_id, reason)
        try:
            broker.cancel_all_orders()
        except Exception as exc:
            logger.warning("[%s] Cancel orders failed: %s", self.config.deployment_id, exc)
        self._update_registry_state("HALTED", rejection_reason=reason)

    def _write_heartbeat(self, equity: float = 0.0) -> None:
        try:
            from live.deployment_registry import get_registry
            import json as _json
            returns = self._live_returns
            returns_payload = _json.dumps({
                "values": returns[-500:],
                "equity": equity,
            })
            with get_registry() as reg:
                reg.heartbeat(
                    self.config.deployment_id,
                    pnl_realized=float(equity),
                    n_trades=len(returns),
                    returns_json=returns_payload,
                )
        except Exception as exc:
            logger.warning("[%s] Heartbeat write failed: %s", self.config.deployment_id, exc)

    def _update_registry_state(self, state: str, rejection_reason: str | None = None) -> None:
        try:
            from live.deployment_registry import get_registry
            with get_registry() as reg:
                reg.update_state(self.config.deployment_id, state, rejection_reason=rejection_reason)
        except Exception as exc:
            logger.warning("[%s] Registry state update failed: %s", self.config.deployment_id, exc)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m live.live_runner <deployment_id>")
        sys.exit(1)

    deployment_id = sys.argv[1]

    from live.deployment_registry import get_registry
    with get_registry() as reg:
        record = reg.get(deployment_id)

    if record is None:
        print(f"Deployment {deployment_id!r} not found in registry")
        sys.exit(1)

    cfg = LiveRunnerConfig(
        deployment_id=record.deployment_id,
        run_dir=record.run_dir,
        broker_name=record.broker,
        symbols=record.symbols,
        interval=record.interval,
        cadence=record.cadence,
        paper=(record.account_type == "paper"),
    )
    logging.basicConfig(level=logging.INFO)
    LiveRunner(cfg).run()
