import { useState } from "react";
import { Activity, ChevronDown, ChevronUp, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOfficeStore } from "@/stores/office";
import type { Agent, ActivityEntry } from "@/types/office";

type StatusFilter = "all" | "active" | "idle";

const STATUS_COLOR: Record<Agent["status"], string> = {
  idle:        "bg-muted-foreground/30",
  scanning:    "bg-info pulse-dot",
  backtesting: "bg-warning pulse-dot",
  encoding:    "bg-primary pulse-dot",
  surfacing:   "bg-success pulse-dot",
  complete:    "bg-success",
};

const STATUS_LABEL: Record<Agent["status"], string> = {
  idle: "Idle", scanning: "Scanning", backtesting: "Backtesting",
  encoding: "Encoding", surfacing: "Surfacing", complete: "Done",
};

const STATUS_TEXT: Record<Agent["status"], string> = {
  idle: "text-muted-foreground/50", scanning: "text-info", backtesting: "text-warning",
  encoding: "text-primary", surfacing: "text-success", complete: "text-success",
};

const TYPE_COLOR: Record<ActivityEntry["type"], string> = {
  scan: "text-info", backtest: "text-warning", signal: "text-success",
  complete: "text-success", encode: "text-primary", error: "text-danger",
};

function timeAgo(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function AgentRow({ agent, activity, expanded, onToggle }: {
  agent: Agent;
  activity: ActivityEntry[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const agentActivity = activity.filter(a => a.agent_id === agent.id).slice(0, 12);

  return (
    <>
      <tr
        className={cn(
          "border-b border-border/50 cursor-pointer transition-colors",
          expanded ? "bg-muted/10" : "hover:bg-muted/10"
        )}
        onClick={onToggle}
      >
        {/* Status + Name */}
        <td className="px-4 py-3">
          <div className="flex items-center gap-2.5">
            <div className={cn("h-1.5 w-1.5 rounded-full shrink-0", STATUS_COLOR[agent.status])} />
            <div>
              <p className="text-xs font-semibold">{agent.name}</p>
              <p className="text-[10px] text-muted-foreground">{agent.role}</p>
            </div>
          </div>
        </td>

        {/* Specialty */}
        <td className="px-4 py-3 hidden lg:table-cell">
          <p className="text-[10px] text-muted-foreground max-w-[180px] truncate">{agent.specialty}</p>
        </td>

        {/* Status badge */}
        <td className="px-4 py-3">
          <span className={cn("text-[10px] font-semibold", STATUS_TEXT[agent.status])}>
            {STATUS_LABEL[agent.status]}
          </span>
        </td>

        {/* Current task + progress */}
        <td className="px-4 py-3 max-w-[240px]">
          <p className="text-[10px] text-muted-foreground truncate">{agent.current_task}</p>
          {agent.status !== "idle" && agent.progress > 0 && (
            <div className="mt-1.5 h-0.5 rounded-full bg-muted overflow-hidden w-full max-w-[200px]">
              <div
                className={cn("h-full rounded-full transition-all duration-1000",
                  agent.status === "backtesting" ? "bg-warning" :
                  agent.status === "encoding" ? "bg-primary" : "bg-success"
                )}
                style={{ width: `${agent.progress}%` }}
              />
            </div>
          )}
        </td>

        {/* Backtests */}
        <td className="px-4 py-3 text-right hidden md:table-cell">
          <span className="metric-val text-xs font-semibold">{agent.backtests_run.toLocaleString()}</span>
        </td>

        {/* Surfaced */}
        <td className="px-4 py-3 text-right hidden md:table-cell">
          <span className={cn("metric-val text-xs font-semibold", agent.strategies_surfaced > 0 ? "text-success" : "text-muted-foreground")}>
            {agent.strategies_surfaced}
          </span>
        </td>

        {/* Last active */}
        <td className="px-4 py-3 text-right hidden sm:table-cell">
          <span className="text-[10px] text-muted-foreground">{timeAgo(agent.last_active)}</span>
        </td>

        {/* Expand toggle */}
        <td className="px-3 py-3">
          {expanded
            ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
            : <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          }
        </td>
      </tr>

      {/* Expanded detail row */}
      {expanded && (
        <tr className="border-b border-border/50 bg-muted/5">
          <td colSpan={8} className="px-4 py-3">
            <div className="grid grid-cols-3 gap-4">

              {/* Stats */}
              <div className="space-y-2">
                <p className="label-caps mb-2">Agent Stats</p>
                {[
                  { label: "Backtests run",       value: agent.backtests_run.toLocaleString() },
                  { label: "Strategies surfaced", value: String(agent.strategies_surfaced) },
                  { label: "Last active",         value: timeAgo(agent.last_active) },
                  { label: "Current progress",    value: agent.progress > 0 ? `${agent.progress}%` : "—" },
                ].map(({ label, value }) => (
                  <div key={label} className="flex items-center justify-between">
                    <span className="text-[10px] text-muted-foreground">{label}</span>
                    <span className="metric-val text-[10px] font-semibold">{value}</span>
                  </div>
                ))}
              </div>

              {/* Activity log — spans 2 cols */}
              <div className="col-span-2">
                <p className="label-caps mb-2">Recent Activity</p>
                {agentActivity.length === 0 ? (
                  <p className="text-[10px] text-muted-foreground">No activity recorded.</p>
                ) : (
                  <div className="space-y-1">
                    {agentActivity.map(entry => (
                      <div key={entry.id} className="flex items-start gap-2">
                        <span className={cn("text-[9px] font-semibold mt-0.5 shrink-0", TYPE_COLOR[entry.type])}>
                          {entry.type.toUpperCase()}
                        </span>
                        <p className="text-[10px] text-muted-foreground leading-snug flex-1">{entry.message}</p>
                        <span className="text-[9px] text-muted-foreground/40 shrink-0 ml-2">{timeAgo(entry.timestamp)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export function Agents() {
  const { agents, activity } = useOfficeStore();
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const active = agents.filter(a => a.status !== "idle");
  const totalBacktests = agents.reduce((s, a) => s + a.backtests_run, 0);
  const totalSurfaced = agents.reduce((s, a) => s + a.strategies_surfaced, 0);

  const statusGroups = {
    backtesting: agents.filter(a => a.status === "backtesting").length,
    scanning:    agents.filter(a => a.status === "scanning").length,
    encoding:    agents.filter(a => a.status === "encoding").length,
    surfacing:   agents.filter(a => a.status === "surfacing").length,
    idle:        agents.filter(a => a.status === "idle").length,
  };

  const filtered = agents
    .filter(a => filter === "all" ? true : filter === "active" ? a.status !== "idle" : a.status === "idle")
    .filter(a => !search || a.name.toLowerCase().includes(search.toLowerCase()) || a.specialty.toLowerCase().includes(search.toLowerCase()));

  const FILTERS: { id: StatusFilter; label: string; count: number }[] = [
    { id: "all",    label: "All",    count: agents.length },
    { id: "active", label: "Active", count: active.length },
    { id: "idle",   label: "Idle",   count: agents.length - active.length },
  ];

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b bg-card/50 sticky top-0 z-10 backdrop-blur-sm">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h1 className="text-base font-semibold">Agent Fleet</h1>
              <p className="text-[10px] text-muted-foreground mt-0.5">
                {agents.length} agents · {active.length} active · {totalBacktests.toLocaleString()} backtests · {totalSurfaced} strategies surfaced
              </p>
            </div>
          </div>

          {/* Status summary chips */}
          <div className="flex items-center gap-2 mb-3">
            {Object.entries(statusGroups).map(([status, count]) => count > 0 && (
              <div key={status} className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-muted/40">
                <div className={cn("h-1.5 w-1.5 rounded-full", STATUS_COLOR[status as Agent["status"]])} />
                <span className="text-[10px] font-semibold">{count}</span>
                <span className="text-[10px] text-muted-foreground capitalize">{status}</span>
              </div>
            ))}
          </div>

          {/* Aggregate throughput */}
          <div className="grid grid-cols-4 gap-2 mb-3">
            {[
              { label: "Total Agents",   value: agents.length,                        color: "text-foreground" },
              { label: "Active Now",     value: active.length,                        color: active.length > 0 ? "text-success" : "text-muted-foreground" },
              { label: "Backtests Run",  value: totalBacktests.toLocaleString(),      color: "text-warning" },
              { label: "Strats Surfaced", value: totalSurfaced,                       color: "text-primary" },
            ].map(({ label, value, color }) => (
              <div key={label} className="rounded-lg border bg-card p-2.5">
                <div className={cn("metric-val text-lg font-semibold", color)}>{value}</div>
                <div className="label-caps mt-0.5">{label}</div>
              </div>
            ))}
          </div>

          {/* Filters + search */}
          <div className="flex items-center gap-3">
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
                  <span className={cn("h-4 min-w-4 px-1 rounded-full text-[9px] font-bold flex items-center justify-center",
                    filter === f.id ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                  )}>{f.count}</span>
                </button>
              ))}
            </div>
            <div className="ml-auto relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground pointer-events-none" />
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search agents..."
                className="pl-7 pr-3 py-1.5 rounded-lg border bg-background text-xs w-48 focus:outline-none focus:ring-1 focus:ring-primary/30"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Fleet table */}
      <div className="px-6 py-4">
        <div className="rounded-lg border bg-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b bg-muted/20">
                  {[
                    { label: "Agent",          cls: "text-left px-4 py-2.5" },
                    { label: "Specialty",      cls: "text-left px-4 py-2.5 hidden lg:table-cell" },
                    { label: "Status",         cls: "text-left px-4 py-2.5" },
                    { label: "Current Task",   cls: "text-left px-4 py-2.5" },
                    { label: "Backtests",      cls: "text-right px-4 py-2.5 hidden md:table-cell" },
                    { label: "Surfaced",       cls: "text-right px-4 py-2.5 hidden md:table-cell" },
                    { label: "Last Active",    cls: "text-right px-4 py-2.5 hidden sm:table-cell" },
                    { label: "",               cls: "px-3 py-2.5 w-8" },
                  ].map(({ label, cls }) => (
                    <th key={label} className={cn(cls, "label-caps")} style={{ fontSize: "9px" }}>{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center">
                      <Activity className="h-5 w-5 text-muted-foreground/30 mx-auto mb-2" />
                      <p className="text-xs text-muted-foreground">No agents match filter</p>
                    </td>
                  </tr>
                ) : (
                  filtered.map(agent => (
                    <AgentRow
                      key={agent.id}
                      agent={agent}
                      activity={activity}
                      expanded={expanded === agent.id}
                      onToggle={() => setExpanded(expanded === agent.id ? null : agent.id)}
                    />
                  ))
                )}
              </tbody>
            </table>
          </div>

          {agents.length > 0 && (
            <div className="px-4 py-2 border-t bg-muted/10 flex items-center justify-between">
              <span className="text-[10px] text-muted-foreground">{filtered.length} of {agents.length} agents shown</span>
              <span className="text-[10px] text-muted-foreground/40">Click any row to expand activity log</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
