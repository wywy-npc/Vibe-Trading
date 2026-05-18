"""Alpaca REST provider — historical bars, account, positions, orders, option chains.

Uses ``httpx`` (already a project dependency) rather than ``alpaca-py`` to keep
the dependency surface small and to make request/response shapes explicit for
testing. If we later need streaming or pandas helpers from alpaca-py, the
provider class can be swapped without touching the loader or daemon.

Free tier coverage (verify against current Alpaca docs):
  * Stock bars: real-time IEX, 15-min delayed SIP
  * Stock snapshots/quotes: IEX feed real-time
  * Account/positions/orders: full access on paper + live
  * Options chain enumeration: free (Trading API ``/v2/options/contracts``)
  * Options market data quotes: requires Algo Trader Plus (degrade gracefully)
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

import httpx

from marketdata.config import MarketDataConfig

logger = logging.getLogger(__name__)


_BAR_TIMEFRAME_MAP = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "30m": "30Min",
    "1h": "1Hour",
    "4h": "4Hour",
    "1d": "1Day",
    # Tolerate uppercase project conventions too
    "1D": "1Day",
    "1H": "1Hour",
    "4H": "4Hour",
}


class AlpacaError(RuntimeError):
    """Raised when the Alpaca API returns an unexpected error."""


@dataclass(frozen=True)
class AlpacaBar:
    symbol: str
    ts: dt.datetime           # UTC, bar close
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class AlpacaAccount:
    account_id: str
    ts: dt.datetime
    cash: float
    equity: float
    buying_power: float
    portfolio_value: float
    currency: str
    status: str


@dataclass(frozen=True)
class AlpacaPosition:
    symbol: str
    asset_class: str
    qty: float
    avg_entry: float
    market_price: float
    market_value: float
    unrealized_pl: float


@dataclass(frozen=True)
class AlpacaOrder:
    order_id: str
    account_id: str
    symbol: str
    side: str
    qty: float
    filled_qty: float
    order_type: str
    limit_price: float | None
    stop_price: float | None
    status: str
    submitted_at: dt.datetime | None
    updated_at: dt.datetime | None


@dataclass(frozen=True)
class AlpacaOptionContract:
    contract_symbol: str
    underlying: str
    expiry: dt.date
    strike: float
    option_type: str            # 'call' | 'put'
    exercise_style: str | None


def _project_to_alpaca_symbol(code: str) -> str:
    """``AAPL.US`` -> ``AAPL``. Leave non-suffixed symbols untouched."""
    upper = code.strip().upper()
    if upper.endswith(".US"):
        return upper[:-3]
    return upper


def _parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    s = value.replace("Z", "+00:00")
    return dt.datetime.fromisoformat(s)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


class AlpacaRest:
    """Synchronous Alpaca REST client.

    The daemon and the AlpacaLoader both consume this class. It keeps a
    single ``httpx.Client`` open for the lifetime of the instance and is
    safe to use from one thread.
    """

    def __init__(
        self,
        config: MarketDataConfig,
        *,
        client: httpx.Client | None = None,
        timeout: float = 20.0,
    ):
        if not config.has_credentials:
            raise AlpacaError(
                "Alpaca credentials missing: set ALPACA_KEY_ID and ALPACA_SECRET_KEY."
            )
        self._cfg = config
        self._headers = {
            "APCA-API-KEY-ID": config.alpaca_key_id or "",
            "APCA-API-SECRET-KEY": config.alpaca_secret_key or "",
            "Accept": "application/json",
        }
        self._client = client or httpx.Client(timeout=timeout, headers=self._headers)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "AlpacaRest":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---- HTTP helpers ----------------------------------------------------
    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._client.get(url, params=params or {})
        if resp.status_code >= 400:
            raise AlpacaError(
                f"GET {url} failed [{resp.status_code}]: {resp.text[:300]}"
            )
        return resp.json()

    # ---- historical bars -------------------------------------------------
    def fetch_bars(
        self,
        symbols: Iterable[str],
        start: dt.datetime | dt.date | str,
        end: dt.datetime | dt.date | str,
        *,
        interval: str = "1d",
        feed: str | None = None,
        adjustment: str = "all",
        page_limit: int = 10_000,
    ) -> Iterator[AlpacaBar]:
        """Yield ``AlpacaBar`` rows for each symbol in ``symbols``.

        Paginates server-side; uses Alpaca's bulk-symbol endpoint.
        Bars are emitted in the order Alpaca returns them.
        """
        symbol_list = [_project_to_alpaca_symbol(s) for s in symbols if s]
        if not symbol_list:
            return
        timeframe = _BAR_TIMEFRAME_MAP.get(interval, interval)
        url = f"{self._cfg.alpaca_data_url}/v2/stocks/bars"
        page_token: str | None = None
        params_base: dict[str, Any] = {
            "symbols": ",".join(symbol_list),
            "timeframe": timeframe,
            "start": _iso(start),
            "end": _iso(end),
            "limit": page_limit,
            "adjustment": adjustment,
            "feed": (feed or self._cfg.alpaca_feed),
        }
        while True:
            params = dict(params_base)
            if page_token:
                params["page_token"] = page_token
            data = self._get(url, params)
            bars_by_symbol = data.get("bars") or {}
            for sym, rows in bars_by_symbol.items():
                for row in rows:
                    ts = _parse_ts(row.get("t"))
                    if ts is None:
                        continue
                    yield AlpacaBar(
                        symbol=sym,
                        ts=ts.astimezone(dt.timezone.utc).replace(tzinfo=None),
                        open=_to_float(row.get("o")) or 0.0,
                        high=_to_float(row.get("h")) or 0.0,
                        low=_to_float(row.get("l")) or 0.0,
                        close=_to_float(row.get("c")) or 0.0,
                        volume=_to_int(row.get("v")) or 0,
                    )
            page_token = data.get("next_page_token")
            if not page_token:
                return

    # ---- account / positions / orders ------------------------------------
    def fetch_account(self) -> AlpacaAccount:
        data = self._get(f"{self._cfg.alpaca_base_url}/v2/account")
        return AlpacaAccount(
            account_id=str(data.get("id") or data.get("account_number") or "unknown"),
            ts=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None),
            cash=_to_float(data.get("cash")) or 0.0,
            equity=_to_float(data.get("equity")) or 0.0,
            buying_power=_to_float(data.get("buying_power")) or 0.0,
            portfolio_value=_to_float(data.get("portfolio_value"))
                or _to_float(data.get("equity"))
                or 0.0,
            currency=str(data.get("currency") or "USD"),
            status=str(data.get("status") or "UNKNOWN"),
        )

    def fetch_positions(self) -> list[AlpacaPosition]:
        rows = self._get(f"{self._cfg.alpaca_base_url}/v2/positions")
        if not isinstance(rows, list):
            return []
        result: list[AlpacaPosition] = []
        for r in rows:
            result.append(AlpacaPosition(
                symbol=str(r.get("symbol") or ""),
                asset_class=str(r.get("asset_class") or "us_equity"),
                qty=_to_float(r.get("qty")) or 0.0,
                avg_entry=_to_float(r.get("avg_entry_price")) or 0.0,
                market_price=_to_float(r.get("current_price")) or 0.0,
                market_value=_to_float(r.get("market_value")) or 0.0,
                unrealized_pl=_to_float(r.get("unrealized_pl")) or 0.0,
            ))
        return result

    def fetch_orders(
        self,
        *,
        status: str = "all",
        limit: int = 200,
        account_id: str = "default",
    ) -> list[AlpacaOrder]:
        rows = self._get(
            f"{self._cfg.alpaca_base_url}/v2/orders",
            params={"status": status, "limit": limit, "direction": "desc"},
        )
        if not isinstance(rows, list):
            return []
        result: list[AlpacaOrder] = []
        for r in rows:
            result.append(AlpacaOrder(
                order_id=str(r.get("id") or ""),
                account_id=account_id,
                symbol=str(r.get("symbol") or ""),
                side=str(r.get("side") or ""),
                qty=_to_float(r.get("qty")) or 0.0,
                filled_qty=_to_float(r.get("filled_qty")) or 0.0,
                order_type=str(r.get("order_type") or r.get("type") or ""),
                limit_price=_to_float(r.get("limit_price")),
                stop_price=_to_float(r.get("stop_price")),
                status=str(r.get("status") or ""),
                submitted_at=_parse_ts(r.get("submitted_at")),
                updated_at=_parse_ts(r.get("updated_at") or r.get("submitted_at")),
            ))
        return result

    # ---- options ---------------------------------------------------------
    def fetch_option_contracts(
        self,
        underlying: str,
        *,
        expiry: dt.date | None = None,
        page_limit: int = 1_000,
    ) -> Iterator[AlpacaOptionContract]:
        """Yield active option contracts for an underlying.

        Free-tier-safe: hits the Trading API contract directory, which is
        not gated behind options market data tier.
        """
        url = f"{self._cfg.alpaca_base_url}/v2/options/contracts"
        params_base: dict[str, Any] = {
            "underlying_symbols": _project_to_alpaca_symbol(underlying),
            "status": "active",
            "limit": page_limit,
        }
        if expiry is not None:
            params_base["expiration_date"] = expiry.isoformat()
        page_token: str | None = None
        while True:
            params = dict(params_base)
            if page_token:
                params["page_token"] = page_token
            data = self._get(url, params)
            for c in data.get("option_contracts") or []:
                expiry_str = c.get("expiration_date")
                try:
                    expiry_d = dt.date.fromisoformat(expiry_str) if expiry_str else None
                except ValueError:
                    expiry_d = None
                if expiry_d is None:
                    continue
                strike = _to_float(c.get("strike_price"))
                if strike is None:
                    continue
                yield AlpacaOptionContract(
                    contract_symbol=str(c.get("symbol") or ""),
                    underlying=str(c.get("underlying_symbol") or underlying).upper(),
                    expiry=expiry_d,
                    strike=strike,
                    option_type=str(c.get("type") or "").lower(),
                    exercise_style=str(c.get("style") or "").lower() or None,
                )
            page_token = data.get("next_page_token")
            if not page_token:
                return


def _iso(value: dt.datetime | dt.date | str) -> str:
    """Coerce any of (str, date, datetime) into an RFC3339 UTC string for Alpaca."""
    if isinstance(value, str):
        return value
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    # date
    return dt.datetime.combine(value, dt.time(0, 0), tzinfo=dt.timezone.utc) \
        .isoformat().replace("+00:00", "Z")


__all__ = [
    "AlpacaError",
    "AlpacaBar",
    "AlpacaAccount",
    "AlpacaPosition",
    "AlpacaOrder",
    "AlpacaOptionContract",
    "AlpacaRest",
]
