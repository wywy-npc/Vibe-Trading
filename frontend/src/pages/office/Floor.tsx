import { Link } from "react-router-dom";
import { Inbox, BookOpen, TrendingUp, AlertCircle, CheckCircle2, ArrowRight, Radio, Moon, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOfficeStore } from "@/stores/office";
import type { OfficAlert } from "@/types/office";

const ORIGIN_COLORS: Record<string, string> = {
  strategy_surfaced: "text-info",
  event_trigger: "text-warning",
  risk_alert: "text-danger",
  mandate_complete: "text-success",
  book_update: "text-muted-foreground",
};

const ORIGIN_ICONS: Record<string, React.ReactNode> = {
  strategy_surfaced: <Moon className="h-3.5 w-3.5" />,
  event_trigger: <Zap className="h-3.5 w-3.5" />,
  risk_alert: <AlertCircle className="h-3.5 w-3.5" />,
  mandate_complete: <Radio className="h-3.5 w-3.5" />,
  book_update: <TrendingUp className="h-3.5 w-3.5" />,
};

function timeAgo(iso: string) {
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

function AlertRow({ alert, onRead }: { alert: OfficAlert; onRead: () => void }) {
  return (
    <div
      className={cn(
        "flex items-start gap-3 p-3 rounded-lg transition-colors",
        alert.read ? "opacity-50" : "bg-muted/30 hover:bg-muted/50 cursor-pointer"
      )}
      onClick={() => !alert.read && onRead()}
    >
      <span className={cn("mt-0.5 shrink-0", ORIGIN_COLORS[alert.type])}>
        {ORIGIN_ICONS[alert.type]}
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-sm leading-snug">{alert.message}</p>
        <p className="text-xs text-muted-foreground mt-0.5">{timeAgo(alert.timestamp)}</p>
      </div>
      {!alert.read && <div className="h-1.5 w-1.5 rounded-full bg-primary mt-1.5 shrink-0" />}
    </div>
  );
}

export function Floor() {
  const { strategies, mandates, alerts, markAlertRead, markAllAlertsRead } = useOfficeStore();

  const pending = strategies.filter((s) => s.status === "pending");
  const live = strategies.filter((s) => s.status === "live");
  const totalAlloc = live.reduce((a, s) => a + (s.allocation_pct ?? 0), 0);
  const activeMandates = mandates.filter((m) => m.active);
  const unread = alerts.filter((a) => !a.read);

  const bookPnl = live.reduce((a, s) => a + (s.daily_pnl ?? 0), 0) / Math.max(live.length, 1);

  const greeting = (() => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  })();

  const today = new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b bg-card/50">
        <div className="max-w-5xl mx-auto px-6 py-6">
          <p className="text-xs text-muted-foreground mb-0.5">{today}</p>
          <h1 className="text-2xl font-semibold tracking-tight">{greeting}.</h1>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-6 space-y-6">

        {/* Quick stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Link
            to="/office/inbox"
            className={cn(
              "group rounded-xl border bg-card p-4 flex flex-col gap-1 hover:border-primary/40 transition-all",
              pending.length > 0 && "border-primary/30 bg-primary/5"
            )}
          >
            <div className="flex items-center justify-between">
              <Inbox className={cn("h-4 w-4", pending.length > 0 ? "text-primary" : "text-muted-foreground")} />
              {pending.length > 0 && (
                <span className="h-5 min-w-5 px-1.5 rounded-full bg-primary text-primary-foreground text-[10px] font-bold flex items-center justify-center">
                  {pending.length}
                </span>
              )}
            </div>
            <div className="text-xl font-semibold mt-1">{pending.length}</div>
            <div className="text-xs text-muted-foreground group-hover:text-foreground transition-colors">
              Pending review <ArrowRight className="inline h-3 w-3 ml-0.5" />
            </div>
          </Link>

          <Link
            to="/office/book"
            className="group rounded-xl border bg-card p-4 flex flex-col gap-1 hover:border-border/80 transition-all"
          >
            <div className="flex items-center justify-between">
              <BookOpen className="h-4 w-4 text-muted-foreground" />
              <span className={cn("text-xs font-medium", bookPnl >= 0 ? "text-success" : "text-danger")}>
                {bookPnl >= 0 ? "+" : ""}{bookPnl.toFixed(1)}% today
              </span>
            </div>
            <div className="text-xl font-semibold mt-1">{live.length}</div>
            <div className="text-xs text-muted-foreground group-hover:text-foreground transition-colors">
              Live strategies <ArrowRight className="inline h-3 w-3 ml-0.5" />
            </div>
          </Link>

          <div className="rounded-xl border bg-card p-4 flex flex-col gap-1">
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
            <div className="text-xl font-semibold mt-1">{totalAlloc}%</div>
            <div className="text-xs text-muted-foreground">Risk budget deployed</div>
            <div className="mt-1 h-1.5 rounded-full bg-muted overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all", totalAlloc > 80 ? "bg-danger" : totalAlloc > 60 ? "bg-warning" : "bg-success")}
                style={{ width: `${Math.min(totalAlloc, 100)}%` }}
              />
            </div>
          </div>

          <Link
            to="/office/mandates"
            className="group rounded-xl border bg-card p-4 flex flex-col gap-1 hover:border-border/80 transition-all"
          >
            <Radio className="h-4 w-4 text-muted-foreground" />
            <div className="text-xl font-semibold mt-1">{activeMandates.length}</div>
            <div className="text-xs text-muted-foreground group-hover:text-foreground transition-colors">
              Active mandates <ArrowRight className="inline h-3 w-3 ml-0.5" />
            </div>
          </Link>
        </div>

        {/* Alert feed */}
        <div className="rounded-xl border bg-card">
          <div className="flex items-center justify-between px-4 py-3 border-b">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold">Activity</h2>
              {unread.length > 0 && (
                <span className="h-4 min-w-4 px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-bold flex items-center justify-center">
                  {unread.length}
                </span>
              )}
            </div>
            {unread.length > 0 && (
              <button
                onClick={markAllAlertsRead}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <CheckCircle2 className="h-3.5 w-3.5" />
                Mark all read
              </button>
            )}
          </div>
          <div className="p-2 space-y-0.5">
            {alerts.slice(0, 6).map((a) => (
              <AlertRow key={a.id} alert={a} onRead={() => markAlertRead(a.id)} />
            ))}
          </div>
        </div>

        {/* Pending strategies preview */}
        {pending.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold">Ready for review</h2>
              <Link to="/office/inbox" className="text-xs text-primary hover:underline flex items-center gap-1">
                View all {pending.length} <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
            <div className="grid md:grid-cols-2 gap-3">
              {pending.slice(0, 2).map((s) => {
                const isUp = s.metrics.annual_return >= 0;
                return (
                  <Link
                    key={s.id}
                    to="/office/inbox"
                    className="rounded-xl border bg-card p-4 hover:border-primary/40 transition-all"
                  >
                    <div className="flex items-start justify-between gap-2 mb-3">
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">{s.market}</p>
                        <p className="text-sm font-semibold leading-tight">{s.name}</p>
                      </div>
                      <span className={cn("text-sm font-semibold font-mono", isUp ? "text-success" : "text-danger")}>
                        {s.metrics.sharpe.toFixed(2)} SR
                      </span>
                    </div>
                    <div className="flex gap-3 text-xs text-muted-foreground">
                      <span className={cn(isUp ? "text-success" : "text-danger")}>
                        {s.metrics.annual_return >= 0 ? "+" : ""}{s.metrics.annual_return.toFixed(1)}% ann.
                      </span>
                      <span>{s.metrics.max_drawdown.toFixed(1)}% DD</span>
                      <span>{s.metrics.win_rate.toFixed(0)}% win</span>
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        )}

        {pending.length === 0 && (
          <div className="rounded-xl border border-dashed bg-card/50 p-8 text-center">
            <CheckCircle2 className="h-8 w-8 text-success mx-auto mb-3 opacity-60" />
            <p className="text-sm font-medium">Inbox clear</p>
            <p className="text-xs text-muted-foreground mt-1">No strategies pending review. Agents are running.</p>
          </div>
        )}
      </div>
    </div>
  );
}
