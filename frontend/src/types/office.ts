export type StrategyOrigin = "overnight_loop" | "mandate" | "event_trigger" | "manual";
export type StrategyStatus = "pending" | "approved" | "rejected" | "deferred" | "live" | "paused";
export type DecisionAction = "approve" | "reject" | "modify" | "defer";

export interface StrategyMetrics {
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
  annual_return: number;
  total_return: number;
  trade_count: number;
}

export interface StrategyDecision {
  action: DecisionAction;
  reason: string;
  timestamp: string;
  allocation_pct?: number;
  defer_condition?: string;
}

export interface EquityPoint {
  t: number;
  v: number;
}

export interface Strategy {
  id: string;
  name: string;
  origin: StrategyOrigin;
  signal_logic: string;
  metrics: StrategyMetrics;
  risk_flags: string[];
  status: StrategyStatus;
  allocation_pct?: number;
  decision?: StrategyDecision;
  equity_curve: EquityPoint[];
  created_at: string;
  agent_id?: string;
  run_id?: string;
  market?: string;
  live_since?: string;
  daily_pnl?: number;
}

export interface Mandate {
  id: string;
  name: string;
  description: string;
  markets: string[];
  signal_types: string[];
  min_sharpe: number;
  max_drawdown_limit: number;
  active: boolean;
  schedule: string;
  created_at: string;
  last_run?: string;
  strategies_found?: number;
}

export interface OfficAlert {
  id: string;
  type: "strategy_surfaced" | "event_trigger" | "risk_alert" | "mandate_complete" | "book_update";
  message: string;
  timestamp: string;
  read: boolean;
  strategy_id?: string;
}
