import { useState } from "react";
import { Pause, Play, Trash2, SlidersHorizontal, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOfficeStore } from "@/stores/office";
import { MiniSparkline } from "@/components/office/MiniSparkline";
import type { Strategy } from "@/types/office";

function fmtPnl(n?: number) {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function daysSince(iso?: string) {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
}

function ResizePopover({ strategy, onResize, onClose }: { strategy: Strategy; onResize: (n: number) => void; onClose: () => void }) {
  const [val, setVal] = useState(strategy.allocation_pct ?? 5);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div className="w-72 rounded-xl border bg-card shadow-xl p-4" onClick={(e) => e.stopPropagation()}>
        <p className="text-sm font-medium mb-1">{strategy.name}</p>
        <p className="text-xs text-muted-foreground mb-4">Adjust allocation</p>
        <div className="flex items-center gap-3 mb-4">
          <input type="range" min={1} max={25} step={1} value={val} onChange={(e) => setVal(Number(e.target.value))} className="flex-1 accent-primary" />
          <span className="text-sm font-mono font-semibold w-10 text-right">{val}%</span>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 py-2 rounded-lg border text-xs text-muted-foreground hover:bg-muted">Cancel</button>
          <button onClick={() => { onResize(val); onClose(); }} className="flex-1 py-2 rounded-lg bg-primary text-primary-foreground text-xs font-medium hover:opacity-90">Resize</button>
        </div>
      </div>
    </div>
  );
}

export function Book() {
  const { strategies, pauseStrategy, resumeStrategy, resizeStrategy, killStrategy } = useOfficeStore();
  const [resizeTarget, setResizeTarget] = useState<Strategy | null>(null);

  const live = strategies.filter((s) => s.status === "live");
  const paused = strategies.filter((s) => s.status === "paused");
  const deferred = strategies.filter((s) => s.status === "deferred");

  const totalAlloc = live.reduce((a, s) => a + (s.allocation_pct ?? 0), 0);
  const avgSharpe = live.length > 0
    ? live.reduce((a, s) => a + s.metrics.sharpe, 0) / live.length
    : 0;
  const totalDailyPnl = live.reduce((a, s) => a + (s.daily_pnl ?? 0), 0) / Math.max(live.length, 1);

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b bg-card/50">
        <div className="max-w-5xl mx-auto px-6 py-5">
          <h1 className="text-lg font-semibold mb-4">Book</h1>

          {/* Portfolio-level stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: "Daily P&L", value: fmtPnl(totalDailyPnl), color: totalDailyPnl >= 0 ? "text-success" : "text-danger" },
              { label: "Deployed", value: `${totalAlloc}%`, color: totalAlloc > 80 ? "text-danger" : totalAlloc > 60 ? "text-warning" : "text-foreground" },
              { label: "Avg Sharpe", value: avgSharpe.toFixed(2), color: avgSharpe >= 1.2 ? "text-success" : "text-warning" },
              { label: "Live Strategies", value: String(live.length), color: "text-foreground" },
            ].map(({ label, value, color }) => (
              <div key={label} className="rounded-xl border bg-card p-4">
                <div className={cn("text-xl font-semibold font-mono", color)}>{value}</div>
                <div className="text-xs text-muted-foreground mt-0.5">{label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-6 space-y-6">

        {/* Live strategies table */}
        {live.length > 0 && (
          <div className="rounded-xl border bg-card overflow-hidden">
            <div className="px-4 py-3 border-b flex items-center justify-between">
              <h2 className="text-sm font-semibold">Live</h2>
              <span className="text-xs text-muted-foreground">{live.length} strategies · {totalAlloc}% deployed</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/30">
                    {["Strategy", "Market", "Alloc", "Daily P&L", "Sharpe", "Live Since", "Curve", ""].map((h) => (
                      <th key={h} className="px-4 py-2 text-left text-[11px] text-muted-foreground font-medium whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {live.map((s) => {
                    const days = daysSince(s.live_since);
                    return (
                      <tr key={s.id} className="border-b last:border-0 hover:bg-muted/20 transition-colors">
                        <td className="px-4 py-3">
                          <div className="font-medium text-sm leading-tight">{s.name}</div>
                          {s.decision?.reason && (
                            <div className="text-[10px] text-muted-foreground mt-0.5 max-w-[200px] truncate">{s.decision.reason}</div>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-muted-foreground whitespace-nowrap">{s.market ?? "—"}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-mono font-semibold">{s.allocation_pct ?? "—"}%</span>
                            <button
                              onClick={() => setResizeTarget(s)}
                              className="opacity-0 group-hover:opacity-100 p-0.5 text-muted-foreground hover:text-foreground rounded transition-all"
                            >
                              <SlidersHorizontal className="h-3 w-3" />
                            </button>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className={cn("text-sm font-mono font-semibold", (s.daily_pnl ?? 0) >= 0 ? "text-success" : "text-danger")}>
                            {fmtPnl(s.daily_pnl)}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={cn("text-sm font-mono", s.metrics.sharpe >= 1.2 ? "text-success" : "text-warning")}>
                            {s.metrics.sharpe.toFixed(2)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-muted-foreground whitespace-nowrap">
                          {days != null ? `${days}d` : "—"}
                        </td>
                        <td className="px-4 py-3">
                          <MiniSparkline data={s.equity_curve} width={80} height={28} positive={(s.daily_pnl ?? 0) >= 0} />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => setResizeTarget(s)}
                              className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded transition-colors"
                              title="Resize"
                            >
                              <SlidersHorizontal className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => pauseStrategy(s.id)}
                              className="p-1.5 text-muted-foreground hover:text-warning hover:bg-warning/10 rounded transition-colors"
                              title="Pause"
                            >
                              <Pause className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => killStrategy(s.id)}
                              className="p-1.5 text-muted-foreground hover:text-danger hover:bg-danger/10 rounded transition-colors"
                              title="Kill"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Paused strategies */}
        {paused.length > 0 && (
          <div className="rounded-xl border bg-card overflow-hidden">
            <div className="px-4 py-3 border-b">
              <h2 className="text-sm font-semibold text-muted-foreground">Paused</h2>
            </div>
            <div className="divide-y">
              {paused.map((s) => (
                <div key={s.id} className="flex items-center gap-4 px-4 py-3 hover:bg-muted/20 transition-colors">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{s.name}</p>
                    <p className="text-xs text-muted-foreground">{s.market}</p>
                  </div>
                  <span className="text-xs font-mono text-muted-foreground">{s.allocation_pct ?? "—"}%</span>
                  <button
                    onClick={() => resumeStrategy(s.id)}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-success/10 text-success text-xs font-medium hover:bg-success/20 transition-colors"
                  >
                    <Play className="h-3 w-3" />
                    Resume
                  </button>
                  <button
                    onClick={() => killStrategy(s.id)}
                    className="p-1.5 text-muted-foreground hover:text-danger hover:bg-danger/10 rounded transition-colors"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Deferred pipeline */}
        {deferred.length > 0 && (
          <div className="rounded-xl border bg-card overflow-hidden">
            <div className="px-4 py-3 border-b flex items-center gap-2">
              <Clock className="h-4 w-4 text-info" />
              <h2 className="text-sm font-semibold">Deferred Pipeline</h2>
              <span className="text-xs text-muted-foreground">— waiting on conditions</span>
            </div>
            <div className="divide-y">
              {deferred.map((s) => (
                <div key={s.id} className="px-4 py-4 hover:bg-muted/20 transition-colors">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">{s.name}</p>
                      <p className="text-xs text-muted-foreground mt-0.5">{s.market}</p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-xs font-mono text-muted-foreground">SR {s.metrics.sharpe.toFixed(2)}</span>
                    </div>
                  </div>
                  {s.decision?.defer_condition && (
                    <div className="mt-2 px-3 py-2 rounded-lg bg-info/5 border border-info/20">
                      <p className="text-xs text-info">{s.decision.defer_condition}</p>
                    </div>
                  )}
                  {s.decision?.reason && (
                    <p className="text-xs text-muted-foreground mt-1.5">{s.decision.reason}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {live.length === 0 && paused.length === 0 && deferred.length === 0 && (
          <div className="rounded-xl border border-dashed bg-card/50 p-12 text-center">
            <p className="text-sm font-medium">Book is empty</p>
            <p className="text-xs text-muted-foreground mt-1">Approve strategies from the Inbox to deploy them.</p>
          </div>
        )}
      </div>

      {resizeTarget && (
        <ResizePopover
          strategy={resizeTarget}
          onResize={(n) => resizeStrategy(resizeTarget.id, n)}
          onClose={() => setResizeTarget(null)}
        />
      )}
    </div>
  );
}
