import { useState } from "react";
import { ChevronDown, ChevronUp, Zap, Moon, Radio, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Strategy, StrategyOrigin } from "@/types/office";
import { MiniSparkline } from "./MiniSparkline";
import { DecisionModal } from "./DecisionModal";
import { useOfficeStore } from "@/stores/office";

const ORIGIN_META: Record<StrategyOrigin, { label: string; icon: React.ReactNode; color: string }> = {
  overnight_loop: { label: "Loop",    icon: <Moon className="h-2.5 w-2.5" />, color: "text-info bg-info/10" },
  mandate:        { label: "Mandate", icon: <Radio className="h-2.5 w-2.5" />, color: "text-primary bg-primary/10" },
  event_trigger:  { label: "Event",   icon: <Zap className="h-2.5 w-2.5" />,  color: "text-warning bg-warning/10" },
  manual:         { label: "Manual",  icon: null,                               color: "text-muted-foreground bg-muted" },
};

const REGIME_LABELS = [
  { key: "bull"     as const, label: "Bull" },
  { key: "bear"     as const, label: "Bear" },
  { key: "high_vol" as const, label: "Hi-Vol" },
  { key: "low_vol"  as const, label: "Lo-Vol" },
];

interface Props {
  strategy: Strategy;
  selected?: boolean;
  onClick?: () => void;
}

export function StrategyCard({ strategy, selected, onClick }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [showDecision, setShowDecision] = useState(false);
  const { approveStrategy, rejectStrategy, deferStrategy, modifyStrategy } = useOfficeStore();
  const isUp = strategy.metrics.annual_return >= 0;

  return (
    <>
      <div
        className={cn(
          "rounded-lg border bg-card transition-all cursor-pointer",
          selected ? "border-primary/50 bg-primary/5" : "hover:border-border/80",
        )}
        onClick={onClick}
      >
        {/* Header */}
        <div className="p-3">
          <div className="flex items-start gap-2 mb-2.5">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 mb-1">
                <span className={cn("inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wide", ORIGIN_META[strategy.origin].color)}>
                  {ORIGIN_META[strategy.origin].icon}
                  {ORIGIN_META[strategy.origin].label}
                </span>
                {strategy.market && (
                  <span className="text-[10px] text-muted-foreground">{strategy.market}</span>
                )}
                <span className="text-[10px] text-muted-foreground/40 ml-auto">{strategy.agent_id}</span>
              </div>
              <h3 className="text-sm font-semibold leading-tight">{strategy.name}</h3>
            </div>
            <MiniSparkline data={strategy.equity_curve} width={72} height={28} positive={isUp} />
          </div>

          {/* 4 key metrics — monospaced, tabular */}
          <div className="grid grid-cols-4 gap-1.5">
            {[
              { label: "SR",   value: strategy.metrics.sharpe.toFixed(2),            color: strategy.metrics.sharpe >= 1.2 ? "text-success" : strategy.metrics.sharpe >= 0.8 ? "text-warning" : "text-danger" },
              { label: "DD",   value: `${strategy.metrics.max_drawdown.toFixed(1)}%`, color: Math.abs(strategy.metrics.max_drawdown) <= 10 ? "text-success" : "text-warning" },
              { label: "W%",   value: `${strategy.metrics.win_rate.toFixed(0)}%`,     color: "text-foreground" },
              { label: "Ann",  value: `${isUp ? "+" : ""}${strategy.metrics.annual_return.toFixed(1)}%`, color: isUp ? "text-success" : "text-danger" },
            ].map(({ label, value, color }) => (
              <div key={label} className="bg-muted/30 rounded px-1.5 py-1.5 text-center">
                <div className={cn("metric-val text-xs font-semibold", color)}>{value}</div>
                <div className="label-caps mt-0.5" style={{ fontSize: "9px" }}>{label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Regime grid */}
        {strategy.regime_performance && (
          <div className="px-3 pb-2">
            <div className="grid grid-cols-4 gap-1">
              {REGIME_LABELS.map(({ key, label }) => {
                const r = strategy.regime_performance![key];
                const pos = r.return >= 0;
                return (
                  <div key={key} className="bg-muted/20 rounded px-1 py-1 text-center">
                    <div className={cn("metric-val text-[10px] font-semibold", pos ? "text-success" : "text-danger")}>
                      {pos ? "+" : ""}{r.return.toFixed(0)}%
                    </div>
                    <div className="label-caps mt-0.5" style={{ fontSize: "8.5px" }}>{label}</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Risk flags */}
        {strategy.risk_flags.length > 0 && (
          <div className="px-3 pb-2 space-y-1">
            {strategy.risk_flags.map(f => (
              <div key={f} className="flex items-center gap-1.5 text-[10px] text-warning">
                <AlertTriangle className="h-2.5 w-2.5 shrink-0" />{f}
              </div>
            ))}
          </div>
        )}

        {/* Signal logic — expandable */}
        <div className="border-t border-border/50">
          <button
            className="w-full flex items-center justify-between px-3 py-1.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
            onClick={e => { e.stopPropagation(); setExpanded(!expanded); }}
          >
            <span className="label-caps" style={{ fontSize: "9px" }}>Signal logic</span>
            {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
          {expanded && (
            <div className="px-3 pb-2.5">
              <p className="text-[10px] text-muted-foreground leading-relaxed prose-dense">{strategy.signal_logic}</p>
            </div>
          )}
        </div>

        {/* Quick actions — pending only */}
        {strategy.status === "pending" && (
          <div className="border-t border-border/50 p-2 grid grid-cols-3 gap-1.5">
            <button
              onClick={e => { e.stopPropagation(); approveStrategy(strategy.id, 5, "Quick approved."); }}
              className="py-1.5 rounded bg-success/10 text-success text-[10px] font-semibold hover:bg-success/20 transition-colors"
            >
              Deploy
            </button>
            <button
              onClick={e => { e.stopPropagation(); setShowDecision(true); }}
              className="py-1.5 rounded bg-muted text-muted-foreground text-[10px] font-semibold hover:bg-muted/80 transition-colors"
            >
              Review
            </button>
            <button
              onClick={e => { e.stopPropagation(); rejectStrategy(strategy.id, "Declined."); }}
              className="py-1.5 rounded bg-danger/10 text-danger text-[10px] font-semibold hover:bg-danger/20 transition-colors"
            >
              Decline
            </button>
          </div>
        )}
      </div>

      {showDecision && (
        <DecisionModal
          strategy={strategy}
          onApprove={(alloc, reason) => approveStrategy(strategy.id, alloc, reason)}
          onReject={reason => rejectStrategy(strategy.id, reason)}
          onModify={instructions => modifyStrategy(strategy.id, instructions)}
          onDefer={(reason, condition) => deferStrategy(strategy.id, reason, condition)}
          onClose={() => setShowDecision(false)}
        />
      )}
    </>
  );
}
