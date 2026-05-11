import { useState } from "react";
import { X, CheckCircle2, XCircle, Wrench, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Strategy, DecisionAction } from "@/types/office";

interface Props {
  strategy: Strategy;
  onApprove: (allocation: number, reason: string) => void;
  onReject: (reason: string) => void;
  onModify: (instructions: string) => void;
  onDefer: (reason: string, condition: string) => void;
  onClose: () => void;
}

type Tab = DecisionAction;

export function DecisionModal({ strategy, onApprove, onReject, onModify, onDefer, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("approve");
  const [reason, setReason] = useState("");
  const [allocation, setAllocation] = useState(5);
  const [condition, setCondition] = useState("");

  const TABS: { id: Tab; label: string; icon: React.ReactNode; color: string }[] = [
    { id: "approve", label: "Approve", icon: <CheckCircle2 className="h-3.5 w-3.5" />, color: "text-success border-success bg-success/10" },
    { id: "reject",  label: "Reject",  icon: <XCircle className="h-3.5 w-3.5" />,     color: "text-danger border-danger bg-danger/10" },
    { id: "modify",  label: "Modify",  icon: <Wrench className="h-3.5 w-3.5" />,       color: "text-warning border-warning bg-warning/10" },
    { id: "defer",   label: "Defer",   icon: <Clock className="h-3.5 w-3.5" />,        color: "text-info border-info bg-info/10" },
  ];

  const canSubmit = () => {
    if (tab === "approve") return true;
    if (tab === "reject") return reason.trim().length > 0;
    if (tab === "modify") return reason.trim().length > 0;
    if (tab === "defer") return reason.trim().length > 0 && condition.trim().length > 0;
    return false;
  };

  const handleSubmit = () => {
    if (!canSubmit()) return;
    if (tab === "approve") onApprove(allocation, reason || "Approved.");
    else if (tab === "reject") onReject(reason);
    else if (tab === "modify") onModify(reason);
    else if (tab === "defer") onDefer(reason, condition);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-xl border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between p-4 border-b">
          <div>
            <p className="text-xs text-muted-foreground mb-0.5">Decision</p>
            <h3 className="font-semibold text-sm leading-tight">{strategy.name}</h3>
          </div>
          <button onClick={onClose} className="p-1 text-muted-foreground hover:text-foreground rounded transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Action tabs */}
        <div className="flex gap-1.5 p-4 pb-0">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg border text-xs font-medium transition-all",
                tab === t.id ? t.color : "border-border text-muted-foreground hover:bg-muted"
              )}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>

        {/* Form */}
        <div className="p-4 space-y-3">
          {tab === "approve" && (
            <>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Allocation %</label>
                <div className="flex items-center gap-3">
                  <input
                    type="range" min={1} max={25} step={1} value={allocation}
                    onChange={(e) => setAllocation(Number(e.target.value))}
                    className="flex-1 accent-success"
                  />
                  <span className="text-sm font-mono font-semibold w-10 text-right">{allocation}%</span>
                </div>
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Note (optional)</label>
                <textarea
                  rows={2}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Why this fits the book..."
                  className="w-full px-3 py-2 rounded-lg border bg-background text-sm resize-none focus:outline-none focus:ring-2 focus:ring-success/30"
                />
              </div>
            </>
          )}

          {tab === "reject" && (
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Reason <span className="text-danger">*</span></label>
              <textarea
                autoFocus rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Why this doesn't fit (fed back to agents as standing context)..."
                className="w-full px-3 py-2 rounded-lg border bg-background text-sm resize-none focus:outline-none focus:ring-2 focus:ring-danger/30"
              />
            </div>
          )}

          {tab === "modify" && (
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Instructions for agent <span className="text-warning">*</span></label>
              <textarea
                autoFocus rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. Reduce leverage by half, add a VIX regime filter, tighten the stop to 3%..."
                className="w-full px-3 py-2 rounded-lg border bg-background text-sm resize-none focus:outline-none focus:ring-2 focus:ring-warning/30"
              />
              <p className="text-xs text-muted-foreground mt-1.5">Strategy will re-surface when agent completes the revision.</p>
            </div>
          )}

          {tab === "defer" && (
            <>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Reason <span className="text-info">*</span></label>
                <textarea
                  autoFocus rows={2}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Why not now..."
                  className="w-full px-3 py-2 rounded-lg border bg-background text-sm resize-none focus:outline-none focus:ring-2 focus:ring-info/30"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Re-review condition <span className="text-info">*</span></label>
                <textarea
                  rows={2}
                  value={condition}
                  onChange={(e) => setCondition(e.target.value)}
                  placeholder="e.g. Revisit when DXY > 104 and US 2Y yield breaks above 4.5%..."
                  className="w-full px-3 py-2 rounded-lg border bg-background text-sm resize-none focus:outline-none focus:ring-2 focus:ring-info/30"
                />
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-2 p-4 pt-0">
          <button onClick={onClose} className="flex-1 py-2 rounded-lg border text-sm text-muted-foreground hover:bg-muted transition-colors">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit()}
            className={cn(
              "flex-1 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-40",
              tab === "approve" && "bg-success text-white hover:opacity-90",
              tab === "reject"  && "bg-danger text-white hover:opacity-90",
              tab === "modify"  && "bg-warning text-black hover:opacity-90",
              tab === "defer"   && "bg-info text-white hover:opacity-90",
            )}
          >
            Confirm {TABS.find(t => t.id === tab)?.label}
          </button>
        </div>
      </div>
    </div>
  );
}
