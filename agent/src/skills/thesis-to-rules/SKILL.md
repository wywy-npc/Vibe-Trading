---
name: thesis-to-rules
category: strategy
description: Translate a qualitative analyst thesis into a deterministic systematic trade. PM checkpoints at the interpretation and rule-writing seams; backtest runs automatically to confirm historical edge; PM sets conviction-based sizing; approving pm_go_live deploys live.
autonomy:
  mode: hitl
  checkpoints:
    - id: thesis_interpretation
      after_node: parse_thesis
      prompt: "Confirm the agent's interpretation of your thesis."
      payload_schema:
        thesis_text: string
        identified_drivers: list[string]
        time_horizon: string
        asset_universe: list[string]
        regime_assumptions: list[string]
      allowed_edits: [identified_drivers, time_horizon, asset_universe, regime_assumptions]
      decision_types: [approve, reject, modify]
      ttl_hours: 72

    - id: rule_codification
      after_node: codify_rules
      prompt: "Review the systematic rules. Do they capture the spirit of the thesis?"
      payload_schema:
        rules_dsl: string
        entry_logic: string
        exit_logic: string
        invalidation_triggers: list[string]
      allowed_edits: [rules_dsl, entry_logic, exit_logic, invalidation_triggers]
      decision_types: [approve, reject, modify]
      ttl_hours: 72

    - id: position_sizing
      after_node: propose_sizing
      prompt: "Review backtest results and set conviction-based position size."
      payload_schema:
        sharpe: float
        max_dd: float
        win_rate: float
        avg_hold_days: float
        proposed_alloc_pct: float
        vol_target: float
        max_pos_pct: float
        correlation_to_book: float
      allowed_edits: [proposed_alloc_pct, vol_target, max_pos_pct]
      decision_types: [approve, reject, modify]

    - id: pm_go_live
      after_node: deploy
      prompt: "Approve to deploy live. Edge is established by the thesis and historical analogs — there is no value in paper trading a discretionary conviction. Reject to discard."
      payload_schema:
        strategy_name: string
        broker: string
        symbols: list[string]
        backtest_sharpe: float
        backtest_max_dd: float
        first_order_preview: object
      allowed_edits: [broker]
      decision_types: [approve, reject]
      requires_role: pm
---

# Thesis → Rules → Live

Takes a qualitative analyst thesis and produces a live trade. This is a
**discretionary workflow** — the PM's conviction is the edge. There is no
paper trading period.

For systematic/quant strategies that run on recurring signals, use the
`research_loop` → AI Quant Lab gates → `deploy_strategy_tool` path instead.
Those strategies validate edge statistically before deployment.

## Why no paper trading for thesis trades

Paper trading validates infrastructure, not edge. For a discretionary thesis:
- Edge was determined when the PM formed the view and confirmed the analogs
- The time window may not survive a paper period
- Watching a paper position tick doesn't tell you whether the original thesis was right
- The PM approval chain at `thesis_interpretation`, `rule_codification`, and
  `position_sizing` is the validation — not a simulated PnL run

If infrastructure validation is needed (data feed, order routing), do it
separately as a small test trade or use the deployment registry's kill-switch
mechanism as the live safety net.

## Checkpoints

### `thesis_interpretation` — after `parse_thesis`
Agent reads the thesis and extracts: drivers, time horizon, asset universe,
regime assumptions. PM corrects before rules are written. This is where
misinterpretation is cheapest to fix.

### `rule_codification` — after `codify_rules`
Agent writes a `SignalEngine` class from the PM-approved interpretation.
PM reads entry/exit in plain English, edits the DSL directly if needed.

### `position_sizing` — after `run_backtest` + `propose_sizing`
Backtest runs autonomously (no pause). PM sees results here alongside the
sizing proposal: `{sharpe, max_dd, win_rate}` + `{proposed_alloc_pct,
correlation_to_book}`. PM sets conviction. Historical edge confirms the
thesis has precedent; PM conviction sets the size.

### `pm_go_live` — after `deploy`
Final gate. Approving registers in `deployments.db` and forks the live runner.
First order goes to the broker. Reject discards without touching the book.

## Promote / halt

After deployment, manage via the existing live infrastructure:
- `POST /live/{deployment_id}/halt` — kill-switch
- `POST /live/{deployment_id}/promote/decide` — not needed (already live)
