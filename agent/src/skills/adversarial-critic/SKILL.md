---
name: adversarial-critic
description: Run the ai-quant-lab adversarial critic on a single strategy hypothesis before writing any code. Use when the user describes a strategy idea you'd otherwise rush to code. The critic kills bad ideas cheaply, before they burn backtest cycles.
category: validation
---

# Adversarial Critic

## When to use

Before writing strategy code outside of `research_loop` (which has its own critic gate built in). Specifically:

- The user describes a strategy idea ("buy when RSI is oversold and the 50-day is below the 200-day…") and asks for a backtest.
- You're about to write a `signal_engine.py` from a chat description.
- The user proposes adding a factor or signal to an existing strategy.

The critic costs one Claude call. The backtest you'd skip costs minutes of engine time plus an inflated `n_trials` count. The asymmetry — generation cheap, validation expensive — is the whole reason this gate exists.

## What to do

Call the **`critique`** tool with a structured hypothesis:

| Field | Example |
|---|---|
| `title` | "Long top-decile 21-day return, hold 5 days, weekly rebalance" |
| `rationale` | "Cross-sectional momentum within a stable universe; literature shows 6-12 month momentum is real net of factor crowding in mid-caps." |
| `spec` | "Signal: rank 21-day return across universe at week close. Long top decile equal-weight, short bottom decile. Hold 5 trading days. Cost 10 bps round-trip." |
| `market_type` | One of `equities`, `crypto`, `futures`, `options`, `fx`, `generic` |
| `expected_sharpe_low` / `expected_sharpe_high` | Be honest. Literature says 0.4-0.8 for vanilla momentum; don't claim 2.0. |
| `works_in_regime` | "Trending regimes; positive cross-sectional dispersion." |
| `breaks_in_regime` | "Reversal regimes (March 2009, April 2020); periods of crowded factor unwind." |

## How to interpret the verdict

```json
{
  "verdict": {
    "passes": false,
    "reasoning": "...",
    "kill_reasons": ["forward-looking via top-decile rebalance timing", "post-2010 momentum decay"]
  }
}
```

**`passes == false` (kill)** → Do not proceed to coding. Iterate on the idea. Address the specific `kill_reasons`. Calling the critic again with a slightly reworded version of the same idea is cheating yourself — the trial counter logs both.

**`passes == true`** → The idea is not obviously broken. **This does not mean it works.** Proceed to coding, then carry the verdict block forward when calling `backtest`:

```python
backtest(run_dir="agent/runs/...", critic_verdict={
    "passes": true,
    "reasoning": "...",
    "kill_reasons": []
})
```

The runner's post-engine gate hook reads this verdict from `config.json` and threads it into `evaluate_gates` as the first gate. Without it, the statistical gates still fire but the critic gate is treated as a synthetic pass — slightly less rigorous.

## Why bias-to-kill

The critic's system prompt is biased toward rejection. That's deliberate. Claude's default mode is helpful-and-credulous; the critic is the antibody. A 30% kill rate at this gate is healthy. If everything passes, the critic isn't doing its job.

## Failure modes the critic looks for

- Implicit look-ahead / forward-looking data
- Survivorship or selection bias in the implied universe
- Already-arbitraged factors with no plausible reason they persist
- Single-parameter sensitivity (silently optimized over)
- Frictions that wouldn't survive realistic costs
- Market-specific traps: factor crowding (equities), funding flips (crypto), roll yield (futures), pin risk (options), carry tail (fx)

## Anti-patterns

- **Don't** skip the critic just because you're confident in the idea. The critic is cheap; your confidence is expensive when it's wrong.
- **Don't** soften the rationale or expected Sharpe to "help" the idea pass. The critic reads honest inputs; lying to it lies to you.
- **Don't** call the critic and then ignore a kill verdict. The trial counter doesn't forget.

## Related skills

- [[strategy-discovery]] — the full research loop, which embeds the critic.
- [[strategy-validation]] — interpreting gate output after a backtest.
