"""Adversarial critic: pre-backtest review of a strategy hypothesis.

Wraps ai_quant_lab.agents.critic.CriticAgent. The critic is cheap (one Claude
call) and adversarial by design — bias is to kill. A pass doesn't mean the
strategy works; it means the idea is not laughable on its face.

The verdict is recorded as a TrialRecord so n_trials stays honest even when
no backtest follows. The verdict JSON can also be carried into the run_dir's
config.json so runner.py's post-engine hook threads it through evaluate_gates.
"""

from __future__ import annotations

import json
import uuid

from src.agent.tools import BaseTool

try:
    from ai_quant_lab.agents.critic import CriticAgent, MarketType
    from ai_quant_lab.agents.hypothesis import StrategyHypothesis
    from backtest.research_memory import get_memory, record_run_trial

    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


_VALID_MARKETS = {"equities", "crypto", "futures", "options", "fx", "generic"}


class CritiqueTool(BaseTool):
    """Adversarial review of a hypothesis before any backtest runs."""

    name = "critique"
    description = (
        "Adversarial pre-backtest review of a trading hypothesis. Returns a "
        "verdict (pass|kill) with reasoning. Bias is to kill — passing means "
        "the idea is not obviously broken, not that it works. Records a trial "
        "so the deflated-Sharpe gate's n_trials stays honest. Call this before "
        "writing strategy code outside of research_loop."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short one-line description of the strategy idea."},
            "rationale": {"type": "string", "description": "2-4 sentences explaining the market-microstructure reason this should work."},
            "spec": {"type": "string", "description": "Precise spec: signal, direction, holding period. Free text."},
            "market_type": {
                "type": "string",
                "enum": sorted(_VALID_MARKETS),
                "description": "Picks the failure-mode template the critic applies.",
            },
            "expected_sharpe_low": {"type": "number", "description": "Honest low end of expected Sharpe range."},
            "expected_sharpe_high": {"type": "number", "description": "Honest high end of expected Sharpe range."},
            "works_in_regime": {"type": "string", "description": "Regime where the edge should exist."},
            "breaks_in_regime": {"type": "string", "description": "Regime where the edge will die."},
        },
        "required": ["title", "rationale", "spec", "market_type"],
    }
    repeatable = True
    is_readonly = False

    @classmethod
    def check_available(cls) -> bool:
        return _AVAILABLE

    def execute(self, **kwargs) -> str:
        title = kwargs.get("title", "").strip()
        rationale = kwargs.get("rationale", "").strip()
        spec_text = kwargs.get("spec", "").strip()
        market_type = kwargs.get("market_type", "generic")
        if market_type not in _VALID_MARKETS:
            return json.dumps({"status": "error", "error": f"market_type must be one of {sorted(_VALID_MARKETS)}"})

        hypothesis = StrategyHypothesis(
            hypothesis_id=f"adhoc_{uuid.uuid4().hex[:8]}",
            title=title or "(untitled)",
            rationale=rationale or "(no rationale provided)",
            spec={"signal": spec_text},
            expected_sharpe_range=(
                float(kwargs.get("expected_sharpe_low", 0.3)),
                float(kwargs.get("expected_sharpe_high", 0.8)),
            ),
            works_in_regime=str(kwargs.get("works_in_regime", "")),
            breaks_in_regime=str(kwargs.get("breaks_in_regime", "")),
        )

        try:
            critic = CriticAgent(market_type=market_type)  # type: ignore[arg-type]
            verdict = critic.review(hypothesis)
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"Critic call failed: {exc}"})

        with get_memory() as memory:
            record_run_trial(
                memory,
                run_id=hypothesis.hypothesis_id,
                hypothesis_text=title,
                rationale=rationale,
                code="",
                metrics={},
                accepted=False,
                rejection_reason="critic_only" if verdict.passes else "critic_kill",
                returns=None,
            )
            n_trials_after = memory.n_trials()

        return json.dumps({
            "status": "ok",
            "hypothesis_id": hypothesis.hypothesis_id,
            "verdict": {
                "passes": bool(verdict.passes),
                "reasoning": verdict.reasoning,
                "kill_reasons": list(verdict.kill_reasons),
            },
            "market_type": market_type,
            "n_trials": n_trials_after,
            "note": (
                "Carry this verdict block into config.json under 'critic_verdict' so "
                "the runner threads it through evaluate_gates after backtest."
                if verdict.passes else
                "Verdict was kill — do not proceed to coding. Iterate on the idea."
            ),
        }, ensure_ascii=False)
