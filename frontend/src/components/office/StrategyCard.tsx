import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronUp, Zap, Moon, Radio } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Strategy, StrategyOrigin } from "@/types/office";
import { MiniSparkline } from "./MiniSparkline";
import { DecisionModal } from "./DecisionModal";
import { useOfficeStore } from "@/stores/office";

interface Props {
  strategy: Strategy;
  selected?: boolean;
  onClick?: () => void;
}

const ORIGIN_META: Record<StrategyOrigin, { label: string; icon: React.ReactNode; color: string }> = {
  overnight_loop: { label: "Overnight Loop", icon: <Moon className="h-3 w-3" />, color: "text-info bg-info/10" },
  mandate:        { label: "Mandate",        icon: <Radio className="h-3 w-3" />, color: "text-primary bg-primary/10" },
  event_trigger:  { label: "Event Trigger",  icon: <Zap className="h-3 w-3" />,  color: "text-warning bg-warning/10" },
  manual:         { label: "Manual",         icon: null,                           color: "text-muted-foreground bg-muted" },
};

function fmt(n: number, suffix = "%") {
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}${suffix}`;
}

export function StrategyCard({ strategy, selected, onClick }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [showDecision, setShowDecision] = useState(false);
  const { approveStrategy, rejectStrategy, deferStrategy, modifyStrategy } = useOfficeStore();
  const origin = ORIGIN_META[strategy.origin];
  const isUp = strategy.metrics.annual_return >= 0;

  return (
    <>
      <div
        className={cn(
          "rounded-xl border bg-card transition-all",
          selected ? "border-primary ring-1 ring-primary/30" : "hover:border-border/80",
          onClick && "cursor-pointer"
        )}
        onClick={onClick}
      >
        {/* Header row */}
        <div className="p-4 pb-3">
          <div className="flex items-start justify-between gap-3 mb-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className={cn("inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium", origin.color)}>
                  {origin.icon}
                  {origin.label}
                </span>
                {strategy.market && (
                  <span className="text-[10px] text-muted-foreground">{strategy.market}</span>
                )}
              </div>
              <h3 className="font-semibold text-sm leading-tight truncate">{strategy.name}</h3>
              <p className="text-[10px] text-muted-foreground mt-0.5">
                {new Date(strategy.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · {strategy.agent_id ?? "agent"}
              </p>
            </div>
            <MiniSparkline data={strategy.equity_curve} width={100} height={36} positive={isUp} />
          </div>

          {/* 4 key metrics */}
          <div className="grid grid-cols-4 gap-2">
            {[
              { label: "Sharpe", value: strategy.metrics.sharpe.toFixed(2), color: strategy.metrics.sharpe >= 1.2 ? "text-success" : strategy.metrics.sharpe >= 0.8 ? "text-warning" : "text-danger" },
              { label: "Max DD",  value: fmt(strategy.metrics.max_drawdown), color: Math.abs(strategy.metrics.max_drawdown) <= 10 ? "text-success" : "text-warning" },
              { label: "Win Rate", value: `${strategy.metrics.win_rate.toFixed(0)}%`, color: "text-foreground" },
              { label: "Ann. Return", value: fmt(strategy.metrics.annual_return), color: isUp ? "text-success" : "text-danger" },
            ].map(({ label, value, color }) => (
              <div key={label} className="bg-muted/40 rounded-lg p-2 text-center">
                <div className={cn("text-sm font-semibold font-mono", color)}>{value}</div>
                <div className="text-[10px] text-muted-foreground mt-0.5">{label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Risk flags */}
        {strategy.risk_flags.length > 0 && (
          <div className="px-4 pb-2 space-y-1">
            {strategy.risk_flags.map((f) => (
              <div key={f} className="flex items-center gap-1.5 text-[11px] text-warning">
                <AlertTriangle className="h-3 w-3 shrink-0" />
                {f}
              </div>
            ))}
          </div>
        )}

        {/* Expandable signal logic */}
        <div className="border-t">
          <button
            className="w-full flex items-center justify-between px-4 py-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
          >
            <span>Signal logic</span>
            {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
          {expanded && (
            <div className="px-4 pb-3">
              <p className="text-xs text-muted-foreground leading-relaxed">{strategy.signal_logic}</p>
            </div>
          )}
        </div>

        {/* Action bar — only for pending strategies */}
        {strategy.status === "pending" && (
          <div className="border-t p-3 flex gap-2">
            <button
              onClick={(e) => { e.stopPropagation(); useOfficeStore.getState().approveStrategy(strategy.id, 5, "Quick approved."); }}
              className="flex-1 py-1.5 rounded-lg bg-success/10 text-success text-xs font-medium hover:bg-success/20 transition-colors"
            >
              Approve
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setShowDecision(true); }}
              className="flex-1 py-1.5 rounded-lg bg-muted text-muted-foreground text-xs font-medium hover:bg-muted/80 transition-colors"
            >
              Review
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); useOfficeStore.getState().rejectStrategy(strategy.id, "Rejected."); }}
              className="flex-1 py-1.5 rounded-lg bg-danger/10 text-danger text-xs font-medium hover:bg-danger/20 transition-colors"
            >
              Reject
            </button>
          </div>
        )}
      </div>

      {showDecision && (
        <DecisionModal
          strategy={strategy}
          onApprove={(alloc, reason) => approveStrategy(strategy.id, alloc, reason)}
          onReject={(reason) => rejectStrategy(strategy.id, reason)}
          onModify={(instructions) => modifyStrategy(strategy.id, instructions)}
          onDefer={(reason, condition) => deferStrategy(strategy.id, reason, condition)}
          onClose={() => setShowDecision(false)}
        />
      )}
    </>
  );
}
