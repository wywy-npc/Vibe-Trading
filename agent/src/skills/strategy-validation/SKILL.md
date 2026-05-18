---
name: strategy-validation
description: Read and interpret gates.json output from ai-quant-lab. Covers Deflated Sharpe / correlation / PCA / leakage gates. Use when reporting on a backtest result, deciding whether to trust a Sharpe figure, or debugging why a strategy was rejected.
category: validation
---

# Strategy Validation

## When to use

- Any time you report a backtest result to the user — read `gates.json` first.
- When a strategy looks "too good" (Sharpe > 1.5 on novel data is the classic trap).
- When the user asks why a strategy was rejected.
- After `n_trials` has grown materially since a survivor was accepted — call `validate_run` to re-check.

## The `gates.json` schema

Every run emits `<run_dir>/gates.json`:

```json
{
  "passes": false,
  "rejection_reason": "deflated_sharpe_pvalue=0.61>=0.05",
  "n_trials_at_gate": 47,
  "critic_verdict": {"passes": true, "reasoning": "...", "kill_reasons": []},
  "dsr": {"sharpe": 1.42, "deflated_sharpe": 0.31, "pvalue": 0.61},
  "max_correlation": 0.23,
  "pca_concentration": 0.42
}
```

## Gate-by-gate interpretation

### Critic gate

`critic_verdict.passes == false` means the adversarial reviewer flagged a structural problem before the backtest even ran. The `kill_reasons` list maps to market-specific failure modes (factor crowding, decimalization, funding flips, roll yield, pin risk, carry tail). **Do not** try to fix the strategy by re-running with the same idea — read the kill reasons and propose a different hypothesis.

### Deflated Sharpe (`dsr`)

The hard gate. `pvalue < 0.05` is required. Interpretation:
- `sharpe` is the raw, naive figure.
- `deflated_sharpe` deflates it by the number of trials honestly attempted (`n_trials_at_gate`).
- `pvalue` is the probability you'd see this Sharpe by chance given that many trials.

**A Sharpe of 1.4 with a DSR p-value of 0.6 is noise**, not a strategy. The classic multiple-testing trap. If the user objects, point them at ai-quant-lab's `examples/05_deflated_sharpe_demo.py` — the best of 1000 random strategies on GBM has expected Sharpe ≈ 1.5 with p ≈ 0.6.

### Correlation gate

`max_correlation` is the maximum |corr| between this candidate's returns and any already-accepted survivor's returns. Above the threshold (default 0.6) means the candidate is too similar to something we already have — the survivor set should be diversified.

### PCA concentration gate

`pca_concentration` catches "stealthy" duplication: pairwise correlation is OK but the candidate loads on the same principal component as the survivor set. Above the threshold (default 0.5) → reject. This catches the case where five "different" momentum strategies are really one factor wearing five hats.

## How to report a result

When `passes == true`:
- Report Sharpe, drawdown, DSR p-value, and `n_trials_at_gate` together.
- "Sharpe 0.9, DSR p=0.02 across 47 trials" is honest. "Sharpe 0.9" alone hides the trial count.

When `passes == false`:
- Lead with the `rejection_reason`. The user wants to know which gate killed it.
- Don't sugarcoat. The system is designed to kill noise.
- If the user pushes to override, **don't**. The gates have no override path by design.

## When to call `validate_run` or `leakage_scan`

- **`validate_run`** — after `n_trials` grows substantially (e.g. several runs later, more survivors accepted). Re-checks the candidate against current state without re-running the engine. **Strict by default**: only operates on runs produced by `research_loop` (see the `not_loop_gated` error below). Pass `allow_non_loop=true` for analyst re-checks of ad-hoc `backtest` runs.
- **`leakage_scan`** — when a backtest Sharpe looks suspiciously high (≥1.5 on novel data with low n_trials). Checks position-vs-future-return correlation. Catches the centered-rolling and forgotten-`.shift(1)` bugs that hide inside otherwise-clean code.

## Hard-gate invariant: the `not_loop_gated` error

`validate_run` returns:

```json
{"status": "error", "code": "not_loop_gated", "via": "manual", "loop_run_id": null, ...}
```

…when the target `run_dir` has no `loop_run_id` in its `config.json` — i.e. the run was produced by `backtest` (manual coding path) or an unknown origin, not by `research_loop`. This is by design: the deflated-Sharpe / correlation / PCA gates are only meaningful when the trial-and-decision order is Python-controlled. Re-running gates on a manually-stitched workflow doesn't recover that invariant.

What to do when you see it:
- **Default**: re-run the same idea through `research_loop`. The hard-gated path is the trustworthy result.
- **Analyst escape hatch** (use sparingly): pass `allow_non_loop=true`. The returned `gates.json` will be stamped with `allow_non_loop_override=true` so the audit trail is preserved.
- **Don't** chain `critique` → `backtest` → `validate_run` and treat the output as loop-gated. It isn't; the `via` field in `config.json` will read `manual` regardless of how the prose around it reads.

## Common interpretation mistakes

- **Treating `sharpe` as the answer.** The deflated figure is the answer when `n_trials > 1`.
- **Re-running until something passes.** Every run inflates `n_trials`, making the next DSR check stricter. The gate is anti-cheat by design.
- **Lowering `cost_bps` or shortening the date range to make a strategy pass.** Friction and regime coverage are the substance, not nuisance parameters.
- **Ignoring `pca_concentration`** when `max_correlation` looks fine. The PCA gate catches what pairwise misses.

## Related skills

- [[strategy-discovery]] — running the research loop.
- [[adversarial-critic]] — calling the critic on a single hypothesis.
