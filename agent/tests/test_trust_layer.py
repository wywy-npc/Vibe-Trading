"""Tests for the Trust Layer: models, extractor, builder, store, and tool."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.trust_layer.models import (
    Assumption,
    DataSource,
    Evidence,
    FailureMode,
    PMDecision,
    ResearchArtifact,
    ValidationResult,
)
from src.trust_layer.extractor import (
    extract_source,
    extract_validation_from_csv,
    hash_code,
)
from src.trust_layer.builder import TrustLayerBuilder
from src.trust_layer.store import HypothesisStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_dir(tmp: Path) -> Path:
    """Create a minimal run directory structure."""
    (tmp / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp / "code").mkdir(exist_ok=True)
    (tmp / "trust_layer").mkdir(exist_ok=True)
    return tmp


def _write_metrics(run_dir: Path, sharpe: float = 1.2, drawdown: float = -0.08,
                   win_rate: float = 0.54, trade_count: int = 42) -> None:
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts" / "metrics.csv").write_text(
        f"sharpe,max_drawdown,win_rate,trade_count\n{sharpe},{drawdown},{win_rate},{trade_count}\n"
    )


# ---------------------------------------------------------------------------
# models.py
# ---------------------------------------------------------------------------


class TestResearchArtifactDefaults:
    def test_artifact_id_auto_generated(self) -> None:
        a = ResearchArtifact(run_id="run1")
        assert len(a.artifact_id) == 32

    def test_two_artifacts_have_different_ids(self) -> None:
        a1 = ResearchArtifact(run_id="run1")
        a2 = ResearchArtifact(run_id="run1")
        assert a1.artifact_id != a2.artifact_id

    def test_default_status_is_proposed(self) -> None:
        a = ResearchArtifact(run_id="run1")
        assert a.hypothesis_status == "proposed"

    def test_is_complete_defaults_false(self) -> None:
        a = ResearchArtifact(run_id="run1")
        assert a.is_complete is False

    def test_lists_default_empty(self) -> None:
        a = ResearchArtifact(run_id="run1")
        assert a.data_sources == []
        assert a.assumptions == []
        assert a.evidence == []
        assert a.validation_results == []
        assert a.failure_modes == []

    def test_json_round_trip(self) -> None:
        a = ResearchArtifact(
            run_id="run42",
            hypothesis="Test hypothesis",
            hypothesis_status="testing",
        )
        restored = ResearchArtifact.model_validate_json(a.model_dump_json())
        assert restored.run_id == "run42"
        assert restored.hypothesis == "Test hypothesis"
        assert restored.hypothesis_status == "testing"


class TestAssumptionModel:
    def test_required_statement(self) -> None:
        a = Assumption(statement="Market is trending")
        assert a.statement == "Market is trending"
        assert a.basis == ""
        assert a.invalidation_trigger == ""

    def test_full_fields(self) -> None:
        a = Assumption(
            statement="Low volatility regime",
            basis="VIX < 20 for 30 days",
            invalidation_trigger="VIX > 25 for 5+ days",
        )
        assert a.invalidation_trigger == "VIX > 25 for 5+ days"


class TestEvidenceModel:
    def test_defaults(self) -> None:
        e = Evidence(claim="Momentum persists")
        assert e.polarity == "neutral"
        assert e.strength == "moderate"

    def test_polarity_values(self) -> None:
        for p in ("supporting", "contradicting", "neutral"):
            e = Evidence(claim="test", polarity=p)
            assert e.polarity == p

    def test_invalid_polarity_raises(self) -> None:
        with pytest.raises(Exception):
            Evidence(claim="test", polarity="unknown")


class TestValidationResult:
    def test_passed_flag(self) -> None:
        v = ValidationResult(run_id="r1", sharpe=1.3, passed=True)
        assert v.passed is True

    def test_optional_fields(self) -> None:
        v = ValidationResult(run_id="r1")
        assert v.sharpe is None
        assert v.max_drawdown is None


# ---------------------------------------------------------------------------
# extractor.py
# ---------------------------------------------------------------------------


class TestExtractSource:
    def test_web_search(self) -> None:
        src = extract_source("web_search", {"query": "AAPL momentum"}, "results here...")
        assert src is not None
        assert src.tool == "web_search"
        assert src.query_or_path == "AAPL momentum"
        assert src.snippet == "results here..."

    def test_web_reader(self) -> None:
        src = extract_source("web_reader", {"url": "https://example.com"}, "page content")
        assert src is not None
        assert src.url == "https://example.com"
        assert src.query_or_path == "https://example.com"

    def test_read_document(self) -> None:
        src = extract_source("read_document", {"path": "/data/report.pdf"}, "doc content")
        assert src is not None
        assert src.query_or_path == "/data/report.pdf"

    def test_read_file(self) -> None:
        src = extract_source("read_file", {"file_path": "/tmp/data.csv"}, "csv content")
        assert src is not None
        assert src.query_or_path == "/tmp/data.csv"

    def test_non_source_tool_returns_none(self) -> None:
        assert extract_source("backtest", {}, "{}") is None
        assert extract_source("write_file", {"path": "x.py"}, "ok") is None

    def test_web_search_missing_query_returns_none(self) -> None:
        assert extract_source("web_search", {}, "results") is None

    def test_snippet_truncated_to_500(self) -> None:
        long_result = "x" * 1000
        src = extract_source("web_search", {"query": "test"}, long_result)
        assert len(src.snippet) == 500


class TestExtractValidationFromCsv:
    def test_parses_standard_csv(self, tmp_path: Path) -> None:
        _write_metrics(tmp_path)
        v = extract_validation_from_csv("run1", "abc123", tmp_path / "artifacts" / "metrics.csv")
        assert v is not None
        assert v.sharpe == pytest.approx(1.2)
        assert v.max_drawdown == pytest.approx(-0.08)
        assert v.win_rate == pytest.approx(0.54)
        assert v.trade_count == 42
        assert v.run_id == "run1"
        assert v.strategy_code_hash == "abc123"

    def test_passed_when_sharpe_above_threshold(self, tmp_path: Path) -> None:
        _write_metrics(tmp_path, sharpe=1.5)
        v = extract_validation_from_csv("r", "", tmp_path / "artifacts" / "metrics.csv")
        assert v.passed is True

    def test_not_passed_when_sharpe_below_threshold(self, tmp_path: Path) -> None:
        _write_metrics(tmp_path, sharpe=0.3)
        v = extract_validation_from_csv("r", "", tmp_path / "artifacts" / "metrics.csv")
        assert v.passed is False

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        v = extract_validation_from_csv("r", "", tmp_path / "no_file.csv")
        assert v is None

    def test_empty_csv_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "empty.csv").write_text("")
        v = extract_validation_from_csv("r", "", tmp_path / "empty.csv")
        assert v is None


class TestHashCode:
    def test_returns_16_char_hex(self) -> None:
        h = hash_code("class SignalEngine: pass")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_content_same_hash(self) -> None:
        assert hash_code("abc") == hash_code("abc")

    def test_different_content_different_hash(self) -> None:
        assert hash_code("abc") != hash_code("def")


# ---------------------------------------------------------------------------
# builder.py
# ---------------------------------------------------------------------------


class TestTrustLayerBuilderPassive:
    def test_web_search_adds_source(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.on_tool_result("web_search", {"query": "momentum AAPL"}, "some results")
        assert len(b.artifact.data_sources) == 1
        assert b.artifact.data_sources[0].tool == "web_search"

    def test_multiple_sources_accumulate(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.on_tool_result("web_search", {"query": "q1"}, "r1")
        b.on_tool_result("web_reader", {"url": "https://x.com"}, "r2")
        b.on_tool_result("read_document", {"path": "doc.pdf"}, "r3")
        assert len(b.artifact.data_sources) == 3

    def test_write_file_signal_engine_captures_hash(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.on_tool_result("write_file", {"path": "code/signal_engine.py", "content": "class SE: pass"}, '{"status":"ok"}')
        assert b.artifact.strategy_code_hash is not None
        assert len(b.artifact.strategy_code_hash) == 16

    def test_write_file_non_signal_engine_ignored(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.on_tool_result("write_file", {"path": "config.json", "content": "{}"}, '{"status":"ok"}')
        assert b.artifact.strategy_code_hash is None

    def test_status_moves_to_testing_after_code_write(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        assert b.artifact.hypothesis_status == "proposed"
        b.on_tool_result("write_file", {"path": "code/signal_engine.py", "content": "x"}, '{"status":"ok"}')
        assert b.artifact.hypothesis_status == "testing"

    def test_backtest_reads_metrics_csv(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        _write_metrics(tmp_path, sharpe=1.4)
        b = TrustLayerBuilder("run1", tmp_path)
        b.on_tool_result("write_file", {"path": "code/signal_engine.py", "content": "x"}, '{"status":"ok"}')
        b.on_tool_result("backtest", {}, json.dumps({"status": "ok", "run_dir": str(tmp_path)}))
        assert len(b.artifact.validation_results) == 1
        assert b.artifact.validation_results[0].sharpe == pytest.approx(1.4)

    def test_passing_backtest_moves_status_to_validated(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        _write_metrics(tmp_path, sharpe=1.1)
        b = TrustLayerBuilder("run1", tmp_path)
        b.on_tool_result("write_file", {"path": "code/signal_engine.py", "content": "x"}, '{"status":"ok"}')
        b.on_tool_result("backtest", {}, json.dumps({"status": "ok", "run_dir": str(tmp_path)}))
        assert b.artifact.hypothesis_status == "validated"

    def test_failing_backtest_does_not_validate(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        _write_metrics(tmp_path, sharpe=0.2)
        b = TrustLayerBuilder("run1", tmp_path)
        b.on_tool_result("write_file", {"path": "code/signal_engine.py", "content": "x"}, '{"status":"ok"}')
        b.on_tool_result("backtest", {}, json.dumps({"status": "ok", "run_dir": str(tmp_path)}))
        assert b.artifact.hypothesis_status == "testing"

    def test_backtest_deduplicates_same_run_id(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        _write_metrics(tmp_path, sharpe=1.1)
        b = TrustLayerBuilder("run1", tmp_path)
        b.on_tool_result("backtest", {}, json.dumps({"status": "ok", "run_dir": str(tmp_path)}))
        b.on_tool_result("backtest", {}, json.dumps({"status": "ok", "run_dir": str(tmp_path)}))
        assert len(b.artifact.validation_results) == 1

    def test_non_source_tool_does_not_add_source(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.on_tool_result("remember", {"action": "save"}, '{"status":"ok"}')
        assert len(b.artifact.data_sources) == 0


class TestTrustLayerBuilderMergeStructured:
    def test_hypothesis_set(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.merge_structured({"hypothesis": "AAPL momentum has positive expected return in trending regimes"})
        assert "AAPL" in b.artifact.hypothesis

    def test_assumptions_appended(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.merge_structured({"assumptions": [
            {"statement": "Regime is trending", "basis": "VIX < 20", "invalidation_trigger": "VIX > 25 for 5d"},
        ]})
        assert len(b.artifact.assumptions) == 1
        assert b.artifact.assumptions[0].invalidation_trigger == "VIX > 25 for 5d"

    def test_evidence_appended(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.merge_structured({"evidence": [
            {"claim": "Momentum persists", "source_tool": "web_search", "source_ref": "query", "polarity": "supporting", "strength": "strong"},
        ]})
        assert len(b.artifact.evidence) == 1
        assert b.artifact.evidence[0].polarity == "supporting"

    def test_failure_modes_appended(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.merge_structured({"failure_modes": [
            {"condition": "Factor goes flat", "probability": "medium", "monitoring_signal": "autocorr < 0.1"},
        ]})
        assert len(b.artifact.failure_modes) == 1

    def test_is_complete_when_hypothesis_assumptions_failure_modes_set(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.merge_structured({
            "hypothesis": "Signal X works in regime Y",
            "assumptions": [{"statement": "Regime is Y"}],
            "failure_modes": [{"condition": "Regime changes"}],
        })
        assert b.artifact.is_complete is True

    def test_not_complete_missing_failure_modes(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.merge_structured({
            "hypothesis": "Signal X works",
            "assumptions": [{"statement": "Market stable"}],
        })
        assert b.artifact.is_complete is False

    def test_merge_is_additive_not_replacing(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.merge_structured({"assumptions": [{"statement": "A1"}]})
        b.merge_structured({"assumptions": [{"statement": "A2"}]})
        assert len(b.artifact.assumptions) == 2


class TestTrustLayerBuilderFinalize:
    def test_writes_trust_layer_json(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.merge_structured({"hypothesis": "Test"})
        path = b.finalize()
        assert path.exists()
        assert path.name == "trust_layer.json"

    def test_json_is_valid_artifact(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.merge_structured({"hypothesis": "My hypothesis"})
        b.finalize()
        loaded = ResearchArtifact.model_validate_json(
            (tmp_path / "trust_layer.json").read_text()
        )
        assert loaded.hypothesis == "My hypothesis"
        assert loaded.run_id == "run1"

    def test_trace_path_set(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        b = TrustLayerBuilder("run1", tmp_path)
        b.finalize()
        loaded = ResearchArtifact.model_validate_json(
            (tmp_path / "trust_layer.json").read_text()
        )
        assert "trace.jsonl" in loaded.trace_path


class TestTrustLayerBuilderFullRun:
    """End-to-end: simulate a complete research + backtest session."""

    def test_full_passive_plus_active(self, tmp_path: Path) -> None:
        _make_run_dir(tmp_path)
        _write_metrics(tmp_path, sharpe=1.34, drawdown=-0.07, win_rate=0.55, trade_count=48)

        b = TrustLayerBuilder("full_run_001", tmp_path, session_id="sess_abc")

        # Passive: research sources
        b.on_tool_result("web_search", {"query": "AAPL momentum 2024"}, "Momentum persists in trending regimes...")
        b.on_tool_result("read_document", {"path": "filings/AAPL_10K.pdf"}, "Revenue grew 8%...")

        # Passive: strategy code
        b.on_tool_result("write_file", {"path": "code/signal_engine.py", "content": "class SignalEngine: pass"}, '{"status":"ok"}')

        # Passive: backtest result
        b.on_tool_result("backtest", {}, json.dumps({"status": "ok", "run_dir": str(tmp_path)}))

        # Active: model fills in epistemic layer
        b.merge_structured({
            "hypothesis": "20-day momentum on AAPL has Sharpe > 0.8 in low-volatility trending regimes (VIX < 20)",
            "assumptions": [
                {"statement": "Regime is trending", "basis": "VIX < 20 for 30 days", "invalidation_trigger": "VIX > 25 for 5+ consecutive days"},
                {"statement": "Relationship is stationary", "basis": "3-year rolling correlation stable", "invalidation_trigger": "rolling correlation drops below 0.3"},
            ],
            "evidence": [
                {"claim": "Momentum persists in trending regimes", "source_tool": "web_search", "source_ref": "AAPL momentum 2024", "polarity": "supporting", "strength": "moderate"},
            ],
            "failure_modes": [
                {"condition": "Momentum factor flat for 60+ consecutive days", "probability": "medium", "monitoring_signal": "20d return autocorrelation < 0.1"},
                {"condition": "Regime shifts to mean-reverting", "probability": "medium", "monitoring_signal": "VIX spike above 30"},
            ],
        })

        b.finalize()
        a = b.artifact

        assert a.hypothesis_status == "validated"
        assert a.is_complete is True
        assert len(a.data_sources) == 2
        assert len(a.assumptions) == 2
        assert len(a.evidence) == 1
        assert len(a.validation_results) == 1
        assert len(a.failure_modes) == 2
        assert a.validation_results[0].sharpe == pytest.approx(1.34)
        assert a.strategy_code_hash is not None
        assert a.session_id == "sess_abc"


# ---------------------------------------------------------------------------
# store.py
# ---------------------------------------------------------------------------


class TestHypothesisStore:
    def test_save_and_get(self, tmp_path: Path) -> None:
        store = HypothesisStore(store_dir=tmp_path)
        a = ResearchArtifact(run_id="run1", hypothesis="Test hypothesis")
        store.save(a)
        loaded = store.get(a.artifact_id)
        assert loaded is not None
        assert loaded.hypothesis == "Test hypothesis"

    def test_get_missing_returns_none(self, tmp_path: Path) -> None:
        store = HypothesisStore(store_dir=tmp_path)
        assert store.get("nonexistent_id") is None

    def test_index_updated_on_save(self, tmp_path: Path) -> None:
        store = HypothesisStore(store_dir=tmp_path)
        a = ResearchArtifact(run_id="run1", hypothesis="H1")
        store.save(a)
        index_path = tmp_path / "index.json"
        assert index_path.exists()
        index = json.loads(index_path.read_text())
        assert a.artifact_id in index
        assert index[a.artifact_id]["run_id"] == "run1"

    def test_version_increments_on_update(self, tmp_path: Path) -> None:
        store = HypothesisStore(store_dir=tmp_path)
        a = ResearchArtifact(run_id="run1")
        store.save(a)
        a2 = a.model_copy(update={"hypothesis": "Updated"})
        store.save(a2)
        loaded = store.get(a.artifact_id)
        assert loaded.version == 2

    def test_old_version_archived(self, tmp_path: Path) -> None:
        store = HypothesisStore(store_dir=tmp_path)
        a = ResearchArtifact(run_id="run1", hypothesis="V1")
        store.save(a)
        a2 = a.model_copy(update={"hypothesis": "V2"})
        store.save(a2)
        archive = tmp_path / f"{a.artifact_id}_v1.json"
        assert archive.exists()
        old = ResearchArtifact.model_validate_json(archive.read_text())
        assert old.hypothesis == "V1"

    def test_list_by_status(self, tmp_path: Path) -> None:
        store = HypothesisStore(store_dir=tmp_path)
        a1 = ResearchArtifact(run_id="r1", hypothesis_status="validated")
        a2 = ResearchArtifact(run_id="r2", hypothesis_status="proposed")
        a3 = ResearchArtifact(run_id="r3", hypothesis_status="validated")
        store.save(a1)
        store.save(a2)
        store.save(a3)
        validated = store.list_by_status("validated")
        assert len(validated) == 2

    def test_list_all_sorted_by_updated_at(self, tmp_path: Path) -> None:
        store = HypothesisStore(store_dir=tmp_path)
        import time
        a1 = ResearchArtifact(run_id="r1")
        store.save(a1)
        time.sleep(0.01)
        a2 = ResearchArtifact(run_id="r2")
        store.save(a2)
        all_entries = store.list_all()
        assert all_entries[0]["run_id"] == "r2"

    def test_get_for_run(self, tmp_path: Path) -> None:
        store = HypothesisStore(store_dir=tmp_path)
        a = ResearchArtifact(run_id="specific_run")
        store.save(a)
        found = store.get_for_run("specific_run")
        assert found is not None
        assert found.run_id == "specific_run"

    def test_get_for_run_missing_returns_none(self, tmp_path: Path) -> None:
        store = HypothesisStore(store_dir=tmp_path)
        assert store.get_for_run("no_such_run") is None

    def test_record_pm_decision_approved(self, tmp_path: Path) -> None:
        store = HypothesisStore(store_dir=tmp_path)
        a = ResearchArtifact(run_id="r1", hypothesis_status="validated")
        store.save(a)
        decision = PMDecision(decision="approved", rationale="Looks good")
        ok = store.record_pm_decision(a.artifact_id, decision)
        assert ok is True
        loaded = store.get(a.artifact_id)
        assert loaded.hypothesis_status == "live"
        assert loaded.pm_decision.decision == "approved"

    def test_record_pm_decision_rejected(self, tmp_path: Path) -> None:
        store = HypothesisStore(store_dir=tmp_path)
        a = ResearchArtifact(run_id="r1", hypothesis_status="validated")
        store.save(a)
        decision = PMDecision(decision="rejected", rationale="Too risky")
        store.record_pm_decision(a.artifact_id, decision)
        loaded = store.get(a.artifact_id)
        assert loaded.hypothesis_status == "invalidated"

    def test_record_pm_decision_needs_more_research(self, tmp_path: Path) -> None:
        store = HypothesisStore(store_dir=tmp_path)
        a = ResearchArtifact(run_id="r1", hypothesis_status="validated")
        store.save(a)
        decision = PMDecision(decision="needs_more_research", rationale="Need OOS test")
        store.record_pm_decision(a.artifact_id, decision)
        loaded = store.get(a.artifact_id)
        assert loaded.hypothesis_status == "proposed"

    def test_record_pm_decision_missing_artifact(self, tmp_path: Path) -> None:
        store = HypothesisStore(store_dir=tmp_path)
        decision = PMDecision(decision="approved")
        assert store.record_pm_decision("ghost_id", decision) is False


# ---------------------------------------------------------------------------
# trust_layer_tool.py (integration)
# ---------------------------------------------------------------------------


class TestTrustLayerTool:
    def _make_tool(self, tmp_path: Path):
        from src.tools.trust_layer_tool import TrustLayerTool, _store
        import src.tools.trust_layer_tool as tl_module
        # Redirect the module-level store to a temp dir
        tl_module._store = HypothesisStore(store_dir=tmp_path / "store")
        return TrustLayerTool()

    def test_structure_action_missing_run_id(self, tmp_path: Path) -> None:
        tool = self._make_tool(tmp_path)
        result = json.loads(tool.execute(action="structure"))
        assert result["status"] == "error"
        assert "run_id" in result["error"]

    def test_structure_creates_artifact(self, tmp_path: Path, monkeypatch) -> None:
        import src.agent.loop as loop_module
        monkeypatch.setattr(loop_module, "RUNS_DIR", tmp_path)
        run_dir = tmp_path / "test_run_007"
        _make_run_dir(run_dir)

        tool = self._make_tool(tmp_path)
        result = json.loads(tool.execute(
            action="structure",
            run_id="test_run_007",
            hypothesis="Signal A has positive expected return in regime B",
            assumptions=[{"statement": "Regime is B", "invalidation_trigger": "regime shifts"}],
            failure_modes=[{"condition": "Signal goes flat", "probability": "low"}],
        ))
        assert result["status"] == "ok"
        assert "artifact_id" in result
        assert result["is_complete"] is True
        assert (run_dir / "trust_layer.json").exists()

    def test_decide_missing_fields(self, tmp_path: Path) -> None:
        tool = self._make_tool(tmp_path)
        result = json.loads(tool.execute(action="decide"))
        assert result["status"] == "error"

    def test_decide_missing_artifact(self, tmp_path: Path) -> None:
        tool = self._make_tool(tmp_path)
        result = json.loads(tool.execute(action="decide", artifact_id="ghost", decision="approved"))
        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    def test_decide_approved_flow(self, tmp_path: Path, monkeypatch) -> None:
        import src.agent.loop as loop_module
        monkeypatch.setattr(loop_module, "RUNS_DIR", tmp_path)
        run_dir = tmp_path / "dec_run"
        _make_run_dir(run_dir)

        tool = self._make_tool(tmp_path)

        # First structure
        struct_result = json.loads(tool.execute(
            action="structure",
            run_id="dec_run",
            hypothesis="Hypothesis for PM review",
            assumptions=[{"statement": "Stable market"}],
            failure_modes=[{"condition": "Crash", "probability": "low"}],
        ))
        artifact_id = struct_result["artifact_id"]

        # Then PM decides
        decide_result = json.loads(tool.execute(
            action="decide",
            artifact_id=artifact_id,
            decision="approved",
            rationale="Looks solid",
            conditions=["Review in 30 days"],
        ))
        assert decide_result["status"] == "ok"
        assert decide_result["new_hypothesis_status"] == "live"

    def test_unknown_action(self, tmp_path: Path) -> None:
        tool = self._make_tool(tmp_path)
        result = json.loads(tool.execute(action="invalid"))
        assert result["status"] == "error"
