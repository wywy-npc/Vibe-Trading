"""Alpaca broker adapter — REST orders + WebSocket bar streaming.

Paper vs live is toggled by ALPACA_PAPER env var (default True).
Credentials from ALPACA_API_KEY + ALPACA_API_SECRET.

Requires: alpaca-py >= 0.29.0
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import AsyncIterator

from live.broker_base import Bar, BaseBroker, ExecutionResult, LivePosition, OrderSpec

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.live import StockDataStream, CryptoDataStream
    from alpaca.data.models import Bar as AlpacaBar

    _ALPACA_AVAILABLE = True
except ImportError:
    _ALPACA_AVAILABLE = False


class AlpacaBroker(BaseBroker):
    """Alpaca broker for US equities and crypto.

    Env vars:
        ALPACA_API_KEY      — required
        ALPACA_API_SECRET   — required
        ALPACA_PAPER        — "true" (default) or "false"
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        paper: bool | None = None,
    ) -> None:
        self._key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self._secret = api_secret or os.environ.get("ALPACA_API_SECRET", "")
        if paper is None:
            paper = os.environ.get("ALPACA_PAPER", "true").lower() != "false"
        self.paper = paper

        if not _ALPACA_AVAILABLE:
            raise ImportError("alpaca-py is required: pip install alpaca-py")
        if not self._key or not self._secret:
            raise ValueError("ALPACA_API_KEY and ALPACA_API_SECRET must be set")

        self._client = TradingClient(self._key, self._secret, paper=self.paper)

    @classmethod
    def check_available(cls) -> bool:
        return (
            _ALPACA_AVAILABLE
            and bool(os.environ.get("ALPACA_API_KEY"))
            and bool(os.environ.get("ALPACA_API_SECRET"))
        )

    def place_order(self, spec: OrderSpec) -> ExecutionResult:
        side = OrderSide.BUY if spec.side == "buy" else OrderSide.SELL
        req = MarketOrderRequest(
            symbol=spec.symbol,
            qty=spec.qty,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(req)
        return ExecutionResult(
            order_id=str(order.id),
            symbol=spec.symbol,
            filled_qty=float(order.filled_qty or 0),
            avg_price=float(order.filled_avg_price or 0),
            timestamp=datetime.now(timezone.utc),
            side=spec.side,
        )

    def get_positions(self) -> dict[str, LivePosition]:
        positions = self._client.get_all_positions()
        return {
            p.symbol: LivePosition(
                symbol=p.symbol,
                qty=float(p.qty),
                avg_entry_price=float(p.avg_entry_price),
                market_value=float(p.market_value or 0),
                unrealized_pnl=float(p.unrealized_pl or 0),
            )
            for p in positions
        }

    def get_account_equity(self) -> float:
        account = self._client.get_account()
        return float(account.equity or account.portfolio_value or 0)

    def cancel_all_orders(self) -> None:
        self._client.cancel_orders()

    def is_market_open(self) -> bool:
        clock = self._client.get_clock()
        return bool(clock.is_open)

    async def subscribe_bars(
        self, symbols: list[str], timeframe: str = "1Min"
    ) -> AsyncIterator[Bar]:
        """Yield live bars from Alpaca WebSocket.

        Dispatches to StockDataStream or CryptoDataStream based on symbol format.
        Crypto symbols contain '/' (e.g. 'BTC/USD').
        """
        is_crypto = any("/" in s or "-" in s for s in symbols)
        StreamCls = CryptoDataStream if is_crypto else StockDataStream

        bars: list[Bar] = []

        stream = StreamCls(self._key, self._secret)

        async def _handler(bar: "AlpacaBar") -> None:
            bars.append(Bar(
                symbol=bar.symbol,
                timestamp=bar.timestamp,
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume),
            ))

        stream.subscribe_bars(_handler, *symbols)

        # Run the stream in the background and yield bars as they arrive.
        import asyncio
        stream_task = asyncio.create_task(stream.run())
        try:
            while True:
                if bars:
                    yield bars.pop(0)
                else:
                    await asyncio.sleep(0.1)
        finally:
            stream_task.cancel()
