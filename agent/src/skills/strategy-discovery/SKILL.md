---
name: strategy-discovery
description: Discover trading strategies through the ai-quant-lab research loop. Use when the user asks to find, generate, propose, or discover new strategies on a market. Invokes the `research_loop` tool — do not manually assemble hypothesis → critique → code steps.
category: research
---

# Strategy Discovery

## When to use

Trigger this skill when the user says any of:
- "Find / discover / generate / propose trading strategies"
- "What strategies work on X?"
- "Build me a backtested alpha on SYM"
- "Run a research loop on this market"
- "Hunt for edge in SYM"

## What to do

Call the **`research_loop`** tool. **Do not** manually call `critique` → `backtest` → `validate_run` in sequence and pretend that's strategy discovery — you'll break the hard-gate guarantee, because ai-quant-lab's gate sequence ("no override") only holds when its Python orchestrator controls the order. The tool is the orchestrator.

### Required arguments

| Arg | How to fill it |
|---|---|
| `market_description` | One or two sentences. Example: `"Daily bars on SPY (S&P 500 ETF), 10 years, US large-cap equity."` |
| `market_type` | One of `equities`, `crypto`, `futures`, `options`, `fx`, `generic`. Picks the adversarial-critic failure-mode template. |
| `symbol` | Single Vibe-Trading code: `SPY.US`, `BTC-USDT`, `600519.SH`, `IF2406.CFFEX`. The loop is single-instrument. |
| `data_source` | Match the market: `yfinance` for US/HK equity, `okx` for crypto, `tushare` for A-share, `akshare` for futures/forex. |
| `start_date` / `end_date` | YYYY-MM-DD. Use at least 5 years of daily bars for the DSR gate to have enough data. |

### Optional knobs

- `iterations` (default 50): max Claude calls before the loop stops.
- `target_survivors` (default 3): stop early once this many strategies pass every gate.
- `cost_bps` (default 8.0): be honest. Small-caps and illiquid markets need higher. Don't tune this down to make a strategy pass.
- `annualization` (default 252): bars per year. 252 for daily equity, 365 for daily crypto.

## What the tool returns

```json
{
  "status": "ok",
  "run_dir": "agent/runs/loop_1747XXXXXX_xxxxxx",
  "iterations_completed": 47,
  "survivors_count": 2,
  "n_trials": 47,
  "survivors": [{...trial records...}]
}
```

When `survivors_count < target_survivors`, that's the system being honest — most ideas don't pass. Don't try to "rescue" failed candidates by re-running with looser gates. Report the result as is and offer to widen the universe or re-run on a different market.

## Why a single tool, not five

ai-quant-lab is a deterministic Python pipeline, not a chat agent. Its Critic gate runs *before* code generation specifically so bad ideas don't burn tokens. If you decompose the loop into `hypothesize` → `critique` → `generate_code` → `backtest`, you let the chat agent re-order or skip gates. The `research_loop` tool preserves the invariant. Use it.

## Anti-patterns to avoid

- **Don't** synthesize a hypothesis yourself and call `backtest_tool` directly. That bypasses the critic and inflates `n_trials` off-record relative to the loop. Use `research_loop` or, for ad-hoc work, call `critique` first.
- **Don't** lower `cost_bps` to make a strategy pass. Friction kills 80% of paper edges — that's the point.
- **Don't** re-run with the same parameters until you get survivors. Every run adds to `n_trials`, which makes the Deflated Sharpe gate stricter, not looser. Honest counting is the whole anti-cheat.
- **Don't** present a non-survivor as "promising." It either passed the gates or it didn't.

## Related skills

- [[strategy-validation]] — how to read `gates.json` and interpret a result.
- [[adversarial-critic]] — for ad-hoc critique outside the loop.
