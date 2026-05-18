"""Deterministic research loop: ai-quant-lab's Hypothesis→Critic→Code→Sandbox
→Backtest→Gates→Memory pipeline, wrapped as a single Vibe-Trading tool.

Why a single tool, not five: the hard-gate guarantee ("no override") only
works because Python — not the LLM — controls the order. If we exposed each
agent (HypothesisAgent, CriticAgent, CodeAgent) as separate tools, the chat
agent could short-circuit critic-kill verdicts. The point of wrapping the
whole loop is to keep that invariant intact.

This tool fetches price data through Vibe-Trading's loader registry, then
hands it to ai_quant_lab.orchestrator.loop.run_research_loop. Per-iteration
artifacts and the survivors list are written into the run_dir under
``agent/runs/<id>/`` so Web UI / MCP / CLI all see the same layout.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.tools.path_utils import safe_run_dir

try:
    import pandas as pd

    from ai_quant_lab.backtest import BacktestConfig
    from ai_quant_lab.orchestrator.loop import LoopConfig, run_research_loop
    from backtest.loaders.registry import LOADER_REGISTRY, _ensure_registered
    from backtest.research_memory import get_memory

    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


_VALID_MARKETS = {"equities", "crypto", "futures", "options", "fx", "generic"}


def _resolve_runs_root() -> Path:
    """`agent/runs/` next to this tool file. Created on first use."""
    return Path(__file__).resolve().parents[2] / "runs"


def _fetch_price_series(
    *, source: str, symbol: str, start_date: str, end_date: str, interval: str
) -> "pd.Series":
    """Pull a single-symbol close series via Vibe-Trading's loader registry."""
    _ensure_registered()
    LoaderCls = LOADER_REGISTRY.get(source)
    if LoaderCls is None:
        raise ValueError(
            f"Unknown data source {source!r}. Available: {sorted(LOADER_REGISTRY)}"
        )
    loader = LoaderCls()
    data_map = loader.fetch([symbol], start_date, end_date, interval=interval)
    if not data_map or symbol not in data_map:
        raise ValueError(f"No data fetched for {symbol!r} from {source}.")
    df = data_map[symbol]
    if "close" in df.columns:
        s = df["close"]
    elif "Close" in df.columns:
        s = df["Close"]
    else:
        raise ValueError(f"DataFrame for {symbol!r} has no 'close' column. Cols: {list(df.columns)}")
    s = s.astype(float).dropna()
    if isinstance(s.index, pd.DatetimeIndex) is False:
        s.index = pd.to_datetime(s.index)
    s.name = symbol
    return s


def _artifact_to_dict(artifact: Any) -> dict[str, Any]:
    """Coerce a LoopArtifact (or any dataclass) to JSON-safe dict."""
    if is_dataclass(artifact):
        d = asdict(artifact)
        # GateOutcome inside may have non-serializable critic_verdict etc.
        return _scrub_for_json(d)
    if hasattr(artifact, "__dict__"):
        return _scrub_for_json(dict(artifact.__dict__))
    return {"repr": repr(artifact)}


def _scrub_for_json(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _scrub_for_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_scrub_for_json(v) for v in o]
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    try:
        return float(o)
    except Exception:
        return repr(o)


class ResearchLoopTool(BaseTool):
    """Run ai-quant-lab's full deterministic strategy-discovery loop."""

    name = "research_loop"
    description = (
        "Run the full ai-quant-lab strategy-discovery loop: Hypothesis → Critic "
        "→ Code → Sandbox → vectorized backtest → Deflated-Sharpe / correlation "
        "/ PCA gates → memory. Hard-gated: 'no override.' Use this when the user "
        "asks to find, discover, or generate trading strategies. Returns the run "
        "directory plus the survivor list."
    )
    parameters = {
        "type": "object",
        "properties": {
            "market_description": {
                "type": "string",
                "description": "1-2 sentences describing the universe (e.g. 'Daily bars on SPY, 2014-2024').",
            },
            "market_type": {
                "type": "string",
                "enum": sorted(_VALID_MARKETS),
                "description": "Critic failure-mode template (equities/crypto/futures/options/fx/generic).",
            },
            "symbol": {
                "type": "string",
                "description": "Single Vibe-Trading code (e.g. 'SPY.US', 'BTC-USDT', '600519.SH'). The loop is single-instrument.",
            },
            "data_source": {
                "type": "string",
                "description": "Vibe-Trading loader id (tushare/yfinance/okx/akshare/ccxt). Match the symbol's market.",
            },
            "start_date": {"type": "string", "description": "YYYY-MM-DD."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD."},
            "interval": {"type": "string", "description": "Bar interval (default '1D').", "default": "1D"},
            "iterations": {"type": "integer", "description": "Max loop iterations (default 50).", "default": 50},
            "target_survivors": {
                "type": "integer",
                "description": "Stop early once this many strategies clear all gates (default 3).",
                "default": 3,
            },
            "cost_bps": {"type": "number", "description": "Per-trade transaction cost in bps.", "default": 8.0},
            "annualization": {
                "type": "integer",
                "description": "Bars per year for Sharpe annualization (default 252 for daily).",
                "default": 252,
            },
        },
        "required": [
            "market_description", "market_type", "symbol",
            "data_source", "start_date", "end_date",
        ],
    }
    repeatable = True
    is_readonly = False

    @classmethod
    def check_available(cls) -> bool:
        return _AVAILABLE

    def execute(self, **kwargs) -> str:
        market_type = kwargs.get("market_type", "generic")
        if market_type not in _VALID_MARKETS:
            return json.dumps({
                "status": "error",
                "error": f"market_type must be one of {sorted(_VALID_MARKETS)}",
            }, ensure_ascii=False)

        run_id = f"loop_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        runs_root = _resolve_runs_root()
        runs_root.mkdir(parents=True, exist_ok=True)
        run_dir = runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        try:
            price_series = _fetch_price_series(
                source=kwargs["data_source"],
                symbol=kwargs["symbol"],
                start_date=kwargs["start_date"],
                end_date=kwargs["end_date"],
                interval=kwargs.get("interval", "1D"),
            )
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "error": f"Data fetch failed: {exc}",
                "run_dir": str(run_dir),
            }, ensure_ascii=False)

        loop_run_id = uuid.uuid4().hex
        (run_dir / "config.json").write_text(json.dumps({
            "engine": "aql_research_loop",
            "via": "loop",
            "loop_run_id": loop_run_id,
            "source": kwargs["data_source"],
            "codes": [kwargs["symbol"]],
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "interval": kwargs.get("interval", "1D"),
            "market_description": kwargs["market_description"],
            "market_type": market_type,
            "iterations": int(kwargs.get("iterations", 50)),
            "target_survivors": int(kwargs.get("target_survivors", 3)),
            "cost_bps": float(kwargs.get("cost_bps", 8.0)),
            "annualization": int(kwargs.get("annualization", 252)),
        }, indent=2), encoding="utf-8")

        loop_config = LoopConfig(
            market_description=kwargs["market_description"],
            market_type=market_type,  # type: ignore[arg-type]
            iterations=int(kwargs.get("iterations", 50)),
            target_survivors=int(kwargs.get("target_survivors", 3)),
            backtest_config=BacktestConfig(
                cost_bps=float(kwargs.get("cost_bps", 8.0)),
                annualization=int(kwargs.get("annualization", 252)),
            ),
            annualization=int(kwargs.get("annualization", 252)),
        )

        log_lines: list[str] = []
        def _log(line: str) -> None:
            log_lines.append(line)

        try:
            with get_memory() as memory:
                artifacts, survivors = run_research_loop(
                    price_series,
                    loop_config,
                    memory=memory,
                    log=_log,
                )
                n_trials_after = memory.n_trials()
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "error": f"Loop failed: {exc}",
                "run_dir": str(run_dir),
                "log_tail": log_lines[-20:],
            }, ensure_ascii=False)

        artifacts_payload = [_artifact_to_dict(a) for a in artifacts]
        survivors_payload = [_artifact_to_dict(s) for s in survivors]

        (run_dir / "artifacts.json").write_text(
            json.dumps(artifacts_payload, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        (run_dir / "survivors.json").write_text(
            json.dumps(survivors_payload, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        (run_dir / "loop.log").write_text("\n".join(log_lines), encoding="utf-8")

        return json.dumps({
            "status": "ok",
            "run_dir": str(run_dir),
            "loop_run_id": loop_run_id,
            "iterations_completed": len(artifacts_payload),
            "survivors_count": len(survivors_payload),
            "n_trials": n_trials_after,
            "survivors": survivors_payload,
        }, ensure_ascii=False)
