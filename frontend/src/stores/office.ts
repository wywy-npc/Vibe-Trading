import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Strategy, Mandate, OfficAlert, Agent, ActivityEntry, DecisionRecord } from "@/types/office";

// ─── Deterministic helpers ────────────────────────────────────────────────────

function mockCurve(seed: number, len = 60, bull = true): Array<{ t: number; v: number }> {
  let v = 100000;
  const out = [];
  for (let i = 0; i < len; i++) {
    const rand = Math.sin(seed * 9301 + i * 49297 + 233720) * 0.5 + 0.5;
    const drift = bull ? 0.0008 : -0.0003;
    v = v * (1 + drift + (rand - 0.5) * 0.018);
    out.push({ t: i, v: Math.round(v) });
  }
  return out;
}

// ─── Seed data ────────────────────────────────────────────────────────────────

const SEED_STRATEGIES: Strategy[] = [
  {
    id: "strat-001",
    name: "HK Small Cap 3-Factor Momentum",
    origin: "overnight_loop",
    market: "HK Equities",
    signal_logic: "Enter long when 20-day momentum rank > 80th percentile in top 200 HK small caps, RSI(14) not overbought (< 70), and volume z-score > 0.5. Exit on rank < 40th percentile or -5% stop-loss.",
    metrics: { sharpe: 1.47, max_drawdown: -8.3, win_rate: 61.2, annual_return: 23.4, total_return: 58.6, trade_count: 142 },
    regime_performance: {
      bull:     { return: 34.2, win_rate: 71 },
      bear:     { return: 8.1,  win_rate: 48 },
      high_vol: { return: 11.3, win_rate: 52 },
      low_vol:  { return: 31.8, win_rate: 69 },
    },
    risk_flags: ["0.71 correlation to Strategy #4 in book"],
    status: "pending",
    equity_curve: mockCurve(1, 60, true),
    created_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    agent_id: "momentum-scanner",
  },
  {
    id: "strat-002",
    name: "Tariff Regime USD Long",
    origin: "event_trigger",
    market: "Forex",
    signal_logic: "Systematic USD long via DXY-correlated basket. Enters when tariff escalation index (news NLP score) crosses threshold + USD 3-month momentum positive. Exits on de-escalation signal or monthly rebalance.",
    metrics: { sharpe: 1.21, max_drawdown: -6.1, win_rate: 58.0, annual_return: 17.8, total_return: 31.2, trade_count: 28 },
    regime_performance: {
      bull:     { return: 12.4, win_rate: 55 },
      bear:     { return: 22.1, win_rate: 64 },
      high_vol: { return: 19.8, win_rate: 61 },
      low_vol:  { return: 8.3,  win_rate: 44 },
    },
    risk_flags: [],
    status: "pending",
    equity_curve: mockCurve(2, 60, true),
    created_at: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
    agent_id: "macro-encoder",
  },
  {
    id: "strat-003",
    name: "Crypto Mean Reversion BTC/ETH",
    origin: "overnight_loop",
    market: "Crypto",
    signal_logic: "Fade 4h z-score > 2.5 deviations from 20-period mean on BTC and ETH. Size inversely proportional to volatility. Hard stop at 3% per leg. Take profit at z-score reversion to 0.5.",
    metrics: { sharpe: 0.98, max_drawdown: -14.2, win_rate: 54.8, annual_return: 31.1, total_return: 72.3, trade_count: 614 },
    regime_performance: {
      bull:     { return: 42.3, win_rate: 58 },
      bear:     { return: 18.2, win_rate: 51 },
      high_vol: { return: 38.1, win_rate: 56 },
      low_vol:  { return: 9.4,  win_rate: 46 },
    },
    risk_flags: ["Max drawdown near 15% limit", "High trade frequency — review slippage assumptions"],
    status: "pending",
    equity_curve: mockCurve(3, 60, false),
    created_at: new Date(Date.now() - 8 * 60 * 60 * 1000).toISOString(),
    agent_id: "crypto-scanner",
  },
  {
    id: "strat-004",
    name: "HK Momentum Factor #3",
    origin: "overnight_loop",
    market: "HK Equities",
    signal_logic: "Long top-decile 60-day momentum stocks in HSI universe, equal-weight, monthly rebalance with liquidity filter.",
    metrics: { sharpe: 1.52, max_drawdown: -9.1, win_rate: 63.0, annual_return: 26.1, total_return: 41.8, trade_count: 96 },
    regime_performance: {
      bull:     { return: 38.4, win_rate: 74 },
      bear:     { return: 6.2,  win_rate: 44 },
      high_vol: { return: 14.1, win_rate: 54 },
      low_vol:  { return: 33.7, win_rate: 70 },
    },
    risk_flags: [],
    status: "live",
    allocation_pct: 12,
    daily_pnl: 0.4,
    equity_curve: mockCurve(4, 90, true),
    created_at: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString(),
    live_since: new Date(Date.now() - 28 * 24 * 60 * 60 * 1000).toISOString(),
    decision: { action: "approve", reason: "Clean signal, low correlation to book.", timestamp: new Date(Date.now() - 28 * 24 * 60 * 60 * 1000).toISOString(), allocation_pct: 12 },
  },
  {
    id: "strat-005",
    name: "USD Carry Basket",
    origin: "mandate",
    market: "Forex",
    signal_logic: "Long high-yield EM currencies vs USD, weighted by carry differential and volatility-adjusted. Weekly rebalance.",
    metrics: { sharpe: 1.12, max_drawdown: -7.4, win_rate: 56.3, annual_return: 14.2, total_return: 19.8, trade_count: 44 },
    regime_performance: {
      bull:     { return: 18.3, win_rate: 62 },
      bear:     { return: 6.1,  win_rate: 42 },
      high_vol: { return: 8.4,  win_rate: 48 },
      low_vol:  { return: 19.8, win_rate: 64 },
    },
    risk_flags: [],
    status: "live",
    allocation_pct: 8,
    daily_pnl: -0.1,
    equity_curve: mockCurve(5, 90, true),
    created_at: new Date(Date.now() - 60 * 24 * 60 * 60 * 1000).toISOString(),
    live_since: new Date(Date.now() - 55 * 24 * 60 * 60 * 1000).toISOString(),
    decision: { action: "approve", reason: "Good diversifier, low equity beta.", timestamp: new Date(Date.now() - 55 * 24 * 60 * 60 * 1000).toISOString(), allocation_pct: 8 },
  },
  {
    id: "strat-006",
    name: "EM FX Short Basket",
    origin: "overnight_loop",
    market: "Forex",
    signal_logic: "Short EM FX basket when DXY > 104 and US 2Y yield > 4.5%. Systematic rule-based, monthly rebalance.",
    metrics: { sharpe: 1.33, max_drawdown: -5.8, win_rate: 60.1, annual_return: 19.3, total_return: 28.4, trade_count: 18 },
    regime_performance: {
      bull:     { return: 8.1,  win_rate: 48 },
      bear:     { return: 28.4, win_rate: 68 },
      high_vol: { return: 24.2, win_rate: 64 },
      low_vol:  { return: 6.1,  win_rate: 44 },
    },
    risk_flags: [],
    status: "deferred",
    equity_curve: mockCurve(6, 60, true),
    created_at: new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString(),
    decision: { action: "defer", reason: "Good strategy, wrong macro timing right now.", defer_condition: "Revisit when DXY > 104 and US 2Y yield breaks above 4.5%", timestamp: new Date(Date.now() - 12 * 24 * 60 * 60 * 1000).toISOString() },
  },
];

const SEED_MANDATES = [
  {
    id: "mand-001",
    name: "HK Small Cap Momentum Scan",
    description: "Scan the top 200 HK small caps nightly for momentum factor opportunities. Minimum Sharpe 1.2, max drawdown 12%.",
    markets: ["HK Equities"],
    signal_types: ["momentum", "factor"],
    min_sharpe: 1.2,
    max_drawdown_limit: 12,
    active: true,
    schedule: "Nightly 02:00 HKT",
    created_at: new Date(Date.now() - 45 * 24 * 60 * 60 * 1000).toISOString(),
    last_run: new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString(),
    strategies_found: 8,
  },
  {
    id: "mand-002",
    name: "Macro Event Encoder",
    description: "Monitor news for macro regime-change events (tariffs, central bank, geopolitics). Encode into systematic strategies when signal score > threshold.",
    markets: ["Forex", "Futures"],
    signal_types: ["macro", "event-driven"],
    min_sharpe: 1.0,
    max_drawdown_limit: 10,
    active: true,
    schedule: "Continuous (event-triggered)",
    created_at: new Date(Date.now() - 20 * 24 * 60 * 60 * 1000).toISOString(),
    last_run: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
    strategies_found: 3,
  },
  {
    id: "mand-003",
    name: "Crypto Volatility Arbitrage",
    description: "Scan crypto pairs for mean-reversion opportunities during elevated volatility periods.",
    markets: ["Crypto"],
    signal_types: ["mean-reversion", "statistical-arb"],
    min_sharpe: 1.1,
    max_drawdown_limit: 15,
    active: false,
    schedule: "Nightly 01:00 UTC",
    created_at: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(),
    strategies_found: 2,
  },
];

const SEED_ALERTS = [
  { id: "alert-001", type: "strategy_surfaced" as const, message: "Overnight loop surfaced 2 new strategies — HK Small Cap Momentum and Crypto Mean Reversion ready for review.", timestamp: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(), read: false, strategy_id: "strat-001" },
  { id: "alert-002", type: "event_trigger" as const,     message: "Tariff escalation signal triggered. Macro Encoder built a systematic USD long strategy.", timestamp: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(), read: false, strategy_id: "strat-002" },
  { id: "alert-003", type: "book_update" as const,       message: "HK Momentum Factor #3 up +0.4% today. USD Carry Basket flat (-0.1%).", timestamp: new Date(Date.now() - 60 * 60 * 1000).toISOString(), read: false },
  { id: "alert-004", type: "mandate_complete" as const,  message: "HK Small Cap Momentum Scan completed at 02:14 HKT. 3 candidates screened, 2 passed filters.", timestamp: new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString(), read: true },
];

const SEED_DECISIONS: DecisionRecord[] = [
  {
    id: "dec-001",
    timestamp: new Date(Date.now() - 28 * 24 * 60 * 60 * 1000).toISOString(),
    strategy_id: "strat-004",
    strategy_name: "HK Momentum Factor #3",
    market: "HK Equities",
    agent_id: "momentum-scanner",
    action: "approve",
    allocation_pct: 12,
    reason: "Clean signal, low correlation to book.",
    metrics: { sharpe: 1.52, max_drawdown: -9.1, annual_return: 26.1, win_rate: 63.0 },
  },
  {
    id: "dec-002",
    timestamp: new Date(Date.now() - 55 * 24 * 60 * 60 * 1000).toISOString(),
    strategy_id: "strat-005",
    strategy_name: "USD Carry Basket",
    market: "Forex",
    agent_id: "macro-encoder",
    action: "approve",
    allocation_pct: 8,
    reason: "Good diversifier, low equity beta.",
    metrics: { sharpe: 1.12, max_drawdown: -7.4, annual_return: 14.2, win_rate: 56.3 },
  },
  {
    id: "dec-003",
    timestamp: new Date(Date.now() - 12 * 24 * 60 * 60 * 1000).toISOString(),
    strategy_id: "strat-006",
    strategy_name: "EM FX Short Basket",
    market: "Forex",
    agent_id: "momentum-scanner",
    action: "defer",
    reason: "Good strategy, wrong macro timing right now.",
    defer_condition: "Revisit when DXY > 104 and US 2Y yield breaks above 4.5%",
    metrics: { sharpe: 1.33, max_drawdown: -5.8, annual_return: 19.3, win_rate: 60.1 },
  },
];

const SEED_AGENTS: Agent[] = [
  {
    id: "momentum-scanner",
    name: "momentum-scanner",
    role: "Quant Researcher",
    specialty: "Equity momentum & factor models",
    status: "backtesting",
    current_task: "Running walk-forward on HSI universe — pass 3 of 8",
    progress: 38,
    last_active: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
    strategies_surfaced: 12,
    backtests_run: 847,
  },
  {
    id: "macro-encoder",
    name: "macro-encoder",
    role: "Macro Strategist",
    specialty: "News NLP → systematic strategy encoding",
    status: "encoding",
    current_task: "Processing 14 Fed-related articles from last 6h",
    progress: 61,
    last_active: new Date(Date.now() - 90 * 1000).toISOString(),
    strategies_surfaced: 5,
    backtests_run: 124,
  },
  {
    id: "crypto-scanner",
    name: "crypto-scanner",
    role: "Crypto Analyst",
    specialty: "Mean-reversion & vol arb across 100+ pairs",
    status: "scanning",
    current_task: "Scanning BTC/ETH/SOL for z-score divergences",
    progress: 72,
    last_active: new Date(Date.now() - 30 * 1000).toISOString(),
    strategies_surfaced: 7,
    backtests_run: 2341,
  },
  {
    id: "risk-monitor",
    name: "risk-monitor",
    role: "Risk Officer",
    specialty: "Portfolio correlation & drawdown surveillance",
    status: "idle",
    current_task: "Watching live book — next check in 12m",
    progress: 0,
    last_active: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    strategies_surfaced: 0,
    backtests_run: 0,
  },
];

const SEED_ACTIVITY: ActivityEntry[] = [
  { id: "act-001", agent_id: "crypto-scanner",    agent_name: "crypto-scanner",    type: "scan",      message: "Scanning BTC/ETH spread — z-score 1.84, below threshold", timestamp: new Date(Date.now() - 45 * 1000).toISOString() },
  { id: "act-002", agent_id: "macro-encoder",      agent_name: "macro-encoder",      type: "encode",    message: "Fed pivot signal detected — encoding rate sensitivity basket", timestamp: new Date(Date.now() - 2 * 60 * 1000).toISOString() },
  { id: "act-003", agent_id: "momentum-scanner",   agent_name: "momentum-scanner",   type: "backtest",  message: "Walk-forward window 3/8 complete — Sharpe 1.31 OOS", timestamp: new Date(Date.now() - 4 * 60 * 1000).toISOString() },
  { id: "act-004", agent_id: "crypto-scanner",    agent_name: "crypto-scanner",    type: "scan",      message: "SOL/BTC pair — z-score 2.21, approaching entry threshold", timestamp: new Date(Date.now() - 6 * 60 * 1000).toISOString() },
  { id: "act-005", agent_id: "momentum-scanner",   agent_name: "momentum-scanner",   type: "signal",    message: "New signal: HK Small Cap 3-Factor Momentum → surfaced to inbox", timestamp: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString() },
  { id: "act-006", agent_id: "macro-encoder",      agent_name: "macro-encoder",      type: "signal",    message: "Tariff escalation index crossed 0.72 — USD long strategy built", timestamp: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString() },
  { id: "act-007", agent_id: "risk-monitor",       agent_name: "risk-monitor",       type: "scan",      message: "Book correlation check — HK Momentum / USD Carry: 0.18 ✓", timestamp: new Date(Date.now() - 12 * 60 * 1000).toISOString() },
  { id: "act-008", agent_id: "momentum-scanner",   agent_name: "momentum-scanner",   type: "backtest",  message: "Started overnight run — 847 stocks, 24-month lookback", timestamp: new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString() },
];

// ─── State interface ──────────────────────────────────────────────────────────

interface OfficeState {
  strategies: Strategy[];
  mandates: Mandate[];
  alerts: OfficAlert[];
  agents: Agent[];
  activity: ActivityEntry[];
  decisions: DecisionRecord[];

  approveStrategy: (id: string, allocation_pct: number, reason: string) => void;
  rejectStrategy: (id: string, reason: string) => void;
  deferStrategy: (id: string, reason: string, condition: string) => void;
  modifyStrategy: (id: string, instructions: string) => void;
  pauseStrategy: (id: string) => void;
  resumeStrategy: (id: string) => void;
  resizeStrategy: (id: string, allocation_pct: number) => void;
  killStrategy: (id: string) => void;

  addMandate: (m: Omit<Mandate, "id" | "created_at">) => void;
  toggleMandate: (id: string) => void;
  deleteMandate: (id: string) => void;

  markAlertRead: (id: string) => void;
  markAllAlertsRead: () => void;

  pushActivity: (entry: Omit<ActivityEntry, "id" | "timestamp">) => void;
  updateAgentStatus: (id: string, patch: Partial<Agent>) => void;
}

// ─── Store ────────────────────────────────────────────────────────────────────

export const useOfficeStore = create<OfficeState>()(
  persist(
    (set) => ({
      strategies: SEED_STRATEGIES,
      mandates: SEED_MANDATES,
      alerts: SEED_ALERTS,
      agents: SEED_AGENTS,
      activity: SEED_ACTIVITY,
      decisions: SEED_DECISIONS,

      approveStrategy: (id, allocation_pct, reason) =>
        set((s: OfficeState) => {
          const st = s.strategies.find((x: Strategy) => x.id === id);
          const rec: DecisionRecord = { id: `dec-${Date.now()}`, timestamp: new Date().toISOString(), strategy_id: id, strategy_name: st?.name ?? id, market: st?.market ?? "", agent_id: st?.agent_id ?? "", action: "approve" as const, allocation_pct, reason, metrics: { sharpe: st?.metrics.sharpe ?? 0, max_drawdown: st?.metrics.max_drawdown ?? 0, annual_return: st?.metrics.annual_return ?? 0, win_rate: st?.metrics.win_rate ?? 0 } };
          return {
            strategies: s.strategies.map((x: Strategy) => x.id === id ? { ...x, status: "live" as const, allocation_pct, live_since: new Date().toISOString(), decision: { action: "approve" as const, reason, timestamp: new Date().toISOString(), allocation_pct } } : x),
            decisions: [rec, ...s.decisions],
          };
        }),

      rejectStrategy: (id, reason) =>
        set((s: OfficeState) => {
          const st = s.strategies.find((x: Strategy) => x.id === id);
          const rec: DecisionRecord = { id: `dec-${Date.now()}`, timestamp: new Date().toISOString(), strategy_id: id, strategy_name: st?.name ?? id, market: st?.market ?? "", agent_id: st?.agent_id ?? "", action: "reject" as const, reason, metrics: { sharpe: st?.metrics.sharpe ?? 0, max_drawdown: st?.metrics.max_drawdown ?? 0, annual_return: st?.metrics.annual_return ?? 0, win_rate: st?.metrics.win_rate ?? 0 } };
          return {
            strategies: s.strategies.map((x: Strategy) => x.id === id ? { ...x, status: "rejected" as const, decision: { action: "reject" as const, reason, timestamp: new Date().toISOString() } } : x),
            decisions: [rec, ...s.decisions],
          };
        }),

      deferStrategy: (id, reason, condition) =>
        set((s: OfficeState) => {
          const st = s.strategies.find((x: Strategy) => x.id === id);
          const rec: DecisionRecord = { id: `dec-${Date.now()}`, timestamp: new Date().toISOString(), strategy_id: id, strategy_name: st?.name ?? id, market: st?.market ?? "", agent_id: st?.agent_id ?? "", action: "defer" as const, reason, defer_condition: condition, metrics: { sharpe: st?.metrics.sharpe ?? 0, max_drawdown: st?.metrics.max_drawdown ?? 0, annual_return: st?.metrics.annual_return ?? 0, win_rate: st?.metrics.win_rate ?? 0 } };
          return {
            strategies: s.strategies.map((x: Strategy) => x.id === id ? { ...x, status: "deferred" as const, decision: { action: "defer" as const, reason, defer_condition: condition, timestamp: new Date().toISOString() } } : x),
            decisions: [rec, ...s.decisions],
          };
        }),

      modifyStrategy: (id, instructions) =>
        set((s: OfficeState) => {
          const st = s.strategies.find((x: Strategy) => x.id === id);
          const rec: DecisionRecord = { id: `dec-${Date.now()}`, timestamp: new Date().toISOString(), strategy_id: id, strategy_name: st?.name ?? id, market: st?.market ?? "", agent_id: st?.agent_id ?? "", action: "modify" as const, reason: instructions, metrics: { sharpe: st?.metrics.sharpe ?? 0, max_drawdown: st?.metrics.max_drawdown ?? 0, annual_return: st?.metrics.annual_return ?? 0, win_rate: st?.metrics.win_rate ?? 0 } };
          return {
            strategies: s.strategies.map((x: Strategy) => x.id === id ? { ...x, decision: { action: "modify" as const, reason: instructions, timestamp: new Date().toISOString() } } : x),
            alerts: [{ id: `alert-mod-${id}`, type: "strategy_surfaced" as const, message: `Modification sent to agent for "${st?.name}". Will re-surface when ready.`, timestamp: new Date().toISOString(), read: false, strategy_id: id }, ...s.alerts],
            decisions: [rec, ...s.decisions],
          };
        }),

      pauseStrategy:  (id) => set((s: OfficeState) => ({ strategies: s.strategies.map((st: Strategy) => st.id === id ? { ...st, status: "paused"  as const } : st) })),
      resumeStrategy: (id) => set((s: OfficeState) => ({ strategies: s.strategies.map((st: Strategy) => st.id === id ? { ...st, status: "live"    as const } : st) })),
      resizeStrategy: (id, allocation_pct) => set((s: OfficeState) => ({ strategies: s.strategies.map((st: Strategy) => st.id === id ? { ...st, allocation_pct } : st) })),
      killStrategy:   (id) => set((s: OfficeState) => ({ strategies: s.strategies.map((st: Strategy) => st.id === id ? { ...st, status: "rejected" as const, decision: { action: "reject" as const, reason: "Killed by PM.", timestamp: new Date().toISOString() } } : st) })),

      addMandate: (m) => set((s: OfficeState) => ({ mandates: [...s.mandates, { ...m, id: `mand-${Date.now()}`, created_at: new Date().toISOString() }] })),
      toggleMandate: (id) => set((s: OfficeState) => ({ mandates: s.mandates.map((m: Mandate) => m.id === id ? { ...m, active: !m.active } : m) })),
      deleteMandate: (id) => set((s: OfficeState) => ({ mandates: s.mandates.filter((m: Mandate) => m.id !== id) })),

      markAlertRead:    (id) => set((s: OfficeState) => ({ alerts: s.alerts.map((a: OfficAlert) => a.id === id ? { ...a, read: true } : a) })),
      markAllAlertsRead: ()  => set((s: OfficeState) => ({ alerts: s.alerts.map((a: OfficAlert) => ({ ...a, read: true })) })),

      pushActivity: (entry) =>
        set((s: OfficeState) => ({
          activity: [{ ...entry, id: `act-${Date.now()}`, timestamp: new Date().toISOString() }, ...s.activity].slice(0, 50),
        })),

      updateAgentStatus: (id, patch) =>
        set((s: OfficeState) => ({
          agents: s.agents.map((a: Agent) => a.id === id ? { ...a, ...patch, last_active: new Date().toISOString() } : a),
        })),
    }),
    { name: "vibe-office-store-v2" }
  )
);

// ─── Portfolio impact calculator (pure, no store) ─────────────────────────────

export function calcPortfolioImpact(strategies: Strategy[], candidateId: string, allocationPct: number) {
  const live = strategies.filter(s => s.status === "live");
  const candidate = strategies.find(s => s.id === candidateId);
  if (!candidate) return null;

  const currentDeployed = live.reduce((a, s) => a + (s.allocation_pct ?? 0), 0);
  const currentSharpe = live.length > 0
    ? live.reduce((a, s) => a + s.metrics.sharpe * (s.allocation_pct ?? 5), 0) / Math.max(currentDeployed, 1)
    : 0;
  const currentMaxDD = live.length > 0
    ? live.reduce((a, s) => a + Math.abs(s.metrics.max_drawdown) * (s.allocation_pct ?? 5), 0) / Math.max(currentDeployed, 1)
    : 0;

  const newDeployed = currentDeployed + allocationPct;
  const newSharpe = (currentSharpe * currentDeployed + candidate.metrics.sharpe * allocationPct) / Math.max(newDeployed, 1);
  const newMaxDD = (currentMaxDD * currentDeployed + Math.abs(candidate.metrics.max_drawdown) * allocationPct) / Math.max(newDeployed, 1);

  // Simplified marginal correlation (would use actual covariance in production)
  const correlationImpact = candidate.risk_flags.some(f => f.includes("correlation")) ? "increases" : "neutral";

  return {
    currentDeployed,
    newDeployed,
    currentSharpe,
    newSharpe,
    currentMaxDD: -currentMaxDD,
    newMaxDD: -newMaxDD,
    remainingBudget: 100 - newDeployed,
    correlationImpact,
    deltaSharpe: newSharpe - currentSharpe,
    deltaDD: newMaxDD - currentMaxDD,
  };
}
