"""Passive extraction helpers: pull DataSource and ValidationResult from tool outputs.

These run automatically on every tool result — no model cooperation required.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from pathlib import Path
from typing import Optional

from src.trust_layer.models import DataSource, ValidationResult

logger = logging.getLogger(__name__)

_SOURCE_TOOLS = {"web_search", "web_reader", "read_url", "read_document", "read_file"}

# Minimum Sharpe for a validation to be considered passing
_PASS_SHARPE_THRESHOLD = 0.5


def extract_source(tool_name: str, args: dict, result: str) -> Optional[DataSource]:
    """Return a DataSource if this tool call represents an external information read."""
    snippet = result[:500] if isinstance(result, str) else ""

    if tool_name == "web_search":
        query = args.get("query", "")
        if not query:
            return None
        return DataSource(tool=tool_name, query_or_path=query, snippet=snippet)

    if tool_name in ("web_reader", "read_url"):
        url = args.get("url", "")
        return DataSource(tool=tool_name, query_or_path=url, url=url, snippet=snippet)

    if tool_name in ("read_document", "read_file"):
        path = args.get("path", args.get("file_path", ""))
        return DataSource(tool=tool_name, query_or_path=str(path), snippet=snippet)

    return None


def extract_validation_from_csv(
    run_id: str, code_hash: str, csv_path: Path
) -> Optional[ValidationResult]:
    """Parse artifacts/metrics.csv and return a ValidationResult."""
    if not csv_path.exists():
        return None
    try:
        text = csv_path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(text))
        row = next(reader, None)
        if not row:
            return None

        def _f(key: str) -> Optional[float]:
            val = row.get(key, "").strip()
            try:
                return float(val) if val else None
            except (ValueError, TypeError):
                return None

        def _i(key: str) -> Optional[int]:
            val = row.get(key, "").strip()
            try:
                return int(float(val)) if val else None
            except (ValueError, TypeError):
                return None

        sharpe = _f("sharpe") or _f("sharpe_ratio")
        data_range = row.get("data_range", row.get("start_date", "") + " – " + row.get("end_date", "")).strip(" –")
        return ValidationResult(
            run_id=run_id,
            strategy_code_hash=code_hash,
            data_range=data_range,
            sharpe=sharpe,
            max_drawdown=_f("max_drawdown"),
            win_rate=_f("win_rate"),
            trade_count=_i("trade_count"),
            passed=bool(sharpe and sharpe > _PASS_SHARPE_THRESHOLD),
        )
    except Exception as exc:
        logger.debug("metrics.csv parse failed: %s", exc)
        return None


def hash_code(content: str) -> str:
    """Compute a short SHA-256 hex digest of strategy code."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
