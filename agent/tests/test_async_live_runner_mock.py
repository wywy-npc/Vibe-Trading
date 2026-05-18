"""Tests for AsyncLiveRunner with a mocked bar stream."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from live.async_live_runner import AsyncLiveRunner, AsyncRunnerConfig
from live.broker_base import Bar, ExecutionResult


@pytest.fixture()
def tmp_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from live.deployment_registry import _DB_PATH_ENV
    db = tmp_path / "deps.db"
    monkeypatch.setenv(_DB_PATH_ENV, str(db))
    return db


@pytest.fixture()
def signal_engine_dir(tmp_path: Path) -> Path:
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    # Strategy: buy when 5-day close mean > 10-day close mean
    (code_dir / "signal_engine.py").write_text("""
import pandas as pd

class SignalEngine:
    def generate(self, data_map):
        out = {}
        for sym, df in data_map.items():
            close = df["close"]
            out[sym] = 1.0 if close.rolling(5).mean().iloc[-1] > close.rolling(10).mean().iloc[-1] else -1.0
        return out
""")
    return tmp_path


def _make_bars(symbol: str, n: int = 25) -> list[Bar]:
    """Synthetic uptrending bars so signal flips to 1.0."""
    bars = []
    for i in range(n):
        price = 400 + i * 0.5
        bars.append(Bar(
            symbol=symbol,
            timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
            open=price,
            high=price + 0.5,
            low=price - 0.5,
            close=price,
            volume=1_000_000,
        ))
    return bars


async def _bar_stream(bars: list[Bar]):
    for bar in bars:
        yield bar


def _make_broker_mock():
    broker = MagicMock()
    broker.get_account_equity.return_value = 100_000.0
    broker.get_positions.return_value = {}
    broker.place_order.return_value = ExecutionResult(
        order_id="o1", symbol="SPY", filled_qty=5.0, avg_price=450.0,
        timestamp=datetime.now(timezone.utc), side="buy",
    )
    return broker


def test_intraday_bar_triggers_rebalance(
    signal_engine_dir: Path, tmp_registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Feeding 25 uptrending bars should trigger at least one buy order."""
    broker = _make_broker_mock()

    def _fake_make_broker(_config):
        return broker

    monkeypatch.setattr("live.async_live_runner._make_broker", _fake_make_broker)

    config = AsyncRunnerConfig(
        deployment_id="test_async",
        run_dir=str(signal_engine_dir),
        broker_name="alpaca",
        symbols=["SPY"],
        timeframe="1Min",
        paper=True,
        window_bars=25,
    )

    runner = AsyncLiveRunner(config)
    bars = _make_bars("SPY", n=25)

    asyncio.run(runner.run(bar_stream=_bar_stream(bars)))

    # With 25 uptrending bars the MA cross should fire at least once
    assert broker.place_order.call_count >= 1


def test_kill_switch_halts_on_drawdown(
    signal_engine_dir: Path, tmp_registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After injecting a large drawdown, the runner should halt before consuming all bars."""
    broker = _make_broker_mock()
    monkeypatch.setattr("live.async_live_runner._make_broker", lambda _c: broker)

    config = AsyncRunnerConfig(
        deployment_id="test_async_kill",
        run_dir=str(signal_engine_dir),
        broker_name="alpaca",
        symbols=["SPY"],
        timeframe="1Min",
        paper=True,
        max_drawdown=0.01,  # 1% — very tight
    )

    runner = AsyncLiveRunner(config)
    # Pre-inject returns that already breach the 1% drawdown limit
    runner._live_returns = [0.005, 0.005, -0.025, -0.01]

    bars = _make_bars("SPY", n=30)
    asyncio.run(runner.run(bar_stream=_bar_stream(bars)))

    assert runner._halted is True
