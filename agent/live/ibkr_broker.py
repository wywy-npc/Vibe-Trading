"""Interactive Brokers broker adapter via ib_insync.

Requires:
  - pip install ib_insync
  - TWS or IB Gateway running locally (or accessible host)

Port conventions:
  - TWS paper:    7497   TWS live:    7496
  - IB Gateway paper: 4002   IB Gateway live: 4001
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import AsyncIterator

from live.broker_base import Bar, BaseBroker, ExecutionResult, LivePosition, OrderSpec

try:
    import ib_insync as ibi

    _IBI_AVAILABLE = True
except ImportError:
    _IBI_AVAILABLE = False


def _paper_port() -> int:
    return int(os.environ.get("IBKR_PAPER_PORT", "7497"))


def _live_port() -> int:
    return int(os.environ.get("IBKR_LIVE_PORT", "7496"))


class IbkrBroker(BaseBroker):
    """IBKR broker adapter.

    Env vars:
        IBKR_HOST       — TWS/Gateway host (default 127.0.0.1)
        IBKR_PAPER_PORT — paper port (default 7497 for TWS, 4002 for Gateway)
        IBKR_LIVE_PORT  — live port  (default 7496 for TWS, 4001 for Gateway)
        IBKR_CLIENT_ID  — unique int per connection (default 1)
    """

    def __init__(
        self,
        host: str | None = None,
        paper: bool = True,
        client_id: int | None = None,
    ) -> None:
        if not _IBI_AVAILABLE:
            raise ImportError("ib_insync is required: pip install ib_insync")

        self._host = host or os.environ.get("IBKR_HOST", "127.0.0.1")
        self._client_id = client_id or int(os.environ.get("IBKR_CLIENT_ID", "1"))
        self.paper = paper
        self._port = _paper_port() if paper else _live_port()
        self._ib = ibi.IB()

    @classmethod
    def check_available(cls) -> bool:
        return _IBI_AVAILABLE

    def connect(self) -> None:
        if not self._ib.isConnected():
            self._ib.connect(self._host, self._port, clientId=self._client_id)

    def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()

    def __enter__(self) -> IbkrBroker:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()

    def place_order(self, spec: OrderSpec) -> ExecutionResult:
        self.connect()
        contract = ibi.Stock(spec.symbol, "SMART", "USD")
        self._ib.qualifyContracts(contract)
        action = "BUY" if spec.side == "buy" else "SELL"
        order = ibi.MarketOrder(action, abs(spec.qty))
        trade = self._ib.placeOrder(contract, order)
        # Wait for fill (synchronous-compatible)
        self._ib.sleep(0)
        filled_qty = float(trade.orderStatus.filled or 0)
        avg_price = float(trade.orderStatus.avgFillPrice or 0)
        return ExecutionResult(
            order_id=str(trade.order.orderId),
            symbol=spec.symbol,
            filled_qty=filled_qty,
            avg_price=avg_price,
            timestamp=datetime.now(timezone.utc),
            side=spec.side,
        )

    def get_positions(self) -> dict[str, LivePosition]:
        self.connect()
        result: dict[str, LivePosition] = {}
        for pos in self._ib.positions():
            sym = pos.contract.symbol
            result[sym] = LivePosition(
                symbol=sym,
                qty=float(pos.position),
                avg_entry_price=float(pos.avgCost),
                market_value=float(pos.position) * float(pos.avgCost),
                unrealized_pnl=0.0,
            )
        return result

    def get_account_equity(self) -> float:
        self.connect()
        for item in self._ib.accountSummary():
            if item.tag == "NetLiquidation" and item.currency == "USD":
                return float(item.value)
        return 0.0

    def cancel_all_orders(self) -> None:
        self.connect()
        for order in self._ib.openOrders():
            self._ib.cancelOrder(order)
        self._ib.sleep(0)

    def is_market_open(self) -> bool:
        self.connect()
        contract = ibi.Stock("SPY", "SMART", "USD")
        self._ib.qualifyContracts(contract)
        details = self._ib.reqContractDetails(contract)
        if not details:
            return False
        # TradingHours check is complex — simple heuristic: 9:30–16:00 EST weekdays
        from datetime import time as dtime
        import zoneinfo
        now = datetime.now(zoneinfo.ZoneInfo("America/New_York"))
        if now.weekday() >= 5:
            return False
        return dtime(9, 30) <= now.time() <= dtime(16, 0)

    async def subscribe_bars(
        self, symbols: list[str], timeframe: str = "1 min"
    ) -> AsyncIterator[Bar]:
        """Yield real-time bars via IBKR reqRealTimeBars (5-second granularity).

        Args:
            symbols: Equity symbols in IBKR format.
            timeframe: Passed but IBKR real-time bars are always 5-second;
                       caller should aggregate if coarser bars are needed.
        """
        self.connect()
        queue: asyncio.Queue[Bar] = asyncio.Queue()

        bars_objs = []
        for sym in symbols:
            contract = ibi.Stock(sym, "SMART", "USD")
            self._ib.qualifyContracts(contract)
            rtb = self._ib.reqRealTimeBars(contract, 5, "TRADES", False)

            def _make_handler(symbol: str, rtb_ref: ibi.RealTimeBarList) -> None:
                def _on_bar(bars: ibi.RealTimeBarList, has_new: bool) -> None:
                    if has_new and bars:
                        b = bars[-1]
                        asyncio.get_event_loop().call_soon_threadsafe(
                            queue.put_nowait,
                            Bar(
                                symbol=symbol,
                                timestamp=datetime.fromtimestamp(b.time, tz=timezone.utc),
                                open=float(b.open_),
                                high=float(b.high),
                                low=float(b.low),
                                close=float(b.close),
                                volume=float(b.volume),
                            ),
                        )
                rtb_ref.updateEvent += _on_bar

            _make_handler(sym, rtb)
            bars_objs.append(rtb)

        try:
            while True:
                bar = await queue.get()
                yield bar
        finally:
            for rtb in bars_objs:
                self._ib.cancelRealTimeBars(rtb)
