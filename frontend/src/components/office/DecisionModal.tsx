import { useState } from "react";
import { X, CheckCircle2, XCircle, Wrench, Clock, TrendingUp, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Strategy, DecisionAction } from "@/types/office";
import { useOfficeStore, calcPortfolioImpact } from "@/stores/office";

interface Props {
  strategy: Strategy;
  onApprove: (allocation: number, reason: string) => void;
  onReject: (reason: string) => void;
  onModify: (instructions: string) => void;
  onDefer: (reason: string, condition: string) => void;
  onClose: () => void;
}

type Tab = DecisionAction;

function Delta({ label, current, next, format = (n: number) => n.toFixed(2), positive = true }: {
  label: string; current: number; next: number;
  format?: (n: number) => string; positive?: boolean;
}) {
  const delta = next - current;
  const improved = positive ? delta > 0 : delta < 0;
  const unchanged = Math.abs(delta) < 0.005;
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <div className="flex items-center gap-2">
        <span className="metric-val text-[10px] text-muted-foreground">{format(current)}</span>
        <span className="text-[10px] text-muted-foreground/30">→</span>
        <span className={cn("metric-val text-[10px] font-semibold", unchanged ? "text-muted-foreground" : improved ? "text-success" : "text-danger")}>
          {format(next)}
        </span>
        {!unchanged && (
          improved
            ? <TrendingUp className="h-2.5 w-2.5 text-success" />
            : <TrendingDown className="h-2.5 w-2.5 text-danger" />
        )}
      </div>
    </div>
  );
}

export function DecisionModal({ strategy, onApprove, onReject, onModify, onDefer, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("approve");
  const [reason, setReason] = useState("");
  const [allocation, setAllocation] = useState(5);
  const [condition, setCondition] = useState("");

  const { strategies } = useOfficeStore();
  const impact = calcPortfolioImpact(strategies, strategy.id, allocation);

  const TABS: { id: Tab; label: string; icon: React.ReactNode; active: string; btn: string }[] = [
    { id: "approve", label: "Deploy",   icon: <CheckCircle2 className="h-3 w-3" />, active: "text-success border-success bg-success/10",  btn: "bg-success text-white" },
    { id: "reject",  label: "Decline",  icon: <XCircle className="h-3 w-3" />,      active: "text-danger border-danger bg-danger/10",    btn: "bg-danger text-white" },
    { id: "modify",  label: "Modify",   icon: <Wrench className="h-3 w-3" />,       active: "text-warning border-warning bg-warning/10", btn: "bg-warning text-black" },
    { id: "defer",   label: "Defer",    icon: <Clock className="h-3 w-3" />,        active: "text-info border-info bg-info/10",          btn: "bg-info text-white" },
  ];

  const canSubmit = tab === "approve" || reason.trim().length > 0
    ? (tab === "defer" ? reason.trim().length > 0 && condition.trim().length > 0 : true)
    : false;

  const handleSubmit = () => {
    if (!canSubmit) return;
    if (tab === "approve") onApprove(allocation, reason || "Deployed.");
    else if (tab === "reject") onReject(reason);
    else if (tab === "modify") onModify(reason);
    else if (tab === "defer") onDefer(reason, condition);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl border bg-card shadow-2xl" onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="flex items-start justify-between px-4 py-3 border-b">
          <div>
            <p className="label-caps mb-0.5">Decision required</p>
            <h3 className="text-sm font-semibold leading-tight">{strategy.name}</h3>
            <p className="text-[10px] text-muted-foreground mt-0.5">{strategy.market} · {strategy.agent_id}</p>
          </div>
          <button onClick={onClose} className="p-1 text-muted-foreground hover:text-foreground rounded transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Action tabs */}
        <div className="flex gap-1 px-4 pt-3 pb-0">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg border text-[10px] font-semibold uppercase tracking-wide transition-all",
                tab === t.id ? t.active : "border-border text-muted-foreground hover:bg-muted"
              )}
            >
              {t.icon}{t.label}
            </button>
          ))}
        </div>

        {/* Form */}
        <div className="p-4 space-y-3">
          {tab === "approve" && (
            <>
              {/* Allocation slider */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-[10px] text-muted-foreground uppercase tracking-wide font-semibold">Allocation</label>
                  <span className="metric-val text-sm font-semibold text-success">{allocation}%</span>
                </div>
                <input
                  type="range" min={1} max={25} step={1} value={allocation}
                  onChange={e => setAllocation(Number(e.target.value))}
                  className="w-full accent-success h-1 rounded-full"
                />
                <div className="flex justify-between text-[9px] text-muted-foreground/50 mt-1">
                  <span>1%</span><span>25%</span>
                </div>
              </div>

              {/* Portfolio impact preview */}
              {impact && (
                <div className="rounded-lg border bg-muted/20 px-3 py-2">
                  <p className="label-caps mb-2">Portfolio impact</p>
                  <Delta label="Portfolio Sharpe" current={impact.currentSharpe} next={impact.newSharpe} positive />
                  <Delta label="Max Drawdown" current={impact.currentMaxDD} next={impact.newMaxDD} format={n => `${n.toFixed(1)}%`} positive={false} />
                  <Delta label="Deployed" current={impact.currentDeployed} next={impact.newDeployed} format={n => `${n}%`} positive={false} />
                  <div className="mt-1.5 pt-1.5 border-t border-border/50 flex justify-between">
                    <span className="text-[10px] text-muted-foreground">Budget remaining</span>
                    <span className={cn("metric-val text-[10px] font-semibold", impact.remainingBudget < 20 ? "text-warning" : "text-foreground")}>
                      {impact.remainingBudget}%
                    </span>
                  </div>
                </div>
              )}

              <div>
                <label className="text-[10px] text-muted-foreground uppercase tracking-wide font-semibold block mb-1">Note (optional)</label>
                <textarea rows={2} value={reason} onChange={e => setReason(e.target.value)}
                  placeholder="Rationale for the record..."
                  className="w-full px-3 py-2 rounded-lg border bg-background text-xs resize-none focus:outline-none focus:ring-1 focus:ring-success/40"
                />
              </div>
            </>
          )}

          {tab === "reject" && (
            <div>
              <label className="text-[10px] text-muted-foreground uppercase tracking-wide font-semibold block mb-1">
                Reason <span className="text-danger">*</span>
              </label>
              <textarea autoFocus rows={3} value={reason} onChange={e => setReason(e.target.value)}
                placeholder="Why this signal doesn't fit (returned to agents as standing context)..."
                className="w-full px-3 py-2 rounded-lg border bg-background text-xs resize-none focus:outline-none focus:ring-1 focus:ring-danger/40"
              />
              <p className="text-[10px] text-muted-foreground mt-1.5">This reason is stored and shapes future agent behaviour.</p>
            </div>
          )}

          {tab === "modify" && (
            <div>
              <label className="text-[10px] text-muted-foreground uppercase tracking-wide font-semibold block mb-1">
                Instructions for agent <span className="text-warning">*</span>
              </label>
              <textarea autoFocus rows={3} value={reason} onChange={e => setReason(e.target.value)}
                placeholder="e.g. Reduce leverage by half, add a VIX regime filter, tighten the stop to 3%..."
                className="w-full px-3 py-2 rounded-lg border bg-background text-xs resize-none focus:outline-none focus:ring-1 focus:ring-warning/40"
              />
              <p className="text-[10px] text-muted-foreground mt-1.5">Strategy will re-surface when the agent completes the revision.</p>
            </div>
          )}

          {tab === "defer" && (
            <>
              <div>
                <label className="text-[10px] text-muted-foreground uppercase tracking-wide font-semibold block mb-1">Reason <span className="text-info">*</span></label>
                <textarea autoFocus rows={2} value={reason} onChange={e => setReason(e.target.value)}
                  placeholder="Why not now..."
                  className="w-full px-3 py-2 rounded-lg border bg-background text-xs resize-none focus:outline-none focus:ring-1 focus:ring-info/40"
                />
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground uppercase tracking-wide font-semibold block mb-1">Re-review condition <span className="text-info">*</span></label>
                <textarea rows={2} value={condition} onChange={e => setCondition(e.target.value)}
                  placeholder="e.g. Revisit when DXY > 104 and US 2Y yield breaks 4.5%..."
                  className="w-full px-3 py-2 rounded-lg border bg-background text-xs resize-none focus:outline-none focus:ring-1 focus:ring-info/40"
                />
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-2 px-4 pb-4">
          <button onClick={onClose} className="flex-1 py-2 rounded-lg border text-xs text-muted-foreground hover:bg-muted transition-colors">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className={cn("flex-1 py-2 rounded-lg text-xs font-semibold transition-all disabled:opacity-40 uppercase tracking-wide", TABS.find(t => t.id === tab)?.btn)}
          >
            Confirm {TABS.find(t => t.id === tab)?.label}
          </button>
        </div>
      </div>
    </div>
  );
}
