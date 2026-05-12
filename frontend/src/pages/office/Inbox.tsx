import { useState, useEffect, useCallback } from "react";
import { CheckCircle2, Keyboard } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOfficeStore } from "@/stores/office";
import { StrategyCard } from "@/components/office/StrategyCard";
import { DecisionModal } from "@/components/office/DecisionModal";
import { MiniSparkline } from "@/components/office/MiniSparkline";
import type { Strategy } from "@/types/office";

type FilterTab = "pending" | "deferred" | "rejected" | "all";

const REGIME_LABELS = [
  { key: "bull" as const, label: "Bull" },
  { key: "bear" as const, label: "Bear" },
  { key: "high_vol" as const, label: "Hi-Vol" },
  { key: "low_vol" as const, label: "Lo-Vol" },
];

export function Inbox() {
  const { strategies, approveStrategy, rejectStrategy, deferStrategy, modifyStrategy } = useOfficeStore();
  const [filter, setFilter] = useState<FilterTab>("pending");
  const [selected, setSelected] = useState<Strategy | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [modalTab, setModalTab] = useState<"approve" | "reject" | "modify" | "defer">("approve");
  const [showKeys, setShowKeys] = useState(false);

  const filtered = strategies.filter(s =>
    filter === "all" ? !["live", "paused"].includes(s.status) : s.status === filter
  );

  const pending = strategies.filter(s => s.status === "pending");

  // Auto-select first pending on mount
  useEffect(() => {
    if (!selected && pending.length > 0) setSelected(pending[0]);
  }, []);

  // Keyboard navigation
  const handleKey = useCallback((e: KeyboardEvent) => {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
    if (showModal) return;

    const list = filtered;
    const idx = list.findIndex(s => s.id === selected?.id);

    if (e.key === "j" || e.key === "ArrowDown") {
      e.preventDefault();
      if (idx < list.length - 1) setSelected(list[idx + 1]);
    } else if (e.key === "k" || e.key === "ArrowUp") {
      e.preventDefault();
      if (idx > 0) setSelected(list[idx - 1]);
    } else if (selected?.status === "pending") {
      if (e.key === "a") { setModalTab("approve"); setShowModal(true); }
      else if (e.key === "r") { setModalTab("reject"); setShowModal(true); }
      else if (e.key === "m") { setModalTab("modify"); setShowModal(true); }
      else if (e.key === "d") { setModalTab("defer"); setShowModal(true); }
    }
    if (e.key === "?") setShowKeys(v => !v);
  }, [filtered, selected, showModal]);

  useEffect(() => {
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  const FILTERS: { id: FilterTab; label: string; count?: number }[] = [
    { id: "pending",  label: "Pending",  count: strategies.filter(s => s.status === "pending").length },
    { id: "deferred", label: "Deferred", count: strategies.filter(s => s.status === "deferred").length },
    { id: "rejected", label: "Declined", count: strategies.filter(s => s.status === "rejected").length },
    { id: "all",      label: "All" },
  ];

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <div className="border-b bg-card/50 sticky top-0 z-10 backdrop-blur-sm">
        <div className="px-5 py-3 flex items-center justify-between">
          <div>
            <h1 className="text-base font-semibold">Inbox</h1>
            <p className="text-[10px] text-muted-foreground mt-0.5">
              {pending.length > 0
                ? `${pending.length} ${pending.length === 1 ? "signal" : "signals"} awaiting decision`
                : "All signals reviewed"}
            </p>
          </div>
          <button
            onClick={() => setShowKeys(v => !v)}
            className="flex items-center gap-1.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          >
            <Keyboard className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Shortcuts</span>
          </button>
        </div>

        {/* Keyboard shortcut legend */}
        {showKeys && (
          <div className="px-5 pb-2 flex items-center gap-4">
            {[
              { key: "J/K", desc: "Navigate" },
              { key: "A", desc: "Deploy" },
              { key: "R", desc: "Decline" },
              { key: "M", desc: "Modify" },
              { key: "D", desc: "Defer" },
              { key: "?", desc: "Toggle" },
            ].map(({ key, desc }) => (
              <div key={key} className="flex items-center gap-1">
                <kbd className="px-1.5 py-0.5 rounded border border-border bg-muted text-[10px] font-mono font-semibold">{key}</kbd>
                <span className="text-[10px] text-muted-foreground">{desc}</span>
              </div>
            ))}
          </div>
        )}

        {/* Filter tabs */}
        <div className="px-5 flex gap-1 pb-2">
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
              {f.count !== undefined && f.count > 0 && (
                <span className={cn("h-4 min-w-4 px-1 rounded-full text-[9px] font-bold flex items-center justify-center",
                  filter === f.id ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                )}>{f.count}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 flex overflow-hidden">
        {filtered.length === 0 ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <CheckCircle2 className="h-6 w-6 text-success mx-auto mb-2 opacity-60" />
              <p className="text-sm font-medium">{filter === "pending" ? "Nothing pending" : `No ${filter} signals`}</p>
              <p className="text-[10px] text-muted-foreground mt-1">
                {filter === "pending" ? "Agents are running. New signals surface when they clear threshold." : ""}
              </p>
            </div>
          </div>
        ) : (
          <div className="flex flex-1 overflow-hidden">
            {/* Strategy list */}
            <div className="w-72 shrink-0 border-r overflow-y-auto p-3 space-y-2">
              {filtered.map((s, i) => (
                <div key={s.id} className="relative">
                  {i === 0 && filter === "pending" && (
                    <div className="absolute -top-0.5 -right-0.5 z-10">
                      <span className="text-[8px] px-1 py-0.5 rounded-br rounded-tl bg-muted text-muted-foreground/60 font-mono">J/K</span>
                    </div>
                  )}
                  <StrategyCard strategy={s} selected={selected?.id === s.id} onClick={() => setSelected(s)} />
                </div>
              ))}
            </div>

            {/* Detail panel */}
            <div className="flex-1 overflow-y-auto p-4">
              {selected ? (
                <div className="max-w-2xl space-y-3">

                  {/* Detail header */}
                  <div className="rounded-lg border bg-card p-4">
                    <div className="flex items-start justify-between gap-3 mb-3">
                      <div>
                        <p className="label-caps mb-1">{selected.market} · {selected.agent_id}</p>
                        <h2 className="text-base font-semibold">{selected.name}</h2>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={cn("px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide",
                          selected.status === "pending"  && "bg-primary/10 text-primary",
                          selected.status === "deferred" && "bg-info/10 text-info",
                          selected.status === "rejected" && "bg-danger/10 text-danger",
                          selected.status === "live"     && "bg-success/10 text-success",
                        )}>
                          {selected.status}
                        </span>
                      </div>
                    </div>
                    {/* Equity curve */}
                    <div className="h-20 w-full">
                      <MiniSparkline data={selected.equity_curve} width={600} height={80} positive={selected.metrics.annual_return >= 0} />
                    </div>
                  </div>

                  {/* Metrics */}
                  <div className="rounded-lg border bg-card p-4">
                    <p className="label-caps mb-3">Performance</p>
                    <div className="grid grid-cols-3 gap-2">
                      {[
                        { label: "Sharpe",       v: selected.metrics.sharpe.toFixed(2),                   hi: selected.metrics.sharpe >= 1.2 },
                        { label: "Max DD",       v: `${selected.metrics.max_drawdown.toFixed(1)}%`,        hi: Math.abs(selected.metrics.max_drawdown) < 10 },
                        { label: "Win Rate",     v: `${selected.metrics.win_rate.toFixed(1)}%`,            hi: selected.metrics.win_rate > 55 },
                        { label: "Ann. Return",  v: `${selected.metrics.annual_return >= 0 ? "+" : ""}${selected.metrics.annual_return.toFixed(1)}%`, hi: selected.metrics.annual_return > 15 },
                        { label: "Total Return", v: `${selected.metrics.total_return >= 0 ? "+" : ""}${selected.metrics.total_return.toFixed(1)}%`,   hi: selected.metrics.total_return > 0 },
                        { label: "Trades",       v: String(selected.metrics.trade_count),                  hi: true },
                      ].map(({ label, v, hi }) => (
                        <div key={label} className="bg-muted/30 rounded-lg p-2.5">
                          <div className={cn("metric-val text-sm font-semibold", hi ? "text-success" : "text-danger")}>{v}</div>
                          <div className="label-caps mt-0.5">{label}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Regime breakdown */}
                  {selected.regime_performance && (
                    <div className="rounded-lg border bg-card p-4">
                      <p className="label-caps mb-3">Regime Performance</p>
                      <div className="grid grid-cols-4 gap-2">
                        {REGIME_LABELS.map(({ key, label }) => {
                          const r = selected.regime_performance![key];
                          return (
                            <div key={key} className="bg-muted/30 rounded-lg p-2.5 text-center">
                              <div className={cn("metric-val text-sm font-semibold", r.return >= 0 ? "text-success" : "text-danger")}>
                                {r.return >= 0 ? "+" : ""}{r.return.toFixed(1)}%
                              </div>
                              <div className="label-caps mt-0.5">{label}</div>
                              <div className="text-[10px] text-muted-foreground mt-0.5">{r.win_rate}% win</div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Risk flags */}
                  {selected.risk_flags.length > 0 && (
                    <div className="rounded-lg border border-warning/30 bg-warning/5 p-4 space-y-2">
                      <p className="label-caps text-warning">Risk Flags</p>
                      {selected.risk_flags.map(f => (
                        <p key={f} className="text-xs text-warning leading-snug">⚠ {f}</p>
                      ))}
                    </div>
                  )}

                  {/* Signal logic */}
                  <div className="rounded-lg border bg-card p-4">
                    <p className="label-caps mb-2">Signal Logic</p>
                    <p className="text-xs text-muted-foreground leading-relaxed prose-dense">{selected.signal_logic}</p>
                  </div>

                  {/* Prior decision */}
                  {selected.decision && (
                    <div className="rounded-lg border bg-card p-4">
                      <p className="label-caps mb-2">Prior Decision</p>
                      <div className="bg-muted/30 rounded-lg p-3 space-y-1">
                        <p className="text-xs font-semibold capitalize">{selected.decision.action}</p>
                        {selected.decision.reason && <p className="text-[10px] text-muted-foreground">{selected.decision.reason}</p>}
                        {selected.decision.defer_condition && (
                          <p className="text-[10px] text-info mt-1">Condition: {selected.decision.defer_condition}</p>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Action bar */}
                  {selected.status === "pending" && (
                    <div className="grid grid-cols-4 gap-2">
                      {[
                        { label: "Deploy",  key: "A", action: () => { setModalTab("approve"); setShowModal(true); }, color: "bg-success/10 text-success hover:bg-success/20 border-success/20" },
                        { label: "Decline", key: "R", action: () => { setModalTab("reject");  setShowModal(true); }, color: "bg-danger/10 text-danger hover:bg-danger/20 border-danger/20" },
                        { label: "Modify",  key: "M", action: () => { setModalTab("modify");  setShowModal(true); }, color: "bg-warning/10 text-warning hover:bg-warning/20 border-warning/20" },
                        { label: "Defer",   key: "D", action: () => { setModalTab("defer");   setShowModal(true); }, color: "bg-info/10 text-info hover:bg-info/20 border-info/20" },
                      ].map(({ label, key, action, color }) => (
                        <button key={label} onClick={action}
                          className={cn("py-2.5 rounded-lg border text-xs font-semibold uppercase tracking-wide transition-colors flex flex-col items-center gap-0.5", color)}>
                          {label}
                          <kbd className="text-[8px] opacity-50 font-mono">{key}</kbd>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex items-center justify-center h-40">
                  <p className="text-xs text-muted-foreground">Select a signal to review</p>
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
          onReject={reason => { rejectStrategy(selected.id, reason); setSelected(null); }}
          onModify={instructions => { modifyStrategy(selected.id, instructions); setSelected(null); }}
          onDefer={(reason, condition) => { deferStrategy(selected.id, reason, condition); setSelected(null); }}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  );
}
