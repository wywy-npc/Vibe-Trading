import { useState } from "react";
import { CheckCircle2, XCircle, Clock, Wrench, BookOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOfficeStore } from "@/stores/office";
import type { DecisionAction, DecisionRecord, Strategy } from "@/types/office";

type FilterTab = "all" | DecisionAction;

const ACTION_META: Record<DecisionAction, { label: string; icon: React.ReactNode; color: string; bg: string }> = {
  approve: { label: "Deployed",  icon: <CheckCircle2 className="h-3 w-3" />, color: "text-success", bg: "bg-success/10" },
  reject:  { label: "Declined",  icon: <XCircle      className="h-3 w-3" />, color: "text-danger",  bg: "bg-danger/10"  },
  defer:   { label: "Deferred",  icon: <Clock        className="h-3 w-3" />, color: "text-info",    bg: "bg-info/10"    },
  modify:  { label: "Modified",  icon: <Wrench       className="h-3 w-3" />, color: "text-warning", bg: "bg-warning/10" },
};

function fmtDate(iso: string) {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function daysAgo(iso: string) {
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  return d === 0 ? "Today" : d === 1 ? "Yesterday" : `${d}d ago`;
}

function OutcomeBadge({ record, strategies }: { record: DecisionRecord; strategies: Strategy[] }) {
  if (record.action !== "approve") return null;
  const s = strategies.find(x => x.id === record.strategy_id);
  if (!s) return <span className="text-[10px] text-muted-foreground/40">—</span>;

  if (s.status === "live") {
    const days = Math.floor((Date.now() - new Date(record.timestamp).getTime()) / 86400000);
    const pnl = s.daily_pnl;
    return (
      <div className="flex flex-col gap-0.5">
        <span className={cn("metric-val text-[10px] font-semibold", (pnl ?? 0) >= 0 ? "text-success" : "text-danger")}>
          {(pnl ?? 0) >= 0 ? "+" : ""}{(pnl ?? 0).toFixed(2)}% today
        </span>
        <span className="text-[9px] text-muted-foreground">{days}d live</span>
      </div>
    );
  }
  if (s.status === "paused") return <span className="text-[10px] text-warning">Paused</span>;
  if (s.status === "rejected") return <span className="text-[10px] text-danger">Killed</span>;
  return <span className="text-[10px] text-muted-foreground/40">—</span>;
}

export function Ledger() {
  const { decisions, strategies } = useOfficeStore();
  const [filter, setFilter] = useState<FilterTab>("all");

  const filtered = filter === "all" ? decisions : decisions.filter(d => d.action === filter);

  const counts: Record<FilterTab, number> = {
    all:     decisions.length,
    approve: decisions.filter(d => d.action === "approve").length,
    reject:  decisions.filter(d => d.action === "reject").length,
    defer:   decisions.filter(d => d.action === "defer").length,
    modify:  decisions.filter(d => d.action === "modify").length,
  };

  const FILTERS: { id: FilterTab; label: string }[] = [
    { id: "all",     label: "All" },
    { id: "approve", label: "Deployed" },
    { id: "reject",  label: "Declined" },
    { id: "defer",   label: "Deferred" },
    { id: "modify",  label: "Modified" },
  ];

  // Group by day for visual separation
  const grouped = filtered.reduce((acc: Record<string, DecisionRecord[]>, d) => {
    const day = fmtDate(d.timestamp);
    if (!acc[day]) acc[day] = [];
    acc[day].push(d);
    return acc;
  }, {});

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b bg-card/50 sticky top-0 z-10 backdrop-blur-sm">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h1 className="text-base font-semibold">Decision Ledger</h1>
              <p className="text-[10px] text-muted-foreground mt-0.5">
                Complete audit trail of all PM decisions
              </p>
            </div>

            {/* Summary chips */}
            <div className="flex items-center gap-2">
              {(["approve", "reject", "defer", "modify"] as DecisionAction[]).map(action => {
                const meta = ACTION_META[action];
                const count = counts[action];
                if (!count) return null;
                return (
                  <div key={action} className={cn("flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-semibold", meta.color, meta.bg)}>
                    {meta.icon}
                    <span className="metric-val">{count}</span>
                    <span>{meta.label}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Filter tabs */}
          <div className="flex gap-1">
            {FILTERS.map(f => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                className={cn(
                  "flex items-center gap-1.5 px-2.5 py-1 rounded text-[10px] font-semibold uppercase tracking-wide transition-colors",
                  filter === f.id ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted"
                )}
              >
                {f.label}
                {counts[f.id] > 0 && (
                  <span className={cn("h-4 min-w-4 px-1 rounded-full text-[9px] font-bold flex items-center justify-center",
                    filter === f.id ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                  )}>{counts[f.id]}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="px-6 py-4">
        {filtered.length === 0 ? (
          <div className="rounded-lg border border-dashed bg-card/30 p-12 text-center">
            <BookOpen className="h-5 w-5 text-muted-foreground/30 mx-auto mb-2" />
            <p className="text-sm font-medium">No decisions recorded</p>
            <p className="text-[10px] text-muted-foreground mt-1">Decisions made in the Inbox will appear here.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {Object.entries(grouped).map(([day, records]) => (
              <div key={day}>
                <div className="flex items-center gap-3 mb-2">
                  <span className="label-caps text-muted-foreground/60">{daysAgo(records[0].timestamp)} — {day}</span>
                  <div className="flex-1 h-px bg-border/40" />
                  <span className="text-[9px] text-muted-foreground/40">{records.length} decision{records.length > 1 ? "s" : ""}</span>
                </div>

                <div className="rounded-lg border bg-card overflow-hidden">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b bg-muted/20">
                        {[
                          { label: "Time",       cls: "text-left px-4 py-2.5 w-20" },
                          { label: "Strategy",   cls: "text-left px-4 py-2.5" },
                          { label: "Market",     cls: "text-left px-4 py-2.5 hidden sm:table-cell w-24" },
                          { label: "Agent",      cls: "text-left px-4 py-2.5 hidden md:table-cell w-32" },
                          { label: "Action",     cls: "text-left px-4 py-2.5 w-28" },
                          { label: "Alloc",      cls: "text-right px-4 py-2.5 hidden sm:table-cell w-16" },
                          { label: "Sharpe",     cls: "text-right px-4 py-2.5 hidden lg:table-cell w-16" },
                          { label: "Max DD",     cls: "text-right px-4 py-2.5 hidden lg:table-cell w-16" },
                          { label: "Ann Ret",    cls: "text-right px-4 py-2.5 hidden lg:table-cell w-16" },
                          { label: "Note",       cls: "text-left px-4 py-2.5" },
                          { label: "Outcome",    cls: "text-right px-4 py-2.5 w-28" },
                        ].map(({ label, cls }) => (
                          <th key={label} className={cn(cls, "label-caps")} style={{ fontSize: "9px" }}>{label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {records.map((d, i) => {
                        const meta = ACTION_META[d.action];
                        return (
                          <tr key={d.id} className={cn("border-b border-border/40 last:border-0 hover:bg-muted/10 transition-colors", i % 2 === 1 && "bg-muted/5")}>

                            {/* Time */}
                            <td className="px-4 py-3">
                              <span className="metric-val text-[10px] text-muted-foreground">{fmtTime(d.timestamp)}</span>
                            </td>

                            {/* Strategy */}
                            <td className="px-4 py-3">
                              <p className="text-xs font-medium leading-tight">{d.strategy_name}</p>
                            </td>

                            {/* Market */}
                            <td className="px-4 py-3 hidden sm:table-cell">
                              <span className="text-[10px] text-muted-foreground">{d.market || "—"}</span>
                            </td>

                            {/* Agent */}
                            <td className="px-4 py-3 hidden md:table-cell">
                              <span className="text-[10px] text-muted-foreground font-mono">{d.agent_id || "—"}</span>
                            </td>

                            {/* Action badge */}
                            <td className="px-4 py-3">
                              <span className={cn("inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold", meta.color, meta.bg)}>
                                {meta.icon}{meta.label}
                              </span>
                            </td>

                            {/* Allocation */}
                            <td className="px-4 py-3 text-right hidden sm:table-cell">
                              <span className="metric-val text-[10px] font-semibold">
                                {d.allocation_pct != null ? `${d.allocation_pct}%` : "—"}
                              </span>
                            </td>

                            {/* Metrics at decision time */}
                            <td className="px-4 py-3 text-right hidden lg:table-cell">
                              <span className={cn("metric-val text-[10px] font-semibold",
                                d.metrics.sharpe >= 1.2 ? "text-success" : "text-warning"
                              )}>{d.metrics.sharpe.toFixed(2)}</span>
                            </td>
                            <td className="px-4 py-3 text-right hidden lg:table-cell">
                              <span className={cn("metric-val text-[10px] font-semibold",
                                Math.abs(d.metrics.max_drawdown) <= 10 ? "text-success" : "text-warning"
                              )}>{d.metrics.max_drawdown.toFixed(1)}%</span>
                            </td>
                            <td className="px-4 py-3 text-right hidden lg:table-cell">
                              <span className={cn("metric-val text-[10px] font-semibold",
                                d.metrics.annual_return >= 0 ? "text-success" : "text-danger"
                              )}>
                                {d.metrics.annual_return >= 0 ? "+" : ""}{d.metrics.annual_return.toFixed(1)}%
                              </span>
                            </td>

                            {/* Reason / note */}
                            <td className="px-4 py-3 max-w-[200px]">
                              <p className="text-[10px] text-muted-foreground leading-snug line-clamp-2">
                                {d.reason || "—"}
                              </p>
                              {d.defer_condition && (
                                <p className="text-[10px] text-info mt-0.5 leading-snug line-clamp-1">
                                  ↳ {d.defer_condition}
                                </p>
                              )}
                            </td>

                            {/* Outcome */}
                            <td className="px-4 py-3 text-right">
                              <OutcomeBadge record={d} strategies={strategies} />
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
