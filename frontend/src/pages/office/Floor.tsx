import { Link } from "react-router-dom";
import { ArrowRight, CheckCircle2, AlertCircle, Zap, Moon, Radio, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOfficeStore } from "@/stores/office";
import type { OfficAlert } from "@/types/office";

const ALERT_ICON: Record<OfficAlert["type"], React.ReactNode> = {
  strategy_surfaced: <Moon className="h-3.5 w-3.5" />,
  event_trigger:     <Zap className="h-3.5 w-3.5" />,
  risk_alert:        <AlertCircle className="h-3.5 w-3.5" />,
  mandate_complete:  <Radio className="h-3.5 w-3.5" />,
  book_update:       <TrendingUp className="h-3.5 w-3.5" />,
};

const ALERT_COLOR: Record<OfficAlert["type"], string> = {
  strategy_surfaced: "text-info",
  event_trigger:     "text-warning",
  risk_alert:        "text-danger",
  mandate_complete:  "text-success",
  book_update:       "text-muted-foreground",
};

function timeAgo(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function Floor() {
  const { strategies, mandates, alerts, agents, markAlertRead, markAllAlertsRead } = useOfficeStore();

  const pending  = strategies.filter(s => s.status === "pending");
  const live     = strategies.filter(s => s.status === "live");
  const totalAlloc = live.reduce((a, s) => a + (s.allocation_pct ?? 0), 0);
  const bookPnl  = live.length > 0 ? live.reduce((a, s) => a + (s.daily_pnl ?? 0), 0) / live.length : 0;
  const activeMandates = mandates.filter(m => m.active);
  const unread   = alerts.filter(a => !a.read);
  const activeAgents = agents.filter(a => a.status !== "idle");
  const totalBacktests = agents.reduce((a, ag) => a + ag.backtests_run, 0);

  const greeting = (() => {
    const h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  })();
  const today = new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });

  // Build narrative brief
  const narrativeParts: string[] = [];
  if (totalBacktests > 0) narrativeParts.push(`Agents ran ${totalBacktests.toLocaleString()} backtests overnight.`);
  if (pending.length > 0) narrativeParts.push(`${pending.length} ${pending.length === 1 ? "signal" : "signals"} cleared threshold and ${pending.length === 1 ? "is" : "are"} awaiting your decision.`);
  if (live.length > 0) narrativeParts.push(`Book is ${bookPnl >= 0 ? "up" : "down"} ${Math.abs(bookPnl).toFixed(2)}% today across ${live.length} live ${live.length === 1 ? "strategy" : "strategies"}.`);
  if (pending.length === 0 && live.length > 0) narrativeParts.push("Inbox clear.");

  return (
    <div className="min-h-screen bg-background">

      {/* Morning brief header */}
      <div className="border-b bg-card/40">
        <div className="max-w-4xl mx-auto px-6 py-7">
          <p className="label-caps mb-1">{today}</p>
          <h1 className="text-2xl font-semibold tracking-tight mb-3">{greeting}.</h1>
          {narrativeParts.length > 0 && (
            <p className="text-sm text-muted-foreground leading-relaxed max-w-2xl prose-dense">
              {narrativeParts.join(" ")}
            </p>
          )}
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-6 py-5 space-y-6">

        {/* Status tiles — dense, data-forward */}
        <div className="grid grid-cols-4 gap-2">
          {[
            {
              to: "/office/inbox",
              label: "Pending Decision",
              value: pending.length,
              sub: pending.length > 0 ? `${pending.map(s => s.market).filter((v,i,a) => a.indexOf(v) === i).join(", ")}` : "Inbox clear",
              highlight: pending.length > 0,
              color: pending.length > 0 ? "text-primary" : "text-muted-foreground",
            },
            {
              to: "/office/book",
              label: "Book P&L",
              value: `${bookPnl >= 0 ? "+" : ""}${bookPnl.toFixed(2)}%`,
              sub: `${live.length} live · ${totalAlloc}% deployed`,
              highlight: false,
              color: bookPnl > 0 ? "text-success" : bookPnl < 0 ? "text-danger" : "text-muted-foreground",
            },
            {
              to: "/office/book",
              label: "Risk Budget",
              value: `${totalAlloc}%`,
              sub: `${100 - totalAlloc}% available`,
              highlight: false,
              color: totalAlloc > 80 ? "text-danger" : totalAlloc > 60 ? "text-warning" : "text-foreground",
              progress: totalAlloc,
            },
            {
              to: "/office/mandates",
              label: "Active Mandates",
              value: activeMandates.length,
              sub: `${activeAgents.length} agents working`,
              highlight: false,
              color: "text-foreground",
            },
          ].map(({ to, label, value, sub, highlight, color, progress }) => (
            <Link
              key={label}
              to={to}
              className={cn(
                "group rounded-lg border bg-card p-3 flex flex-col gap-1.5 hover:border-border/80 transition-all",
                highlight && "border-primary/30 bg-primary/5 glow-primary"
              )}
            >
              <p className="label-caps">{label}</p>
              <p className={cn("metric-val text-xl font-semibold", color)}>{value}</p>
              <p className="text-[10px] text-muted-foreground group-hover:text-foreground transition-colors truncate">{sub}</p>
              {progress !== undefined && (
                <div className="h-0.5 rounded-full bg-muted overflow-hidden mt-0.5">
                  <div
                    className={cn("h-full rounded-full", progress > 80 ? "bg-danger" : progress > 60 ? "bg-warning" : "bg-success")}
                    style={{ width: `${Math.min(progress, 100)}%` }}
                  />
                </div>
              )}
            </Link>
          ))}
        </div>

        {/* Two-column: alerts + agent floor */}
        <div className="grid grid-cols-5 gap-4">

          {/* Activity feed — 3 cols */}
          <div className="col-span-3 rounded-lg border bg-card overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2.5 border-b">
              <div className="flex items-center gap-2">
                <span className="label-caps">Activity</span>
                {unread.length > 0 && (
                  <span className="h-4 min-w-4 px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-bold flex items-center justify-center">
                    {unread.length}
                  </span>
                )}
              </div>
              {unread.length > 0 && (
                <button onClick={markAllAlertsRead} className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors">
                  <CheckCircle2 className="h-3 w-3" /> Mark read
                </button>
              )}
            </div>
            <div className="divide-y divide-border/50">
              {alerts.slice(0, 6).map(a => (
                <div
                  key={a.id}
                  className={cn("flex items-start gap-3 px-4 py-2.5 transition-colors", !a.read ? "cursor-pointer hover:bg-muted/20" : "opacity-50")}
                  onClick={() => !a.read && markAlertRead(a.id)}
                >
                  <span className={cn("mt-0.5 shrink-0", ALERT_COLOR[a.type])}>{ALERT_ICON[a.type]}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs leading-snug prose-dense">{a.message}</p>
                    <p className="text-[10px] text-muted-foreground mt-0.5">{timeAgo(a.timestamp)}</p>
                  </div>
                  {!a.read && <div className="h-1.5 w-1.5 rounded-full bg-primary mt-1.5 shrink-0" />}
                </div>
              ))}
            </div>
          </div>

          {/* Agent floor — 2 cols */}
          <div className="col-span-2 rounded-lg border bg-card overflow-hidden">
            <div className="px-4 py-2.5 border-b">
              <span className="label-caps">Trading Floor</span>
            </div>
            <div className="divide-y divide-border/50">
              {agents.map(agent => (
                <div key={agent.id} className="px-4 py-2.5">
                  <div className="flex items-center gap-2 mb-1">
                    <div className={cn("h-1.5 w-1.5 rounded-full shrink-0",
                      agent.status === "idle"        ? "bg-muted-foreground/30" :
                      agent.status === "backtesting" ? "bg-warning pulse-dot" :
                      agent.status === "encoding"    ? "bg-primary pulse-dot" :
                      agent.status === "surfacing"   ? "bg-success pulse-dot" :
                      "bg-info pulse-dot"
                    )} />
                    <span className="text-xs font-medium">{agent.name}</span>
                    <span className="text-[10px] text-muted-foreground ml-auto">{agent.specialty.split(" ")[0]}</span>
                  </div>
                  <p className="text-[10px] text-muted-foreground pl-3.5 leading-snug truncate">{agent.current_task}</p>
                  {agent.status !== "idle" && agent.progress > 0 && (
                    <div className="mt-1.5 ml-3.5 h-0.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className={cn("h-full rounded-full transition-all duration-1000",
                          agent.status === "backtesting" ? "bg-warning" :
                          agent.status === "encoding" ? "bg-primary" :
                          "bg-success"
                        )}
                        style={{ width: `${agent.progress}%` }}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Pending strategies preview */}
        {pending.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="label-caps">Awaiting Decision</span>
              <Link to="/office/inbox" className="text-[10px] text-primary hover:text-primary/80 flex items-center gap-0.5 transition-colors">
                Review all <ArrowRight className="h-2.5 w-2.5" />
              </Link>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {pending.slice(0, 3).map(s => (
                <Link key={s.id} to="/office/inbox" className="rounded-lg border bg-card px-3 py-2.5 hover:border-primary/30 transition-all group">
                  <div className="flex items-start justify-between gap-1 mb-1.5">
                    <p className="text-xs font-medium leading-tight">{s.name}</p>
                    <span className={cn("metric-val text-xs font-semibold shrink-0", s.metrics.sharpe >= 1.2 ? "text-success" : "text-warning")}>
                      {s.metrics.sharpe.toFixed(2)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                    <span>{s.market}</span>
                    <span className="text-muted-foreground/30">·</span>
                    <span className={s.metrics.annual_return >= 0 ? "text-success" : "text-danger"}>
                      {s.metrics.annual_return >= 0 ? "+" : ""}{s.metrics.annual_return.toFixed(1)}% ann.
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {pending.length === 0 && (
          <div className="rounded-lg border border-dashed bg-card/30 p-6 flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-success opacity-60 shrink-0" />
            <div>
              <p className="text-sm font-medium">Inbox clear.</p>
              <p className="text-xs text-muted-foreground mt-0.5">Agents are running. New signals will surface when they clear your threshold.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
