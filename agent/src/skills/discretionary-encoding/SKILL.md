---
name: discretionary-encoding
description: Convert a qualitative or discretionary trading thesis into a testable, systematic signal_engine.py hypothesis. Use when the user describes a strategy in natural language, based on intuition, macro views, or qualitative analysis rather than quant factors.
category: research
---

# Discretionary Strategy Encoding

## What this is

Discretionary strategies are based on judgment: "I buy NVDA when AI spending is accelerating" or "I go short when the yield curve inverts." These aren't naturally coded as formulas — but they can be *approximated* as rules and tested as systematized strategies.

The encoding process: human judgment → extractable rules → quantifiable signals → `research_loop`-compatible hypothesis.

## Step-by-step encoding

### 1. Extract the core rule

Ask: "What exactly triggers a buy/sell? What data would tell you to enter?"

| Discretionary view | Approximation |
|---|---|
| "Buy when AI spending is accelerating" | `Revenue growth YoY in top-5 semis > X%` |
| "Short when yield curve inverts" | `10Y-2Y spread < 0 for N consecutive days` |
| "Buy momentum stocks in bull market" | `Price > 200MA AND 63-day return > top-decile` |
| "Avoid crowded trades" | `Short-interest ratio > X% OR high put/call ratio` |
| "Buy after a panic sell-off" | `Price drops > Y% in Z days → long signal` |

Only use OHLCV data available in Vibe-Trading's loaders (no fundamentals, no alt data, no sentiment unless wired). If the thesis depends on data that doesn't exist, state that clearly and approximate.

### 2. Specify the regime and breaks

Every discretionary thesis has conditions:
- **Works in**: "trending markets / rising rates / post-panic"
- **Breaks in**: "choppy / mean-reverting / deflationary shock"

These become the `works_in_regime` and `breaks_in_regime` fields for the critic.

### 3. Build the hypothesis spec

```
Hypothesis: [one-line description]
Signal: [exact rule — which data, what threshold, what timeframe]
Direction: long / short / both
Holding period: N bars
Rebalance: weekly / daily / on-signal
Position sizing: equal-weight / signal-proportional
Expected Sharpe: 0.3-0.8 (be honest — discretionary edge is smaller when coded)
```

### 4. Call research_loop

Once you have a crisp spec, call `research_loop` with the encoded hypothesis as `market_description`. The loop will:
1. Feed the description to HypothesisAgent (which may refine it)
2. CriticAgent applies adversarial review
3. CodeAgent translates to `signal_engine.py`
4. Gates validate it

### 5. If research_loop kills it

Common kill reasons for discretionary encodings:
- **"Implicit lookahead"** — your proxy for "AI spending accelerating" uses forward returns. Find a purely lagged proxy.
- **"Already-arbitraged factor"** — the rule was mined by thousands of quants. Narrow the universe or add a timing filter.
- **"Parameter sensitivity"** — the threshold you picked was fit to the sample. Propose a range-based version.

Iterate: tighten the rule, widen the universe, or accept that this thesis doesn't survive systematic testing (and report that honestly).

## What NOT to do

- Don't make up data that isn't in the loaders. "Buy when CEO sentiment is positive" → approximation using price reaction to earnings, or drop the idea.
- Don't treat an encoded strategy as equivalent to the discretionary version. The code is a systematized *approximation* of the thesis, not the thesis itself.
- Don't lower `cost_bps` to help a discretionary idea pass gates. Friction applies equally.

## Example encoding

**User:** "I like buying MSFT after a big pullback in a bull market."

**Encoded hypothesis:**
```
Title: MSFT mean-reversion after drawdown in uptrend
Signal: MSFT price drops > 5% from 20-day high AND close > 200-day MA (uptrend filter)
Direction: Long only
Holding period: 10 bars (2 weeks)
Works in: Bull markets with momentum regime
Breaks in: Structural bear markets (200MA decaying)
Expected Sharpe: 0.4-0.7
```

**market_description for research_loop:**
"MSFT daily bars 2014-2024. Mean-reversion signal: long when price drops >5% from 20-day high AND close is above the 200-day MA. Hold 10 bars. Exit unconditionally."

## Related skills

- [[strategy-discovery]] — running the research loop
- [[adversarial-critic]] — critiquing a hypothesis before coding
- [[strategy-validation]] — reading gate results
