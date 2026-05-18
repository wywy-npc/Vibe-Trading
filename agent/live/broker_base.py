"""Abstract broker interface for all live-trading integrations.

All concrete brokers (Alpaca, IBKR) implement this contract. The live runner
only talks to BaseBroker so the same execution loop works across venues.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator


@dataclass(frozen=True)
class OrderSpec:
    symbol: str
    qty: float
    side: str          # "buy" | "sell"
    order_type: str = "market"


@dataclass(frozen=True)
class ExecutionResult:
    order_id: str
    symbol: str
    filled_qty: float
    avg_price: float
    timestamp: datetime
    side: str


@dataclass(frozen=True)
class LivePosition:
    symbol: str
    qty: float
    avg_entry_price: float
    market_value: float
    unrealized_pnl: float


@dataclass(frozen=True)
class Bar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class BaseBroker(ABC):
    """Interface every broker adapter must satisfy."""

    paper: bool = True

    @abstractmethod
    def place_order(self, spec: OrderSpec) -> ExecutionResult:
        """Submit an order. Blocks until a fill confirmation is received."""

    @abstractmethod
    def get_positions(self) -> dict[str, LivePosition]:
        """Current open positions keyed by symbol."""

    @abstractmethod
    def get_account_equity(self) -> float:
        """Total account equity (net liquidation value)."""

    @abstractmethod
    def cancel_all_orders(self) -> None:
        """Cancel all open / pending orders."""

    @abstractmethod
    def is_market_open(self) -> bool:
        """True if the primary venue is currently open for trading."""

    @abstractmethod
    async def subscribe_bars(
        self, symbols: list[str], timeframe: str
    ) -> AsyncIterator[Bar]:
        """Yield completed bars in real time. Used by AsyncLiveRunner.

        Args:
            symbols: Instrument codes in broker format.
            timeframe: e.g. "1Min", "5Min", "1Hour".
        """
        # Must be an async generator — yield bars as they arrive.
        raise NotImplementedError
        # Make mypy happy: generators need at least one yield
        yield  # type: ignore[misc]

    @classmethod
    def check_available(cls) -> bool:
        """Return False if required deps or credentials are missing.

        Implementing brokers override this so the tool registry can skip
        unavailable brokers without raising import errors.
        """
        return True
