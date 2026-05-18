"""Tests that the four new ai-quant-lab integration tools register cleanly.

Auto-discovery via BaseTool.__subclasses__() picks them up if their files import
cleanly. We don't invoke them (the critique/research_loop tools call Claude),
we just verify registration + schema shape.
"""

from __future__ import annotations

import pytest

pytest.importorskip("ai_quant_lab.orchestrator.gates")

from src.tools import build_registry  # noqa: E402


EXPECTED_TOOLS = {"critique", "validate_run", "leakage_scan", "research_loop"}


def test_new_tools_are_registered() -> None:
    registry = build_registry()
    missing = EXPECTED_TOOLS - set(registry.tool_names)
    assert missing == set(), f"Missing tools: {missing}"


def test_tool_schemas_are_openai_compatible() -> None:
    registry = build_registry()
    defs = registry.get_definitions()
    for tool_name in EXPECTED_TOOLS:
        defn = next((d for d in defs if d["function"]["name"] == tool_name), None)
        assert defn is not None, f"No OpenAI schema for {tool_name}"
        params = defn["function"]["parameters"]
        assert params["type"] == "object"
        assert "properties" in params


def test_backtest_tool_accepts_critic_verdict_param() -> None:
    """The existing backtest tool gains an optional critic_verdict parameter."""
    registry = build_registry()
    tool = registry.get("backtest")
    assert tool is not None
    props = tool.parameters["properties"]
    assert "critic_verdict" in props
    assert "critic_verdict" not in tool.parameters.get("required", [])
