import { useState } from "react";
import { Radio, Plus, Trash2, Power, Clock, TrendingUp, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOfficeStore } from "@/stores/office";
import type { Mandate } from "@/types/office";

function timeAgo(iso?: string) {
  if (!iso) return "Never";
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

function NewMandateModal({ onSave, onClose }: { onSave: (m: Omit<Mandate, "id" | "created_at">) => void; onClose: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [markets, setMarkets] = useState("");
  const [signalTypes, setSignalTypes] = useState("");
  const [minSharpe, setMinSharpe] = useState(1.2);
  const [maxDd, setMaxDd] = useState(12);
  const [schedule, setSchedule] = useState("Nightly 02:00");

  const canSave = name.trim() && description.trim();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-lg rounded-xl border bg-card shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="font-semibold">New Mandate</h3>
          <button onClick={onClose} className="p-1 text-muted-foreground hover:text-foreground rounded transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-4 space-y-4 max-h-[70vh] overflow-y-auto">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Name <span className="text-danger">*</span></label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. HK Small Cap Momentum Scan"
              className="w-full px-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Description <span className="text-danger">*</span></label>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2}
              placeholder="What should agents look for?"
              className="w-full px-3 py-2 rounded-lg border bg-background text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary/30" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Markets</label>
              <input value={markets} onChange={(e) => setMarkets(e.target.value)} placeholder="HK Equities, Crypto"
                className="w-full px-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Signal Types</label>
              <input value={signalTypes} onChange={(e) => setSignalTypes(e.target.value)} placeholder="momentum, factor"
                className="w-full px-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Min Sharpe</label>
              <div className="flex items-center gap-2">
                <input type="range" min={0.5} max={3} step={0.1} value={minSharpe} onChange={(e) => setMinSharpe(Number(e.target.value))} className="flex-1 accent-success" />
                <span className="text-sm font-mono w-8">{minSharpe.toFixed(1)}</span>
              </div>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Max Drawdown %</label>
              <div className="flex items-center gap-2">
                <input type="range" min={5} max={30} step={1} value={maxDd} onChange={(e) => setMaxDd(Number(e.target.value))} className="flex-1 accent-danger" />
                <span className="text-sm font-mono w-8">{maxDd}%</span>
              </div>
            </div>
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Schedule</label>
            <input value={schedule} onChange={(e) => setSchedule(e.target.value)} placeholder="Nightly 02:00 HKT"
              className="w-full px-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
          </div>
        </div>
        <div className="flex gap-2 p-4 border-t">
          <button onClick={onClose} className="flex-1 py-2 rounded-lg border text-sm text-muted-foreground hover:bg-muted">Cancel</button>
          <button
            disabled={!canSave}
            onClick={() => {
              onSave({
                name: name.trim(),
                description: description.trim(),
                markets: markets.split(",").map(s => s.trim()).filter(Boolean),
                signal_types: signalTypes.split(",").map(s => s.trim()).filter(Boolean),
                min_sharpe: minSharpe,
                max_drawdown_limit: maxDd,
                active: true,
                schedule: schedule.trim() || "Nightly",
                strategies_found: 0,
              });
              onClose();
            }}
            className="flex-1 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 disabled:opacity-40 transition-opacity"
          >
            Create Mandate
          </button>
        </div>
      </div>
    </div>
  );
}

function MandateCard({ mandate }: { mandate: Mandate }) {
  const { toggleMandate, deleteMandate } = useOfficeStore();

  return (
    <div className={cn("rounded-xl border bg-card transition-all", !mandate.active && "opacity-60")}>
      <div className="p-4">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <Radio className={cn("h-3.5 w-3.5 shrink-0", mandate.active ? "text-primary" : "text-muted-foreground")} />
              <h3 className="font-semibold text-sm leading-tight">{mandate.name}</h3>
            </div>
            <p className="text-xs text-muted-foreground leading-snug">{mandate.description}</p>
          </div>
          <button
            onClick={() => toggleMandate(mandate.id)}
            className={cn(
              "shrink-0 flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium transition-colors",
              mandate.active
                ? "bg-success/10 text-success hover:bg-success/20"
                : "bg-muted text-muted-foreground hover:bg-muted/80"
            )}
          >
            <Power className="h-3 w-3" />
            {mandate.active ? "Active" : "Paused"}
          </button>
        </div>

        {/* Tags */}
        <div className="flex flex-wrap gap-1.5 mb-3">
          {mandate.markets.map((m) => (
            <span key={m} className="px-2 py-0.5 rounded-full bg-muted text-[10px] text-muted-foreground">{m}</span>
          ))}
          {mandate.signal_types.map((t) => (
            <span key={t} className="px-2 py-0.5 rounded-full bg-primary/10 text-[10px] text-primary">{t}</span>
          ))}
        </div>

        {/* Criteria */}
        <div className="grid grid-cols-3 gap-2 mb-3">
          <div className="bg-muted/40 rounded-lg p-2 text-center">
            <div className="text-sm font-semibold text-success">{mandate.min_sharpe.toFixed(1)}</div>
            <div className="text-[10px] text-muted-foreground">Min Sharpe</div>
          </div>
          <div className="bg-muted/40 rounded-lg p-2 text-center">
            <div className="text-sm font-semibold text-warning">{mandate.max_drawdown_limit}%</div>
            <div className="text-[10px] text-muted-foreground">Max DD</div>
          </div>
          <div className="bg-muted/40 rounded-lg p-2 text-center">
            <div className="text-sm font-semibold">{mandate.strategies_found ?? 0}</div>
            <div className="text-[10px] text-muted-foreground">Found</div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {mandate.schedule}
            </span>
            {mandate.last_run && (
              <span className="flex items-center gap-1">
                <TrendingUp className="h-3 w-3" />
                Last run {timeAgo(mandate.last_run)}
              </span>
            )}
          </div>
          <button
            onClick={() => deleteMandate(mandate.id)}
            className="p-1 text-muted-foreground hover:text-danger hover:bg-danger/10 rounded transition-colors"
            title="Delete mandate"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

export function Mandates() {
  const { mandates, addMandate } = useOfficeStore();
  const [showNew, setShowNew] = useState(false);

  const active = mandates.filter((m) => m.active);
  const inactive = mandates.filter((m) => !m.active);

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b bg-card/50">
        <div className="max-w-5xl mx-auto px-6 py-5 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">Mandates</h1>
            <p className="text-xs text-muted-foreground mt-0.5">
              Standing instructions for continuous agent research loops
            </p>
          </div>
          <button
            onClick={() => setShowNew(true)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity"
          >
            <Plus className="h-4 w-4" />
            New Mandate
          </button>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-6 space-y-6">

        {/* Active */}
        {active.length > 0 && (
          <div>
            <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">Active</h2>
            <div className="grid md:grid-cols-2 gap-3">
              {active.map((m) => <MandateCard key={m.id} mandate={m} />)}
            </div>
          </div>
        )}

        {/* Inactive */}
        {inactive.length > 0 && (
          <div>
            <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">Paused</h2>
            <div className="grid md:grid-cols-2 gap-3">
              {inactive.map((m) => <MandateCard key={m.id} mandate={m} />)}
            </div>
          </div>
        )}

        {mandates.length === 0 && (
          <div className="rounded-xl border border-dashed bg-card/50 p-12 text-center">
            <Radio className="h-8 w-8 text-muted-foreground mx-auto mb-3 opacity-40" />
            <p className="text-sm font-medium">No mandates yet</p>
            <p className="text-xs text-muted-foreground mt-1 mb-4">
              Mandates tell agents what to look for continuously. Without mandates, the inbox won't fill itself.
            </p>
            <button
              onClick={() => setShowNew(true)}
              className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity"
            >
              Create your first mandate
            </button>
          </div>
        )}
      </div>

      {showNew && (
        <NewMandateModal
          onSave={addMandate}
          onClose={() => setShowNew(false)}
        />
      )}
    </div>
  );
}
