import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Strategy, Mandate, OfficAlert, DecisionAction } from "@/types/office";

// Deterministic sparkline generator so seed data looks realistic
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

const SEED_STRATEGIES: Strategy[] = [
  {
    id: "strat-001",
    name: "HK Small Cap 3-Factor Momentum",
    origin: "overnight_loop",
    market: "HK Equities",
    signal_logic:
      "Enter long when 20-day momentum rank > 80th percentile in top 200 HK small caps, RSI(14) not overbought (< 70), and volume z-score > 0.5. Exit on rank < 40th percentile or -5% stop-loss.",
    metrics: { sharpe: 1.47, max_drawdown: -8.3, win_rate: 61.2, annual_return: 23.4, total_return: 58.6, trade_count: 142 },
    risk_flags: ["0.71 correlation to Strategy #4 in book"],
    status: "pending",
    equity_curve: mockCurve(1, 60, true),
    created_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    agent_id: "momentum-scanner-v2",
  },
  {
    id: "strat-002",
    name: "Tariff Regime USD Long",
    origin: "event_trigger",
    market: "Forex",
    signal_logic:
      "Systematic USD long via DXY-correlated basket. Enters when tariff escalation index (news NLP score) crosses threshold + USD 3-month momentum positive. Exits on de-escalation signal or monthly rebalance.",
    metrics: { sharpe: 1.21, max_drawdown: -6.1, win_rate: 58.0, annual_return: 17.8, total_return: 31.2, trade_count: 28 },
    risk_flags: [],
    status: "pending",
    equity_curve: mockCurve(2, 60, true),
    created_at: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
    agent_id: "macro-encoder-v1",
  },
  {
    id: "strat-003",
    name: "Crypto Mean Reversion BTC/ETH",
    origin: "overnight_loop",
    market: "Crypto",
    signal_logic:
      "Fade 4h z-score > 2.5 deviations from 20-period mean on BTC and ETH. Size inversely proportional to volatility. Hard stop at 3% per leg. Take profit at z-score reversion to 0.5.",
    metrics: { sharpe: 0.98, max_drawdown: -14.2, win_rate: 54.8, annual_return: 31.1, total_return: 72.3, trade_count: 614 },
    risk_flags: ["Max drawdown near 15% limit", "High trade frequency — review slippage assumptions"],
    status: "pending",
    equity_curve: mockCurve(3, 60, false),
    created_at: new Date(Date.now() - 8 * 60 * 60 * 1000).toISOString(),
    agent_id: "crypto-scanner-v1",
  },
  // Live strategies (already approved)
  {
    id: "strat-004",
    name: "HK Momentum Factor #3",
    origin: "overnight_loop",
    market: "HK Equities",
    signal_logic: "Long top-decile 60-day momentum stocks in HSI universe, equal-weight, monthly rebalance with liquidity filter.",
    metrics: { sharpe: 1.52, max_drawdown: -9.1, win_rate: 63.0, annual_return: 26.1, total_return: 41.8, trade_count: 96 },
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
    risk_flags: [],
    status: "live",
    allocation_pct: 8,
    daily_pnl: -0.1,
    equity_curve: mockCurve(5, 90, true),
    created_at: new Date(Date.now() - 60 * 24 * 60 * 60 * 1000).toISOString(),
    live_since: new Date(Date.now() - 55 * 24 * 60 * 60 * 1000).toISOString(),
    decision: { action: "approve", reason: "Good diversifier, low equity beta.", timestamp: new Date(Date.now() - 55 * 24 * 60 * 60 * 1000).toISOString(), allocation_pct: 8 },
  },
  // Deferred
  {
    id: "strat-006",
    name: "EM FX Short Basket",
    origin: "overnight_loop",
    market: "Forex",
    signal_logic: "Short EM FX basket when DXY > 104 and US 2Y yield > 4.5%. Systematic rule-based, monthly rebalance.",
    metrics: { sharpe: 1.33, max_drawdown: -5.8, win_rate: 60.1, annual_return: 19.3, total_return: 28.4, trade_count: 18 },
    risk_flags: [],
    status: "deferred",
    equity_curve: mockCurve(6, 60, true),
    created_at: new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString(),
    decision: { action: "defer", reason: "Good strategy, wrong macro timing right now.", defer_condition: "Revisit when DXY > 104 and US 2Y yield breaks above 4.5%", timestamp: new Date(Date.now() - 12 * 24 * 60 * 60 * 1000).toISOString() },
  },
];

const SEED_MANDATES: Mandate[] = [
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

const SEED_ALERTS: OfficAlert[] = [
  {
    id: "alert-001",
    type: "strategy_surfaced",
    message: "Overnight loop surfaced 2 new strategies — HK Small Cap Momentum and Crypto Mean Reversion ready for review.",
    timestamp: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    read: false,
    strategy_id: "strat-001",
  },
  {
    id: "alert-002",
    type: "event_trigger",
    message: "Tariff escalation signal triggered. Macro Encoder built a systematic USD long strategy.",
    timestamp: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
    read: false,
    strategy_id: "strat-002",
  },
  {
    id: "alert-003",
    type: "book_update",
    message: "HK Momentum Factor #3 up +0.4% today. USD Carry Basket flat (-0.1%).",
    timestamp: new Date(Date.now() - 1 * 60 * 60 * 1000).toISOString(),
    read: false,
  },
  {
    id: "alert-004",
    type: "mandate_complete",
    message: "HK Small Cap Momentum Scan completed at 02:14 HKT. 3 candidates screened, 2 passed filters.",
    timestamp: new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString(),
    read: true,
  },
];

interface OfficeState {
  strategies: Strategy[];
  mandates: Mandate[];
  alerts: OfficAlert[];

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
}

export const useOfficeStore = create<OfficeState>()(
  persist(
    (set) => ({
      strategies: SEED_STRATEGIES,
      mandates: SEED_MANDATES,
      alerts: SEED_ALERTS,

      approveStrategy: (id, allocation_pct, reason) =>
        set((s: OfficeState) => ({
          strategies: s.strategies.map((st: Strategy) =>
            st.id === id
              ? {
                  ...st,
                  status: "live" as const,
                  allocation_pct,
                  live_since: new Date().toISOString(),
                  decision: { action: "approve" as const, reason, timestamp: new Date().toISOString(), allocation_pct },
                }
              : st
          ),
        })),

      rejectStrategy: (id, reason) =>
        set((s: OfficeState) => ({
          strategies: s.strategies.map((st: Strategy) =>
            st.id === id
              ? { ...st, status: "rejected" as const, decision: { action: "reject" as const, reason, timestamp: new Date().toISOString() } }
              : st
          ),
        })),

      deferStrategy: (id, reason, condition) =>
        set((s: OfficeState) => ({
          strategies: s.strategies.map((st: Strategy) =>
            st.id === id
              ? { ...st, status: "deferred" as const, decision: { action: "defer" as const, reason, defer_condition: condition, timestamp: new Date().toISOString() } }
              : st
          ),
        })),

      modifyStrategy: (id, instructions) =>
        set((s: OfficeState) => ({
          strategies: s.strategies.map((st: Strategy) =>
            st.id === id
              ? { ...st, decision: { action: "modify" as const, reason: instructions, timestamp: new Date().toISOString() } }
              : st
          ),
          alerts: [
            {
              id: `alert-mod-${id}`,
              type: "strategy_surfaced" as const,
              message: `Modification request sent to agent for "${s.strategies.find((x: Strategy) => x.id === id)?.name}". Will re-surface when ready.`,
              timestamp: new Date().toISOString(),
              read: false,
              strategy_id: id,
            },
            ...s.alerts,
          ],
        })),

      pauseStrategy: (id) =>
        set((s: OfficeState) => ({
          strategies: s.strategies.map((st: Strategy) => (st.id === id ? { ...st, status: "paused" as const } : st)),
        })),

      resumeStrategy: (id) =>
        set((s: OfficeState) => ({
          strategies: s.strategies.map((st: Strategy) => (st.id === id ? { ...st, status: "live" as const } : st)),
        })),

      resizeStrategy: (id, allocation_pct) =>
        set((s: OfficeState) => ({
          strategies: s.strategies.map((st: Strategy) => (st.id === id ? { ...st, allocation_pct } : st)),
        })),

      killStrategy: (id) =>
        set((s: OfficeState) => ({
          strategies: s.strategies.map((st: Strategy) =>
            st.id === id ? { ...st, status: "rejected" as const, decision: { action: "reject" as const, reason: "Manually killed by PM.", timestamp: new Date().toISOString() } } : st
          ),
        })),

      addMandate: (m) =>
        set((s: OfficeState) => ({
          mandates: [
            ...s.mandates,
            { ...m, id: `mand-${Date.now()}`, created_at: new Date().toISOString() },
          ],
        })),

      toggleMandate: (id) =>
        set((s: OfficeState) => ({
          mandates: s.mandates.map((m: Mandate) => (m.id === id ? { ...m, active: !m.active } : m)),
        })),

      deleteMandate: (id) =>
        set((s: OfficeState) => ({ mandates: s.mandates.filter((m: Mandate) => m.id !== id) })),

      markAlertRead: (id) =>
        set((s: OfficeState) => ({
          alerts: s.alerts.map((a: OfficAlert) => (a.id === id ? { ...a, read: true } : a)),
        })),

      markAllAlertsRead: () =>
        set((s: OfficeState) => ({ alerts: s.alerts.map((a: OfficAlert) => ({ ...a, read: true })) })),
    }),
    { name: "vibe-office-store" }
  )
);
