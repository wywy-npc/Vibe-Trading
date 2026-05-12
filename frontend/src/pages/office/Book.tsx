import { useState, useMemo } from "react";
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

function pearson(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  if (n < 2) return 0;
  const slice = (arr: number[]) => arr.slice(0, n);
  const sa = slice(a), sb = slice(b);
  const meanA = sa.reduce((s, v) => s + v, 0) / n;
  const meanB = sb.reduce((s, v) => s + v, 0) / n;
  let num = 0, da = 0, db = 0;
  for (let i = 0; i < n; i++) {
    const x = sa[i] - meanA, y = sb[i] - meanB;
    num += x * y; da += x * x; db += y * y;
  }
  return da && db ? num / Math.sqrt(da * db) : 0;
}

function corrColor(r: number) {
  if (r >= 0.7)  return "bg-danger/70 text-danger-foreground";
  if (r >= 0.4)  return "bg-warning/50 text-warning-foreground";
  if (r >= 0.1)  return "bg-muted/40";
  if (r <= -0.3) return "bg-info/40 text-info";
  return "bg-muted/20";
}

function factorExposures(s: Strategy) {
  const sharpeScore = Math.min(100, Math.max(0, s.metrics.sharpe * 40));
  const momentum   = Math.min(100, Math.round(sharpeScore + s.metrics.win_rate * 0.5 - 20));
  const meanRev    = Math.min(100, Math.round(Math.max(0, 85 - momentum)));
  const carry      = s.market?.includes("CNH") || s.market?.includes("FX") || s.market?.includes("AUD")
    ? 72 : Math.round(15 + Math.abs(s.metrics.max_drawdown) * 0.8);
  const volArb     = Math.min(100, Math.round(Math.abs(s.metrics.max_drawdown) * 4));
  return { Momentum: momentum, "Mean-Rev": meanRev, Carry: carry, "Vol-Arb": volArb };
}

function FactorBar({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.round((value / max) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", pct > 60 ? "bg-primary" : pct > 30 ? "bg-info" : "bg-muted-foreground/40")}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="metric-val text-[10px] text-muted-foreground w-7 text-right">{value}</span>
    </div>
  );
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
          <span className="metric-val text-sm font-semibold w-10 text-right">{val}%</span>
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

  const live    = strategies.filter((s) => s.status === "live");
  const paused  = strategies.filter((s) => s.status === "paused");
  const deferred = strategies.filter((s) => s.status === "deferred");

  const totalAlloc    = live.reduce((a, s) => a + (s.allocation_pct ?? 0), 0);
  const avgSharpe     = live.length > 0 ? live.reduce((a, s) => a + s.metrics.sharpe, 0) / live.length : 0;
  const totalDailyPnl = live.reduce((a, s) => a + (s.daily_pnl ?? 0), 0) / Math.max(live.length, 1);
  const maxBudget     = 100;

  // Correlation matrix from equity curves
  const corrMatrix = useMemo(() => {
    const curves = live.map(s => s.equity_curve.map(p => p.v));
    return live.map((_, i) => live.map((_, j) => i === j ? 1 : pearson(curves[i], curves[j])));
  }, [live]);

  // Factor exposures
  const factors = useMemo(() => live.map(s => factorExposures(s)), [live]);
  const factorKeys = ["Momentum", "Mean-Rev", "Carry", "Vol-Arb"] as const;

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b bg-card/50 sticky top-0 z-10 backdrop-blur-sm">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-base font-semibold">Book</h1>
              <p className="text-[10px] text-muted-foreground mt-0.5">{live.length} live · {totalAlloc}% deployed · {maxBudget - totalAlloc}% available</p>
            </div>
          </div>

          <div className="grid grid-cols-4 gap-2">
            {[
              { label: "Daily P&L",        value: fmtPnl(totalDailyPnl),   color: totalDailyPnl >= 0 ? "text-success" : "text-danger" },
              { label: "Deployed",         value: `${totalAlloc}%`,         color: totalAlloc > 80 ? "text-danger" : totalAlloc > 60 ? "text-warning" : "text-foreground" },
              { label: "Avg Sharpe",       value: avgSharpe.toFixed(2),     color: avgSharpe >= 1.2 ? "text-success" : "text-warning" },
              { label: "Live Strategies",  value: String(live.length),      color: "text-foreground" },
            ].map(({ label, value, color }) => (
              <div key={label} className="rounded-lg border bg-card p-3">
                <div className={cn("metric-val text-xl font-semibold", color)}>{value}</div>
                <div className="label-caps mt-0.5">{label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="px-6 py-5 space-y-4 max-w-6xl">

        {live.length > 0 && (
          <>
            {/* Risk overview: allocation + correlation */}
            <div className="grid grid-cols-5 gap-4">

              {/* Allocation breakdown */}
              <div className="col-span-2 rounded-lg border bg-card p-4">
                <p className="label-caps mb-3">Risk Budget</p>
                <div className="space-y-2.5">
                  {live.map(s => {
                    const pct = s.allocation_pct ?? 0;
                    const share = totalAlloc > 0 ? (pct / maxBudget) * 100 : 0;
                    return (
                      <div key={s.id}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[10px] text-muted-foreground truncate max-w-[140px]">{s.name}</span>
                          <span className="metric-val text-[10px] font-semibold">{pct}%</span>
                        </div>
                        <div className="h-2 rounded-full bg-muted overflow-hidden">
                          <div
                            className={cn("h-full rounded-full",
                              (s.daily_pnl ?? 0) >= 0 ? "bg-success/70" : "bg-danger/60"
                            )}
                            style={{ width: `${share}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}

                  {/* Undeployed */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-muted-foreground/50">Undeployed</span>
                      <span className="metric-val text-[10px] text-muted-foreground/50">{maxBudget - totalAlloc}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-muted overflow-hidden">
                      <div className="h-full rounded-full bg-muted-foreground/15" style={{ width: `${maxBudget - totalAlloc}%` }} />
                    </div>
                  </div>

                  {/* Budget bar */}
                  <div className="mt-2 pt-2 border-t border-border/40">
                    <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className={cn("h-full rounded-full transition-all",
                          totalAlloc > 80 ? "bg-danger" : totalAlloc > 60 ? "bg-warning" : "bg-success"
                        )}
                        style={{ width: `${totalAlloc}%` }}
                      />
                    </div>
                    <div className="flex justify-between mt-1">
                      <span className="text-[9px] text-muted-foreground/40">0%</span>
                      <span className={cn("text-[9px] font-semibold",
                        totalAlloc > 80 ? "text-danger" : totalAlloc > 60 ? "text-warning" : "text-muted-foreground/40"
                      )}>100%</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Correlation matrix */}
              <div className="col-span-3 rounded-lg border bg-card p-4">
                <p className="label-caps mb-3">Correlation Matrix</p>
                {live.length < 2 ? (
                  <div className="flex items-center justify-center h-24">
                    <p className="text-xs text-muted-foreground">Need ≥ 2 live strategies</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse">
                      <thead>
                        <tr>
                          <th className="w-28" />
                          {live.map(s => (
                            <th key={s.id} className="px-1 pb-2 text-[9px] font-semibold text-muted-foreground text-center">
                              <span className="block max-w-[72px] truncate mx-auto" title={s.name}>
                                {s.name.split(" ").slice(0, 2).join(" ")}
                              </span>
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {live.map((rowS, i) => (
                          <tr key={rowS.id}>
                            <td className="pr-2 py-0.5 text-[9px] text-muted-foreground text-right max-w-[100px]">
                              <span className="truncate block" title={rowS.name}>
                                {rowS.name.split(" ").slice(0, 2).join(" ")}
                              </span>
                            </td>
                            {live.map((_, j) => {
                              const r = corrMatrix[i][j];
                              const isDiag = i === j;
                              return (
                                <td key={j} className="p-0.5">
                                  <div className={cn(
                                    "rounded flex items-center justify-center h-8 w-full min-w-[48px]",
                                    isDiag ? "bg-muted/50" : corrColor(r)
                                  )}>
                                    <span className={cn("metric-val text-[10px] font-semibold",
                                      isDiag ? "text-muted-foreground" :
                                      r >= 0.7 ? "text-danger" :
                                      r >= 0.4 ? "text-warning" :
                                      r <= -0.3 ? "text-info" :
                                      "text-muted-foreground"
                                    )}>
                                      {isDiag ? "—" : r.toFixed(2)}
                                    </span>
                                  </div>
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="flex items-center gap-3 mt-3 pt-2 border-t border-border/40">
                      {[
                        { color: "bg-danger/60",   label: "High (≥0.7)" },
                        { color: "bg-warning/40",  label: "Moderate (0.4–0.7)" },
                        { color: "bg-muted/30",    label: "Low (<0.4)" },
                        { color: "bg-info/30",     label: "Negative" },
                      ].map(({ color, label }) => (
                        <div key={label} className="flex items-center gap-1">
                          <div className={cn("h-2 w-3 rounded-sm", color)} />
                          <span className="text-[9px] text-muted-foreground/60">{label}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Factor exposures */}
            <div className="rounded-lg border bg-card overflow-hidden">
              <div className="px-4 py-2.5 border-b">
                <p className="label-caps">Factor Exposures</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b bg-muted/20">
                      <th className="px-4 py-2 text-left label-caps" style={{ fontSize: "9px" }}>Strategy</th>
                      {factorKeys.map(k => (
                        <th key={k} className="px-4 py-2 text-left label-caps" style={{ fontSize: "9px" }}>{k}</th>
                      ))}
                      <th className="px-4 py-2 text-left label-caps" style={{ fontSize: "9px" }}>Alloc</th>
                      <th className="px-4 py-2 text-left label-caps" style={{ fontSize: "9px" }}>Daily P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {live.map((s, i) => (
                      <tr key={s.id} className="border-b last:border-0 hover:bg-muted/10 transition-colors">
                        <td className="px-4 py-3">
                          <p className="text-xs font-medium">{s.name}</p>
                          <p className="text-[10px] text-muted-foreground">{s.market}</p>
                        </td>
                        {factorKeys.map(k => (
                          <td key={k} className="px-4 py-3 min-w-[100px]">
                            <FactorBar value={factors[i][k]} />
                          </td>
                        ))}
                        <td className="px-4 py-3">
                          <span className="metric-val text-xs font-semibold">{s.allocation_pct ?? "—"}%</span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={cn("metric-val text-xs font-semibold", (s.daily_pnl ?? 0) >= 0 ? "text-success" : "text-danger")}>
                            {fmtPnl(s.daily_pnl)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Live strategies table */}
            <div className="rounded-lg border bg-card overflow-hidden">
              <div className="px-4 py-2.5 border-b flex items-center justify-between">
                <p className="label-caps">Live Strategies</p>
                <span className="text-[10px] text-muted-foreground">{live.length} strategies · {totalAlloc}% deployed</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/20">
                      {["Strategy", "Market", "Alloc", "Daily P&L", "Sharpe", "Max DD", "Live Since", "Curve", ""].map((h) => (
                        <th key={h} className="px-4 py-2 text-left label-caps whitespace-nowrap" style={{ fontSize: "9px" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {live.map((s) => {
                      const days = daysSince(s.live_since);
                      return (
                        <tr key={s.id} className="border-b last:border-0 hover:bg-muted/20 transition-colors group">
                          <td className="px-4 py-3">
                            <div className="font-medium text-sm leading-tight">{s.name}</div>
                            {s.decision?.reason && (
                              <div className="text-[10px] text-muted-foreground mt-0.5 max-w-[200px] truncate">{s.decision.reason}</div>
                            )}
                          </td>
                          <td className="px-4 py-3 text-[10px] text-muted-foreground whitespace-nowrap">{s.market ?? "—"}</td>
                          <td className="px-4 py-3">
                            <span className="metric-val text-sm font-semibold">{s.allocation_pct ?? "—"}%</span>
                          </td>
                          <td className="px-4 py-3">
                            <span className={cn("metric-val text-sm font-semibold", (s.daily_pnl ?? 0) >= 0 ? "text-success" : "text-danger")}>
                              {fmtPnl(s.daily_pnl)}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <span className={cn("metric-val text-sm", s.metrics.sharpe >= 1.2 ? "text-success" : "text-warning")}>
                              {s.metrics.sharpe.toFixed(2)}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <span className={cn("metric-val text-sm", Math.abs(s.metrics.max_drawdown) <= 10 ? "text-success" : "text-warning")}>
                              {s.metrics.max_drawdown.toFixed(1)}%
                            </span>
                          </td>
                          <td className="px-4 py-3 text-[10px] text-muted-foreground whitespace-nowrap">
                            {days != null ? `${days}d` : "—"}
                          </td>
                          <td className="px-4 py-3">
                            <MiniSparkline data={s.equity_curve} width={80} height={28} positive={(s.daily_pnl ?? 0) >= 0} />
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
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
          </>
        )}

        {/* Paused strategies */}
        {paused.length > 0 && (
          <div className="rounded-lg border bg-card overflow-hidden">
            <div className="px-4 py-2.5 border-b">
              <p className="label-caps text-muted-foreground/70">Paused</p>
            </div>
            <div className="divide-y divide-border/50">
              {paused.map((s) => (
                <div key={s.id} className="flex items-center gap-4 px-4 py-3 hover:bg-muted/20 transition-colors">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{s.name}</p>
                    <p className="text-[10px] text-muted-foreground">{s.market}</p>
                  </div>
                  <span className="metric-val text-xs text-muted-foreground">{s.allocation_pct ?? "—"}%</span>
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
          <div className="rounded-lg border bg-card overflow-hidden">
            <div className="px-4 py-2.5 border-b flex items-center gap-2">
              <Clock className="h-3.5 w-3.5 text-info" />
              <p className="label-caps">Deferred Pipeline</p>
              <span className="text-[10px] text-muted-foreground">— waiting on conditions</span>
            </div>
            <div className="divide-y divide-border/50">
              {deferred.map((s) => (
                <div key={s.id} className="px-4 py-3 hover:bg-muted/20 transition-colors">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">{s.name}</p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">{s.market}</p>
                    </div>
                    <span className="metric-val text-xs text-muted-foreground">SR {s.metrics.sharpe.toFixed(2)}</span>
                  </div>
                  {s.decision?.defer_condition && (
                    <div className="mt-2 px-3 py-2 rounded-lg bg-info/5 border border-info/20">
                      <p className="text-xs text-info leading-snug">{s.decision.defer_condition}</p>
                    </div>
                  )}
                  {s.decision?.reason && (
                    <p className="text-[10px] text-muted-foreground mt-1.5">{s.decision.reason}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {live.length === 0 && paused.length === 0 && deferred.length === 0 && (
          <div className="rounded-lg border border-dashed bg-card/30 p-12 text-center">
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
