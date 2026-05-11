"""TrustLayerBuilder: incrementally assembles a ResearchArtifact during an agent run.

Two passes:
  1. Passive — on_tool_result() is called after every tool execution and
     extracts data sources, strategy code hashes, and validation results
     without any model cooperation.
  2. Active — merge_structured() is called when the model invokes the
     structure_research tool to fill in hypothesis, assumptions, evidence,
     and failure modes explicitly.

finalize() writes trust_layer.json to the run directory.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from src.trust_layer.extractor import (
    extract_source,
    extract_validation_from_csv,
    hash_code,
)
from src.trust_layer.models import (
    Assumption,
    Evidence,
    FailureMode,
    ResearchArtifact,
)

logger = logging.getLogger(__name__)

_SOURCE_TOOLS = {"web_search", "web_reader", "read_url", "read_document", "read_file"}


class TrustLayerBuilder:
    """Builds a ResearchArtifact passively during a run, merged with active model input."""

    def __init__(self, run_id: str, run_dir: Path, session_id: str = "") -> None:
        self._artifact = ResearchArtifact(
            run_id=run_id,
            session_id=session_id,
            trace_path=str(run_dir / "trace.jsonl"),
        )
        self._run_dir = run_dir
        self._code_hash: str = ""

    @property
    def artifact(self) -> ResearchArtifact:
        return self._artifact

    def on_tool_result(self, tool_name: str, args: dict, result: str) -> None:
        """Passive extraction: called after every tool execution in the agent loop."""

        # --- Data sources ---
        if tool_name in _SOURCE_TOOLS:
            source = extract_source(tool_name, args, result)
            if source:
                self._artifact.data_sources.append(source)

        # --- Strategy code hash ---
        # Capture the hash whenever the model writes a signal_engine.py so that
        # any subsequent backtest validation is pinned to that exact code version.
        if tool_name == "write_file":
            path_arg = str(args.get("path", args.get("file_path", "")))
            if "signal_engine.py" in path_arg:
                content = args.get("content", "")
                self._code_hash = hash_code(content)
                self._artifact.strategy_code_path = path_arg
                self._artifact.strategy_code_hash = self._code_hash
                if self._artifact.hypothesis_status == "proposed":
                    self._artifact.hypothesis_status = "testing"

        # --- Validation results from backtest ---
        if tool_name == "backtest":
            # The backtest tool returns a run_dir in its result; prefer that
            # over self._run_dir so that multi-run sessions pick up the right CSV.
            target_dir = self._run_dir
            try:
                data = json.loads(result)
                returned_run_dir = data.get("run_dir", "")
                if returned_run_dir:
                    target_dir = Path(returned_run_dir)
            except (json.JSONDecodeError, TypeError):
                pass

            csv_path = target_dir / "artifacts" / "metrics.csv"
            validation = extract_validation_from_csv(
                self._artifact.run_id, self._code_hash, csv_path
            )
            if validation:
                # Replace any prior result for the same run_id; append new ones.
                self._artifact.validation_results = [
                    v for v in self._artifact.validation_results
                    if v.run_id != validation.run_id
                ] + [validation]

                if validation.passed and self._artifact.hypothesis_status == "testing":
                    self._artifact.hypothesis_status = "validated"

        self._artifact.updated_at = time.time()

    def merge_structured(self, structured: dict) -> None:
        """Merge explicit model-supplied provenance into the artifact.

        Called from the structure_research tool. Appends (does not replace)
        assumptions, evidence, and failure_modes so passive + active data
        coexist in the same artifact.
        """
        a = self._artifact

        if structured.get("hypothesis"):
            a.hypothesis = structured["hypothesis"]

        for raw in structured.get("assumptions", []):
            a.assumptions.append(Assumption(
                statement=raw.get("statement", ""),
                basis=raw.get("basis", ""),
                invalidation_trigger=raw.get("invalidation_trigger", ""),
            ))

        for raw in structured.get("evidence", []):
            a.evidence.append(Evidence(
                claim=raw.get("claim", ""),
                source_tool=raw.get("source_tool", ""),
                source_ref=raw.get("source_ref", ""),
                polarity=raw.get("polarity", "neutral"),
                strength=raw.get("strength", "moderate"),
            ))

        for raw in structured.get("failure_modes", []):
            a.failure_modes.append(FailureMode(
                condition=raw.get("condition", ""),
                probability=raw.get("probability", "medium"),
                monitoring_signal=raw.get("monitoring_signal", ""),
            ))

        # An artifact is complete once the model has committed a hypothesis,
        # at least one assumption, and at least one failure mode.
        a.is_complete = bool(a.hypothesis and a.assumptions and a.failure_modes)
        a.updated_at = time.time()

    def finalize(self) -> Path:
        """Write trust_layer.json to the run directory and return the path."""
        self._artifact.updated_at = time.time()
        out_path = self._run_dir / "trust_layer.json"
        out_path.write_text(
            self._artifact.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info("Trust layer written: %s (complete=%s)", out_path, self._artifact.is_complete)
        return out_path
