"""Signal → order sizing and position drift management.

Converts signal_engine weight outputs ([-1, 1]) into concrete OrderSpecs
for the active broker. Avoids churning small position changes via a drift
threshold.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from live.broker_base import OrderSpec

if TYPE_CHECKING:
    from live.broker_base import BaseBroker, LivePosition


_DEFAULT_DRIFT_THRESHOLD = 0.02   # don't trade if target-vs-actual weight diff < 2%
_DEFAULT_MIN_NOTIONAL = 1.0       # skip orders below $1 notional


def signal_to_qty(
    weight: float,
    equity: float,
    price: float,
    *,
    min_qty: float = 0.0,
    max_notional: float | None = None,
    fractional: bool = True,
) -> float:
    """Convert a target weight to a share quantity.

    Args:
        weight: Target portfolio weight in [-1, 1]. Positive = long, negative = short.
        equity: Account equity in dollars.
        price: Current instrument price.
        min_qty: Minimum fill size. Orders below this are skipped (return 0).
        max_notional: Hard cap on notional per order.
        fractional: If False, round down to the nearest whole share.

    Returns:
        Target qty (positive = long, negative = short). May be 0 if below min_qty.
    """
    if price <= 0:
        return 0.0
    notional = abs(weight) * equity
    if max_notional is not None:
        notional = min(notional, max_notional)
    qty = notional / price
    if not fractional:
        qty = math.floor(qty)
    if qty < max(min_qty, 0.0):
        return 0.0
    return math.copysign(qty, weight)


def compute_orders(
    target_weights: dict[str, float],
    current_positions: dict[str, "LivePosition"],
    equity: float,
    prices: dict[str, float],
    *,
    drift_threshold: float = _DEFAULT_DRIFT_THRESHOLD,
    min_notional: float = _DEFAULT_MIN_NOTIONAL,
    fractional: bool = True,
) -> list[OrderSpec]:
    """Compute the minimal set of orders to move from current to target weights.

    Only generates an order if the weight drift exceeds `drift_threshold`
    to avoid excessive churn on small signal updates.

    Args:
        target_weights: Symbol → target weight from signal_engine.generate().
        current_positions: Symbol → LivePosition from broker.get_positions().
        equity: Total account equity.
        prices: Symbol → latest close price.
        drift_threshold: Min |target - actual| weight to trigger a trade.
        min_notional: Skip orders below this dollar size.
        fractional: Whether the broker supports fractional shares.

    Returns:
        List of OrderSpec to submit.
    """
    orders: list[OrderSpec] = []
    all_symbols = set(target_weights) | set(current_positions)

    for symbol in all_symbols:
        target_w = target_weights.get(symbol, 0.0)
        price = prices.get(symbol, 0.0)
        if price <= 0:
            continue

        pos = current_positions.get(symbol)
        current_qty = pos.qty if pos else 0.0
        current_notional = current_qty * price
        current_w = current_notional / equity if equity > 0 else 0.0

        drift = target_w - current_w
        if abs(drift) < drift_threshold:
            continue

        target_qty = signal_to_qty(target_w, equity, price, fractional=fractional)
        delta_qty = target_qty - current_qty

        if abs(delta_qty * price) < min_notional:
            continue

        side = "buy" if delta_qty > 0 else "sell"
        orders.append(OrderSpec(
            symbol=symbol,
            qty=abs(delta_qty),
            side=side,
        ))

    return orders
