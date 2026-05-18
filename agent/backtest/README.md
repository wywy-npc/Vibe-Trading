# `agent/backtest/`

Backtest engines, loaders, validation, and ai-quant-lab gate integration for the Vibe-Trading agentic quant research harness.

## Layout

```
backtest/
├── engines/           # Daily / options / cross-market / composite engines
├── loaders/           # Source-specific data loaders + registry
│   └── registry.py    # market_type → ordered loader fallback chains
├── optimizers/        # Parameter sweep / hyperparameter search
├── runner.py          # CLI entry: read config.json, fetch data, run engine, post-engine gates
├── metrics.py         # Sharpe / max DD / win rate / etc.
├── correlation.py     # Cross-strategy correlation
├── benchmark.py       # Benchmark equity construction
├── validation.py      # Statistical post-hoc tests (Monte Carlo, bootstrap, walk-forward)
├── validation_aql.py  # Adapter to ai-quant-lab gates (DSR, correlation, PCA, leakage)
└── research_memory.py # Process-safe trial counter (SQLite) — backs Deflated Sharpe
```

## ai-quant-lab integration

The harness wraps an external library, **ai-quant-lab** (installed via `requirements.txt` from a pinned git SHA). It provides:

- **`evaluate_gates`** — orchestrates the gate stack: critic → Deflated Sharpe → correlation → PCA → leakage.
- **`CriticAgent`** — adversarial pre-backtest reviewer that kills bad ideas before code is written.
- **`ResearchMemory`** — durable trial counter so Deflated Sharpe is honest across sessions/processes.
- **`run_research_loop`** — the deterministic Hypothesis → Critic → Code → Sandbox → Backtest → Gates pipeline behind the `research_loop` tool.

### Post-engine gate hook (`runner.py:480–522`)

Every backtest run (whether invoked by the agent's `backtest` tool, the CLI, or the API) emits a `gates.json` artifact alongside `artifacts/metrics.csv`. The hook:

1. Reconstructs any `critic_verdict` previously stamped into `config.json`.
2. Calls `validation_aql.gates_from_artifacts(run_dir, memory=memory, critic_verdict=verdict)`.
3. Writes `gates.json` with `via`, `loop_run_id` (if present), `n_trials_at_gate`, the critic verdict, and the gate outcomes.
4. Records a `TrialRecord` in `research_memory.db` so the DSR n_trials counter stays honest.

If ai-quant-lab is missing, the hook degrades silently — engines still produce metrics, but no gates fire.

## The hard-gate invariant

Only `research_loop` produces *fully gated* results. The invariant is enforced in two layers:

1. **Origin stamping**: `research_loop_tool` stamps `via="loop"` and a fresh `loop_run_id` in `config.json`. `backtest_tool` stamps `via="manual"`. `thesis-to-rules` stamps `via="thesis"`.
2. **`validate_run` enforcement**: by default `validate_run` returns `{"status":"error","code":"not_loop_gated"}` unless the target run has `via="loop"` and a `loop_run_id`. Analysts can override with `allow_non_loop=true`; the override is stamped into `gates.json` for audit.

This makes it structurally impossible to chain `critique` → `backtest` → `validate_run` and have the output look loop-gated.

## `research_memory.db`

Default path: `agent/research_memory.db` (next to this directory). Override via `VIBE_TRADING_RESEARCH_MEMORY_PATH`. The file is in `.gitignore`.

**Do not delete it between sessions.** The Deflated Sharpe gate's strictness scales with `n_trials`; resetting the counter is the multiple-testing equivalent of "playing slot machines until you win."

## `gates.json` schema

```json
{
  "passes": false,
  "rejection_reason": "deflated_sharpe_pvalue=0.61>=0.05",
  "via": "manual",
  "loop_run_id": null,
  "n_trials_at_gate": 47,
  "critic_verdict": {"passes": true, "reasoning": "...", "kill_reasons": []},
  "dsr": {"sharpe": 1.42, "deflated_sharpe": 0.31, "pvalue": 0.61},
  "max_correlation": 0.23,
  "pca_concentration": 0.42
}
```

Fields added by P0 (May 2026):
- `via` — origin of the run: `loop` (research_loop), `manual` (backtest_tool), `thesis` (thesis-to-rules), `unknown` (older runs).
- `loop_run_id` — UUID, present only when `via="loop"`.
- `allow_non_loop_override` — present (and `true`) when `validate_run` was called with `allow_non_loop=true` against a non-loop run.
- `revalidated` — present (and `true`) when `validate_run` wrote the artifact post-hoc rather than the engine's post-hook.

## Tools and skills surface

| Tool | Purpose | Trigger |
|---|---|---|
| `backtest` | Run one backtest from `config.json` + `signal_engine.py` | Manual coding path |
| `research_loop` | Deterministic discovery pipeline (one Python-controlled call) | "Find / discover / generate strategies" |
| `critique` | Cheap pre-backtest adversarial review | Ad-hoc idea check |
| `validate_run` | Re-evaluate gates on an existing run | After `n_trials` grows |
| `leakage_scan` | Position-vs-future-return correlation audit | When a Sharpe looks too good |

Skills wrapping these: `strategy-generate` (manual), `strategy-discovery` (loop), `strategy-validation` (interpret gates.json), `adversarial-critic` (pre-backtest kill), `thesis-to-rules` (PM-gated qualitative→systematic flow).

## Loader registry (`loaders/registry.py`)

`_loader_modules` is the canonical import list — adding a new loader means appending its module path here and `@register`-ing the class. Fallback chains map a `market_type` to an ordered list of source names; the runner walks the chain on a `NoAvailableSourceError`.

US-equity default chain (as of May 2026): `["alpaca", "yfinance", "akshare"]`. **`AAPL.US` now defaults to `alpaca`** (requires `ALPACA_KEY_ID`/`ALPACA_SECRET_KEY` env vars); without them the chain falls through to yfinance.
