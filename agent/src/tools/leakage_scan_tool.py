"""Correlation-based look-ahead audit on a finished run's positions vs returns.

A clean signal should not correlate more strongly with future returns than
with past returns. ai-quant-lab's detect_leakage flags it when it does —
catches centered rolling windows, forgotten shifts, forward-as-feature.
"""

from __future__ import annotations

import json

from src.agent.tools import BaseTool
from src.tools.path_utils import safe_run_dir

try:
    from backtest import validation_aql as _validation_aql

    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


class LeakageScanTool(BaseTool):
    """Look-ahead-bias audit on a finished run."""

    name = "leakage_scan"
    description = (
        "Audit a finished run for look-ahead bias. Compares position correlation "
        "with future vs past returns. Catches centered rolling windows, forgotten "
        ".shift(1) calls, and forward-reference leaks. Returns structured findings."
    )
    parameters = {
        "type": "object",
        "properties": {
            "run_dir": {"type": "string", "description": "Path to a run directory with artifacts/positions.csv and equity.csv."},
            "future_horizon": {
                "type": "integer",
                "description": "Bars forward to compare against. Default 1 (next-bar return).",
            },
            "suspicious_future_correlation": {
                "type": "number",
                "description": "|future-correlation| above this independently flags a column. Default 0.20.",
            },
        },
        "required": ["run_dir"],
    }
    repeatable = True
    is_readonly = True

    @classmethod
    def check_available(cls) -> bool:
        return _AVAILABLE

    def execute(self, **kwargs) -> str:
        try:
            run_path = safe_run_dir(kwargs["run_dir"])
        except ValueError as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

        future_horizon = int(kwargs.get("future_horizon", 1))
        suspicious = float(kwargs.get("suspicious_future_correlation", 0.20))

        try:
            report = _validation_aql.leakage_scan(
                run_path,
                future_horizon=future_horizon,
                suspicious_future_correlation=suspicious,
            )
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"Leakage scan failed: {exc}"}, ensure_ascii=False)

        return json.dumps({
            "status": "ok",
            "run_dir": str(run_path),
            "report": _validation_aql.leakage_report_to_dict(report),
        }, ensure_ascii=False)
