"""Tests for the AlpacaLoader (DataLoaderProtocol implementation)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import httpx
import pandas as pd
import pytest

from marketdata.config import MarketDataConfig
from marketdata.loaders.alpaca_loader import DataLoader
from marketdata.providers import alpaca_rest as alpaca_rest_mod

duckdb = pytest.importorskip("duckdb")


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


def _make_mock_transport(payload_by_symbol: dict[str, list[dict]]) -> httpx.MockTransport:
    """Build a MockTransport that returns bars for the given symbols."""
    def handler(request: httpx.Request) -> httpx.Response:
        symbols_param = request.url.params.get("symbols", "")
        wanted = [s for s in symbols_param.split(",") if s]
        bars = {s: payload_by_symbol.get(s, []) for s in wanted}
        return httpx.Response(200, json={"bars": bars, "next_page_token": None})
    return httpx.MockTransport(handler)


def _install_mock_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> list[httpx.Client]:
    """Patch alpaca_rest so AlpacaRest uses our mock transport.

    Returns a list to which each constructed client is appended for inspection.
    """
    captured: list[httpx.Client] = []
    original_cls = alpaca_rest_mod.AlpacaRest

    class _PatchedAlpacaRest(original_cls):  # type: ignore[misc, valid-type]
        def __init__(self, config, *, client=None, timeout=20.0):
            mock_client = httpx.Client(transport=transport, headers={"X-Test": "1"})
            captured.append(mock_client)
            super().__init__(config, client=mock_client, timeout=timeout)

    monkeypatch.setattr(alpaca_rest_mod, "AlpacaRest", _PatchedAlpacaRest)
    # The loader imports AlpacaRest by name; patch that binding too.
    monkeypatch.setattr(
        "marketdata.loaders.alpaca_loader.AlpacaRest", _PatchedAlpacaRest
    )
    return captured


def _bar(date_str: str, c: float) -> dict:
    return {"t": f"{date_str}T00:00:00Z", "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 1000}


class TestLoaderProtocolBasics:
    def test_class_attributes(self) -> None:
        assert DataLoader.name == "alpaca"
        assert "us_equity" in DataLoader.markets
        assert DataLoader.requires_auth is True

    def test_unavailable_without_credentials(self, tmp_path: Path) -> None:
        cfg = MarketDataConfig(
            alpaca_key_id=None, alpaca_secret_key=None,
            alpaca_base_url="x", alpaca_data_url="x", alpaca_stream_url="x",
            alpaca_feed="iex",
            db_path=tmp_path / "x.duckdb", parquet_dir=tmp_path / "p",
        )
        loader = DataLoader(config=cfg)
        assert loader.is_available() is False


class TestFetchCachePopulation:
    def test_first_fetch_populates_cache_and_returns_canonical_frame(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = _config(tmp_path)
        transport = _make_mock_transport({
            "AAPL": [_bar("2026-01-02", 104.0), _bar("2026-01-03", 107.0)],
        })
        _install_mock_client(monkeypatch, transport)

        loader = DataLoader(config=cfg)
        result = loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-04", interval="1D")

        assert "AAPL.US" in result
        df = result["AAPL.US"]
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) == 2
        assert df["close"].iloc[-1] == 107.0
        # Cache file should now exist
        assert cfg.db_path.exists()

    def test_second_fetch_is_cache_hit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = _config(tmp_path)
        transport = _make_mock_transport({
            "AAPL": [_bar("2026-01-02", 104.0)],
        })
        clients = _install_mock_client(monkeypatch, transport)

        loader = DataLoader(config=cfg)
        loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-04", interval="1D")
        first_call_count = len(clients)

        # Second fetch: should be served entirely from cache, no new client.
        result2 = loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-04", interval="1D")

        assert "AAPL.US" in result2
        assert len(clients) == first_call_count  # no new HTTP client constructed

    def test_multiple_symbols_in_one_fetch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = _config(tmp_path)
        transport = _make_mock_transport({
            "AAPL": [_bar("2026-01-02", 104.0)],
            "MSFT": [_bar("2026-01-02", 305.0)],
        })
        _install_mock_client(monkeypatch, transport)

        loader = DataLoader(config=cfg)
        result = loader.fetch(["AAPL.US", "MSFT.US"], "2026-01-01", "2026-01-04")

        assert set(result.keys()) == {"AAPL.US", "MSFT.US"}
        assert result["AAPL.US"]["close"].iloc[0] == 104.0
        assert result["MSFT.US"]["close"].iloc[0] == 305.0


class TestRegistryIntegration:
    def test_alpaca_is_first_in_us_equity_chain(self) -> None:
        from backtest.loaders.registry import FALLBACK_CHAINS, _ensure_registered

        _ensure_registered()
        assert FALLBACK_CHAINS["us_equity"][0] == "alpaca"


class TestCacheCoverage:
    """Regression: extending end_date must trigger a gap fetch, not return
    a stale frame just because the cache has *some* rows in the window.
    """

    def test_extended_end_date_triggers_gap_fetch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = _config(tmp_path)
        # The mock transport will look up bars by date range on each request,
        # which lets us assert both the initial fetch and the gap fetch arrive.
        calls: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            calls.append(params)
            start_iso = params.get("start", "")
            # Day-1 fetch covers Jan 2-4; Day-2 fetch starts AT/AFTER Jan 5.
            start_day = int(start_iso[8:10]) if start_iso else 0
            bars_by_day = {
                2: _bar("2026-01-02", 100.0),
                3: _bar("2026-01-03", 101.0),
                4: _bar("2026-01-04", 102.0),
                5: _bar("2026-01-05", 103.0),
            }
            included = [b for d, b in bars_by_day.items() if d >= start_day and d <= 5]
            # Trim to the requested end too.
            end_iso = params.get("end", "")
            end_day = int(end_iso[8:10]) if end_iso else 31
            included = [b for d, b in bars_by_day.items()
                        if d >= start_day and d <= min(end_day, 5)]
            return httpx.Response(200, json={
                "bars": {"AAPL": included},
                "next_page_token": None,
            })

        transport = httpx.MockTransport(handler)
        _install_mock_client(monkeypatch, transport)

        loader = DataLoader(config=cfg)

        # Day 1: pull 1/1 .. 1/4 → 3 bars.
        first = loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-04", interval="1D")
        assert len(first["AAPL.US"]) == 3
        first_call_count = len(calls)

        # Day 2: pull 1/1 .. 1/5 → must now have 4 bars including 1/5,
        # and must have made an additional REST call for the gap.
        second = loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-05", interval="1D")
        assert len(second["AAPL.US"]) == 4, (
            "loader returned a stale cached frame; gap fetch did not happen"
        )
        assert second["AAPL.US"]["close"].iloc[-1] == 103.0
        assert len(calls) > first_call_count, (
            "expected an additional REST call to fill the cache gap"
        )

    def test_same_window_replay_is_cache_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Replaying the same window must not re-hit the REST API."""
        cfg = _config(tmp_path)
        calls: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(dict(request.url.params))
            return httpx.Response(200, json={
                "bars": {"AAPL": [_bar("2026-01-02", 100.0), _bar("2026-01-03", 101.0)]},
                "next_page_token": None,
            })

        _install_mock_client(monkeypatch, httpx.MockTransport(handler))
        loader = DataLoader(config=cfg)

        # Push end_date well into the past so the coverage check is unambiguous.
        loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-03", interval="1D")
        n1 = len(calls)
        loader.fetch(["AAPL.US"], "2026-01-01", "2026-01-03", interval="1D")
        assert len(calls) == n1, "second identical fetch should be cache-only"
