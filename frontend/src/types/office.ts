export type StrategyOrigin = "overnight_loop" | "mandate" | "event_trigger" | "manual";
export type StrategyStatus = "pending" | "approved" | "rejected" | "deferred" | "live" | "paused";
export type DecisionAction = "approve" | "reject" | "modify" | "defer";

export type AgentStatus = "idle" | "scanning" | "backtesting" | "encoding" | "surfacing" | "complete";

export interface StrategyMetrics {
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
  annual_return: number;
  total_return: number;
  trade_count: number;
}

export interface RegimePerformance {
  bull:     { return: number; win_rate: number };
  bear:     { return: number; win_rate: number };
  high_vol: { return: number; win_rate: number };
  low_vol:  { return: number; win_rate: number };
}

export interface StrategyDecision {
  action: DecisionAction;
  reason: string;
  timestamp: string;
  allocation_pct?: number;
  defer_condition?: string;
}

export interface EquityPoint { t: number; v: number; }

export interface Strategy {
  id: string;
  name: string;
  origin: StrategyOrigin;
  signal_logic: string;
  metrics: StrategyMetrics;
  regime_performance?: RegimePerformance;
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

export interface Agent {
  id: string;
  name: string;
  role: string;
  specialty: string;
  status: AgentStatus;
  current_task: string;
  progress: number;
  last_active: string;
  strategies_surfaced: number;
  backtests_run: number;
}

export interface ActivityEntry {
  id: string;
  agent_id: string;
  agent_name: string;
  message: string;
  timestamp: string;
  type: "scan" | "backtest" | "signal" | "complete" | "error" | "encode";
}

export interface DecisionRecord {
  id: string;
  timestamp: string;
  strategy_id: string;
  strategy_name: string;
  market: string;
  agent_id: string;
  action: DecisionAction;
  allocation_pct?: number;
  reason: string;
  defer_condition?: string;
  metrics: Pick<StrategyMetrics, "sharpe" | "max_drawdown" | "annual_return" | "win_rate">;
}
