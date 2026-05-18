---
name: live-monitoring
description: Monitor running paper and live strategy deployments. Interpret list_live output, heartbeat age, PnL vs backtest, kill-switch status, and portfolio risk. Use when the user asks about running strategies or wants to check performance.
category: deployment
---

# Live Monitoring

## Reading list_live output

```json
{
  "deployment_id": "deploy_1747..._a3b2c1",
  "strategy_name": "SPY MA Cross",
  "state": "PAPER",
  "broker": "alpaca",
  "pnl_realized": 243.50,
  "n_trades": 12,
  "heartbeat_age_seconds": 45,
  "pid": 83421
}
```

| Field | What to look for |
|---|---|
| `state` | PAPER / LIVE / HALTED / PENDING_APPROVAL |
| `pnl_realized` | Raw dollar PnL (not %) — needs equity context to interpret |
| `heartbeat_age_seconds` | > 3600 (1 hour): runner may be stuck or dead |
| `pid` | If null: runner not started or remote deploy |

## When to investigate

- `state=HALTED` → check `rejection_reason` via `/live/{id}` endpoint. Common causes: drawdown breach, daily loss limit, or manual halt.
- `heartbeat_age_seconds > 3600` → the runner process may have crashed. Check logs.
- `pnl_realized` significantly negative vs backtest expected → run `validate_run` on the run_dir to check if gates still pass with current n_trials.

## Kill-switch meanings

| Rejection reason | What happened |
|---|---|
| `drawdown=0.12` | Realized drawdown exceeded max_drawdown_pct |
| `daily_loss=-0.03` | Single day loss exceeded daily_loss_pct |
| `kill_switch` | ai-quant-lab's KillSwitch tripped (generic) |
| `portfolio_drawdown=0.16` | Portfolio-level kill (all strategies halted) |
| `manual_halt` | Agent or human called halt_strategy |

## Portfolio risk check

When the user asks "how is the portfolio doing?" or "are we too exposed?", call `portfolio_risk`:

```
portfolio_risk() → combined PnL, drawdown, correlation matrix
```

Key flags:
- `portfolio_max_dd_breach=true` — portfolio drawdown exceeds threshold. Recommend halting all live strategies.
- High correlation between live strategies (corr > 0.7) — they're essentially the same trade. Recommend halting one.
- `n_active=0` — nothing running. Offer to deploy approved survivors.

## When to recommend halting

Recommend calling `halt_strategy` when:
1. `state=PAPER` and realized Sharpe after 20+ days is < 0 (strategy isn't working)
2. `heartbeat_age_seconds > 7200` (runner is dead)
3. `portfolio_max_dd_breach=true` (mandatory portfolio-level halt)
4. User explicitly asks to stop it

## When to recommend promote_to_live

Suggest `promote_to_live` when:
- Strategy has been paper trading ≥ 20 days
- Realized Sharpe is consistent with backtest Sharpe (within ~0.5)
- No kill-switch events
- Portfolio correlation with other live strategies < 0.6

Always remind: promotion requires HITL approval. You can recommend; you cannot approve.

## Related skills

- [[live-deployment]] — deploying strategies
- [[strategy-validation]] — interpreting gate results
