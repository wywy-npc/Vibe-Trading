---
name: live-deployment
description: Deploy a gate-approved strategy to paper or live trading. Covers the full workflow from research_loop survivor to paper deploy to HITL live promotion. Use when the user wants to run a strategy on a real (or paper) account.
category: deployment
---

# Live Deployment

## The deployment workflow

```
research_loop / backtest → gates.json passes=true → survivor in research_memory.db
        ↓
deploy_strategy (auto paper)
        ↓
paper trading runs via broker paper account
        ↓
monitor with list_live + portfolio_risk
        ↓
promote_to_live (HITL required)
        ↓
human approves: POST /live/{id}/promote/decide {"approved": true}
        ↓
live trading
```

**Paper is automatic. Live is never automatic.**

## When to call deploy_strategy

The user says:
- "Deploy this strategy" / "Run this in paper"
- "Start trading with this strategy"
- "Go live with the SPY momentum strategy"

Pre-conditions (the tool enforces these; call them out explicitly if needed):
1. `gates.json` exists and `passes=true` (run a backtest first if not)
2. The strategy is a survivor in `research_memory.db` (came from `research_loop`)

## Choosing broker + cadence

| Asset class | Broker | Cadence |
|---|---|---|
| US equities (SPY, AAPL, etc.) | alpaca | daily |
| Crypto (BTC, ETH, etc.) | alpaca | daily or intraday |
| All asset classes, international | ibkr | daily |
| Crypto 24/7 intraday | alpaca | intraday |
| Equity intraday | alpaca | intraday |

**IBKR requires TWS Gateway or IB Gateway running.** Ask the user to confirm their setup before deploying to ibkr.

## Risk parameters

Always specify:
- `max_drawdown_pct` — default 10%. Kill-switch fires if realized drawdown exceeds this.
- `daily_loss_pct` — default 2%. Kill-switch fires on a single day's loss.

Don't let the user set `max_drawdown_pct=100` to "disable" the kill-switch. That defeats the purpose.

## Remote deployment

If the strategy should run on AWS / EC2 rather than locally, call `deploy_to_server` after `deploy_strategy`:

1. `deploy_strategy(run_dir=..., broker=..., symbols=..., cadence=...)` — creates registry record + local subprocess
2. `deploy_to_server(deployment_id=..., host=..., key_path=...)` — pushes to remote + starts remote runner

Credentials via env: `VIBE_DEPLOY_HOST`, `VIBE_DEPLOY_USER`, `VIBE_DEPLOY_KEY`.

## Promoting to live

Call `promote_to_live` with:
- `deployment_id` — the paper deployment
- `rationale` — include: how many days paper ran, realized Sharpe, realized vs backtest Sharpe, any notable incidents

The tool updates state to `PENDING_APPROVAL`. Tell the user they must approve via:
```
POST /live/{deployment_id}/promote/decide {"approved": true}
```

**Do not skip this step.** Never claim a strategy is live without confirmed HITL approval.

## Anti-patterns

- **Don't deploy a strategy that hasn't passed gates.** Not even to paper. The gates exist to catch noise.
- **Don't set max_drawdown_pct=100.** That disables the kill-switch.
- **Don't call promote_to_live before the strategy has run on paper.** Minimum: 5 trading days; recommended: 20+.
- **Don't claim live deployment is done** without the human posting the approval decision.

## Related skills

- [[strategy-discovery]] — running research_loop to find strategies
- [[strategy-validation]] — reading gates.json
- [[live-monitoring]] — watching a deployed strategy
