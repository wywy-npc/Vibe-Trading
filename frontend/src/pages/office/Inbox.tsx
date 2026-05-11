import { useState } from "react";
import { Filter, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOfficeStore } from "@/stores/office";
import { StrategyCard } from "@/components/office/StrategyCard";
import { DecisionModal } from "@/components/office/DecisionModal";
import type { Strategy } from "@/types/office";

type Filter = "pending" | "deferred" | "rejected" | "all";

export function Inbox() {
  const { strategies, approveStrategy, rejectStrategy, deferStrategy, modifyStrategy } = useOfficeStore();
  const [filter, setFilter] = useState<Filter>("pending");
  const [selected, setSelected] = useState<Strategy | null>(null);
  const [showModal, setShowModal] = useState(false);

  const filtered = strategies.filter((s) => {
    if (filter === "all") return !["live", "paused"].includes(s.status);
    return s.status === filter;
  });

  const pending = strategies.filter((s) => s.status === "pending");

  const FILTERS: { id: Filter; label: string; count?: number }[] = [
    { id: "pending",  label: "Pending",  count: strategies.filter(s => s.status === "pending").length },
    { id: "deferred", label: "Deferred", count: strategies.filter(s => s.status === "deferred").length },
    { id: "rejected", label: "Rejected", count: strategies.filter(s => s.status === "rejected").length },
    { id: "all",      label: "All" },
  ];

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b bg-card/50 sticky top-0 z-10 backdrop-blur-sm">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">Inbox</h1>
            <p className="text-xs text-muted-foreground mt-0.5">
              {pending.length > 0
                ? `${pending.length} ${pending.length === 1 ? "strategy" : "strategies"} awaiting your decision`
                : "All strategies reviewed"}
            </p>
          </div>
          <Filter className="h-4 w-4 text-muted-foreground" />
        </div>

        {/* Filter tabs */}
        <div className="max-w-5xl mx-auto px-6 flex gap-1 pb-2">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                filter === f.id
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted"
              )}
            >
              {f.label}
              {f.count !== undefined && f.count > 0 && (
                <span className={cn(
                  "h-4 min-w-4 px-1 rounded-full text-[10px] font-bold flex items-center justify-center",
                  filter === f.id ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                )}>
                  {f.count}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-6">
        {filtered.length === 0 ? (
          <div className="rounded-xl border border-dashed bg-card/50 p-12 text-center">
            <CheckCircle2 className="h-8 w-8 text-success mx-auto mb-3 opacity-60" />
            <p className="text-sm font-medium">
              {filter === "pending" ? "Nothing pending" : `No ${filter} strategies`}
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              {filter === "pending" ? "Agents are running. Check back after the next loop." : ""}
            </p>
          </div>
        ) : (
          /* Two-column layout: list + detail */
          <div className="flex gap-4">
            {/* Strategy list */}
            <div className="w-80 shrink-0 space-y-3">
              {filtered.map((s) => (
                <div key={s.id} onClick={() => setSelected(s)} className="cursor-pointer">
                  <StrategyCard
                    strategy={s}
                    selected={selected?.id === s.id}
                  />
                </div>
              ))}
            </div>

            {/* Detail panel */}
            <div className="flex-1 min-w-0">
              {selected ? (
                <div className="rounded-xl border bg-card sticky top-[88px]">
                  {/* Detail header */}
                  <div className="p-5 border-b">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">{selected.market} · {selected.agent_id}</p>
                        <h2 className="text-base font-semibold">{selected.name}</h2>
                      </div>
                      <span className={cn(
                        "px-2 py-0.5 rounded-full text-xs font-medium",
                        selected.status === "pending"  && "bg-primary/10 text-primary",
                        selected.status === "deferred" && "bg-info/10 text-info",
                        selected.status === "rejected" && "bg-danger/10 text-danger",
                      )}>
                        {selected.status}
                      </span>
                    </div>
                  </div>

                  {/* Full metrics grid */}
                  <div className="p-5 border-b">
                    <p className="text-xs font-medium text-muted-foreground mb-3">Performance</p>
                    <div className="grid grid-cols-3 gap-2">
                      {[
                        { label: "Sharpe",      v: selected.metrics.sharpe.toFixed(2), hi: selected.metrics.sharpe >= 1.2 },
                        { label: "Max DD",      v: `${selected.metrics.max_drawdown.toFixed(1)}%`, hi: Math.abs(selected.metrics.max_drawdown) < 10 },
                        { label: "Win Rate",    v: `${selected.metrics.win_rate.toFixed(1)}%`, hi: selected.metrics.win_rate > 55 },
                        { label: "Ann. Return", v: `${selected.metrics.annual_return >= 0 ? "+" : ""}${selected.metrics.annual_return.toFixed(1)}%`, hi: selected.metrics.annual_return > 15 },
                        { label: "Total Return",v: `${selected.metrics.total_return >= 0 ? "+" : ""}${selected.metrics.total_return.toFixed(1)}%`, hi: selected.metrics.total_return > 0 },
                        { label: "Trades",      v: String(selected.metrics.trade_count), hi: true },
                      ].map(({ label, v, hi }) => (
                        <div key={label} className="bg-muted/40 rounded-lg p-3">
                          <div className={cn("text-base font-semibold font-mono", hi ? "text-success" : "text-danger")}>{v}</div>
                          <div className="text-[10px] text-muted-foreground mt-0.5">{label}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Risk flags */}
                  {selected.risk_flags.length > 0 && (
                    <div className="p-5 border-b space-y-2">
                      <p className="text-xs font-medium text-muted-foreground">Risk Flags</p>
                      {selected.risk_flags.map((f) => (
                        <div key={f} className="flex items-start gap-2 p-2.5 rounded-lg bg-warning/10 text-warning text-xs">
                          <span className="shrink-0 mt-0.5">⚠</span>
                          {f}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Signal logic */}
                  <div className="p-5 border-b">
                    <p className="text-xs font-medium text-muted-foreground mb-2">Signal Logic</p>
                    <p className="text-sm leading-relaxed text-muted-foreground">{selected.signal_logic}</p>
                  </div>

                  {/* Prior decision */}
                  {selected.decision && (
                    <div className="p-5 border-b">
                      <p className="text-xs font-medium text-muted-foreground mb-2">Previous Decision</p>
                      <div className="bg-muted/30 rounded-lg p-3 space-y-1">
                        <p className="text-xs font-medium capitalize">{selected.decision.action}</p>
                        {selected.decision.reason && <p className="text-xs text-muted-foreground">{selected.decision.reason}</p>}
                        {selected.decision.defer_condition && (
                          <p className="text-xs text-info mt-1">Condition: {selected.decision.defer_condition}</p>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Action bar */}
                  {selected.status === "pending" && (
                    <div className="p-4">
                      <button
                        onClick={() => setShowModal(true)}
                        className="w-full py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity"
                      >
                        Make Decision
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <div className="rounded-xl border border-dashed bg-card/50 p-12 text-center">
                  <p className="text-sm text-muted-foreground">Select a strategy to review details</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {showModal && selected && (
        <DecisionModal
          strategy={selected}
          onApprove={(alloc, reason) => { approveStrategy(selected.id, alloc, reason); setSelected(null); }}
          onReject={(reason) => { rejectStrategy(selected.id, reason); setSelected(null); }}
          onModify={(instructions) => { modifyStrategy(selected.id, instructions); setSelected(null); }}
          onDefer={(reason, condition) => { deferStrategy(selected.id, reason, condition); setSelected(null); }}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  );
}
