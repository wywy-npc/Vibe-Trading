"""Tests for marketdata.providers.alpaca_rest using a mocked httpx client."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import httpx
import pytest

from marketdata.config import MarketDataConfig
from marketdata.providers.alpaca_rest import (
    AlpacaError,
    AlpacaRest,
    _iso,
    _project_to_alpaca_symbol,
)


def _config(tmp_path: Path) -> MarketDataConfig:
    return MarketDataConfig(
        alpaca_key_id="key",
        alpaca_secret_key="secret",
        alpaca_base_url="https://paper-api.alpaca.markets",
        alpaca_data_url="https://data.alpaca.markets",
        alpaca_stream_url="wss://stream.data.alpaca.markets/v2/iex",
        alpaca_feed="iex",
        db_path=tmp_path / "marketdata.duckdb",
        parquet_dir=tmp_path / "parquet",
        watchlist=[],
        options_tier="free",
    )


def _mock_client(handler) -> httpx.Client:
    """Return an httpx.Client whose every request is served by ``handler``."""
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, headers={"X-Test": "1"})


class TestSymbolNormalization:
    def test_strips_us_suffix(self) -> None:
        assert _project_to_alpaca_symbol("AAPL.US") == "AAPL"
        assert _project_to_alpaca_symbol("aapl") == "AAPL"
        assert _project_to_alpaca_symbol("700.HK") == "700.HK"  # untouched


class TestIso:
    def test_naive_datetime_treated_as_utc(self) -> None:
        out = _iso(dt.datetime(2026, 1, 2, 14, 30, 0))
        assert out.endswith("Z")
        assert "2026-01-02T14:30:00" in out

    def test_date_becomes_midnight_utc(self) -> None:
        assert _iso(dt.date(2026, 1, 2)) == "2026-01-02T00:00:00Z"


class TestFetchBars:
    def test_paginated_fetch(self, tmp_path: Path) -> None:
        calls: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append({"url": str(request.url), "params": dict(request.url.params)})
            if "page_token" in dict(request.url.params):
                # Second page.
                return httpx.Response(200, json={
                    "bars": {"AAPL": [
                        {"t": "2026-01-03T00:00:00Z", "o": 104, "h": 108, "l": 103, "c": 107, "v": 2000},
                    ]},
                    "next_page_token": None,
                })
            # First page.
            return httpx.Response(200, json={
                "bars": {"AAPL": [
                    {"t": "2026-01-02T00:00:00Z", "o": 100, "h": 105, "l": 99, "c": 104, "v": 1000},
                ]},
                "next_page_token": "abc",
            })

        cfg = _config(tmp_path)
        with AlpacaRest(cfg, client=_mock_client(handler)) as client:
            bars = list(client.fetch_bars(["AAPL"], start="2026-01-01", end="2026-01-04", interval="1d"))

        assert [b.ts.date() for b in bars] == [dt.date(2026, 1, 2), dt.date(2026, 1, 3)]
        assert bars[0].close == 104.0
        assert bars[1].volume == 2000
        assert len(calls) == 2
        assert calls[0]["params"]["symbols"] == "AAPL"
        assert calls[0]["params"]["timeframe"] == "1Day"
        assert calls[0]["params"]["feed"] == "iex"

    def test_empty_response(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"bars": {}, "next_page_token": None})

        cfg = _config(tmp_path)
        with AlpacaRest(cfg, client=_mock_client(handler)) as client:
            bars = list(client.fetch_bars(["AAPL"], start="2026-01-01", end="2026-01-04"))
        assert bars == []


class TestAccountAndPositions:
    def test_fetch_account_parses_payload(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "id": "acct-abc",
                "cash": "1234.56",
                "equity": "25000.00",
                "buying_power": "50000.00",
                "portfolio_value": "25000.00",
                "currency": "USD",
                "status": "ACTIVE",
            })

        cfg = _config(tmp_path)
        with AlpacaRest(cfg, client=_mock_client(handler)) as client:
            acct = client.fetch_account()
        assert acct.account_id == "acct-abc"
        assert acct.cash == 1234.56
        assert acct.equity == 25000.0
        assert acct.status == "ACTIVE"

    def test_fetch_positions_parses_rows(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[
                {
                    "symbol": "AAPL",
                    "asset_class": "us_equity",
                    "qty": "10",
                    "avg_entry_price": "150.0",
                    "current_price": "160.0",
                    "market_value": "1600.0",
                    "unrealized_pl": "100.0",
                },
            ])

        cfg = _config(tmp_path)
        with AlpacaRest(cfg, client=_mock_client(handler)) as client:
            positions = client.fetch_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].qty == 10.0
        assert positions[0].market_value == 1600.0


class TestErrorHandling:
    def test_4xx_raises_alpaca_error(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text='{"message":"unauthorized"}')

        cfg = _config(tmp_path)
        with AlpacaRest(cfg, client=_mock_client(handler)) as client:
            with pytest.raises(AlpacaError, match="401"):
                client.fetch_account()

    def test_missing_credentials(self, tmp_path: Path) -> None:
        cfg = MarketDataConfig(
            alpaca_key_id=None, alpaca_secret_key=None,
            alpaca_base_url="x", alpaca_data_url="x", alpaca_stream_url="x",
            alpaca_feed="iex",
            db_path=tmp_path / "x.duckdb", parquet_dir=tmp_path / "p",
        )
        with pytest.raises(AlpacaError, match="credentials missing"):
            AlpacaRest(cfg)


class TestOptionContracts:
    def test_paginated_contract_listing(self, tmp_path: Path) -> None:
        pages = [
            {
                "option_contracts": [
                    {"symbol": "AAPL250620C00200000", "underlying_symbol": "AAPL",
                     "expiration_date": "2026-06-20", "strike_price": "200",
                     "type": "call", "style": "american"},
                ],
                "next_page_token": "p2",
            },
            {
                "option_contracts": [
                    {"symbol": "AAPL250620P00200000", "underlying_symbol": "AAPL",
                     "expiration_date": "2026-06-20", "strike_price": "200",
                     "type": "put", "style": "american"},
                ],
                "next_page_token": None,
            },
        ]
        idx = {"i": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            page = pages[idx["i"]]
            idx["i"] += 1
            return httpx.Response(200, json=page)

        cfg = _config(tmp_path)
        with AlpacaRest(cfg, client=_mock_client(handler)) as client:
            contracts = list(client.fetch_option_contracts("AAPL"))
        assert len(contracts) == 2
        assert contracts[0].option_type == "call"
        assert contracts[1].option_type == "put"
        assert contracts[0].strike == 200.0
        assert contracts[0].expiry == dt.date(2026, 6, 20)
