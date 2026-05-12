import { useEffect, useRef, useState } from "react";
import { ChevronRight, ChevronLeft, Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOfficeStore } from "@/stores/office";
import type { Agent, ActivityEntry } from "@/types/office";

const STATUS_COLOR: Record<Agent["status"], string> = {
  idle:       "bg-muted-foreground/40",
  scanning:   "bg-info pulse-dot",
  backtesting:"bg-warning pulse-dot",
  encoding:   "bg-primary pulse-dot",
  surfacing:  "bg-success pulse-dot",
  complete:   "bg-success",
};

const STATUS_LABEL: Record<Agent["status"], string> = {
  idle: "Idle", scanning: "Scanning", backtesting: "Backtesting",
  encoding: "Encoding", surfacing: "Surfacing", complete: "Done",
};

const TYPE_COLOR: Record<ActivityEntry["type"], string> = {
  scan:     "text-info",
  backtest: "text-warning",
  signal:   "text-success",
  complete: "text-success",
  encode:   "text-primary",
  error:    "text-danger",
};

function timeAgo(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60)   return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h`;
}

// Simulate agents doing things — updates progress and pushes activity entries
function useAgentSimulation() {
  const { agents, pushActivity, updateAgentStatus } = useOfficeStore();
  const tickRef = useRef(0);

  useEffect(() => {
    const t = setInterval(() => {
      tickRef.current++;
      const tick = tickRef.current;

      // Momentum scanner: advance backtest progress
      if (tick % 8 === 0) {
        const ms = agents.find(a => a.id === "momentum-scanner");
        if (ms && ms.status === "backtesting") {
          const newProgress = Math.min((ms.progress + 12), 100);
          const window = Math.floor(newProgress / 12.5);
          updateAgentStatus("momentum-scanner", {
            progress: newProgress,
            current_task: newProgress >= 100
              ? "Walk-forward complete — surfacing candidates"
              : `Running walk-forward on HSI universe — pass ${window} of 8`,
            status: newProgress >= 100 ? "surfacing" : "backtesting",
          });
          if (newProgress < 100) {
            pushActivity({ agent_id: "momentum-scanner", agent_name: "momentum-scanner", type: "backtest", message: `Walk-forward window ${window}/8 — Sharpe ${(1.1 + Math.random() * 0.5).toFixed(2)} OOS` });
          } else {
            pushActivity({ agent_id: "momentum-scanner", agent_name: "momentum-scanner", type: "signal", message: "Walk-forward complete — 2 candidates cleared threshold, surfacing to inbox" });
          }
        }
      }

      // Macro encoder: advance encoding
      if (tick % 12 === 0) {
        const me = agents.find(a => a.id === "macro-encoder");
        if (me && me.status === "encoding") {
          const newProgress = Math.min(me.progress + 8, 100);
          const articles = Math.floor(newProgress * 0.14);
          updateAgentStatus("macro-encoder", {
            progress: newProgress,
            current_task: newProgress >= 100
              ? "Encoding complete — building strategy object"
              : `Processing ${articles} of 14 articles`,
            status: newProgress >= 100 ? "surfacing" : "encoding",
          });
          if (tick % 24 === 0) {
            pushActivity({ agent_id: "macro-encoder", agent_name: "macro-encoder", type: "encode", message: `Fed language model: dovish pivot probability ${(45 + Math.random() * 20).toFixed(0)}%` });
          }
        }
      }

      // Crypto scanner: update z-scores
      if (tick % 5 === 0) {
        const cs = agents.find(a => a.id === "crypto-scanner");
        if (cs && cs.status === "scanning") {
          const z = (1.5 + Math.random() * 1.5).toFixed(2);
          const pairs = ["BTC/ETH", "ETH/SOL", "BTC/SOL", "SOL/AVAX"];
          const pair = pairs[tick % pairs.length];
          updateAgentStatus("crypto-scanner", {
            progress: Math.min(cs.progress + 1, 99),
            current_task: `Scanning ${pair} — z-score ${z}`,
          });
          if (tick % 15 === 0) {
            const crossed = parseFloat(z) > 2.3;
            pushActivity({ agent_id: "crypto-scanner", agent_name: "crypto-scanner", type: "scan", message: `${pair} z-score ${z}${crossed ? " — threshold crossed, initiating backtest" : ""}` });
          }
        }
      }

      // Risk monitor: periodic check
      if (tick % 20 === 0) {
        pushActivity({ agent_id: "risk-monitor", agent_name: "risk-monitor", type: "scan", message: `Book check — max correlation pair: 0.${18 + Math.floor(Math.random() * 15)} ✓` });
        updateAgentStatus("risk-monitor", { current_task: `Next check in ${20 - (tick % 20)}m` });
      }
    }, 3000);

    return () => clearInterval(t);
  }, [agents, pushActivity, updateAgentStatus]);
}

interface Props {
  collapsed: boolean;
  onToggle: () => void;
}

export function AgentPanel({ collapsed, onToggle }: Props) {
  useAgentSimulation();
  const { agents, activity } = useOfficeStore();
  const activityRef = useRef<HTMLDivElement>(null);
  const [prevActivityLen, setPrevActivityLen] = useState(activity.length);

  // Track new entries for animation
  const newCount = activity.length - prevActivityLen;
  useEffect(() => {
    if (activity.length !== prevActivityLen) setPrevActivityLen(activity.length);
  }, [activity.length, prevActivityLen]);

  const activeAgents = agents.filter(a => a.status !== "idle").length;

  return (
    <aside className={cn(
      "border-l bg-card flex flex-col shrink-0 transition-all duration-300 relative",
      collapsed ? "w-10" : "w-64"
    )}>
      {/* Toggle button */}
      <button
        onClick={onToggle}
        className="absolute -left-3 top-6 z-10 h-6 w-6 rounded-full border bg-card flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted transition-colors shadow-sm"
      >
        {collapsed ? <ChevronLeft className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
      </button>

      {collapsed ? (
        /* Collapsed: just a pulsing activity indicator */
        <div className="flex flex-col items-center gap-3 pt-4">
          <Activity className="h-4 w-4 text-muted-foreground/60" />
          {activeAgents > 0 && (
            <div className="flex flex-col items-center gap-1.5">
              {agents.filter(a => a.status !== "idle").map(a => (
                <div key={a.id} title={`${a.name}: ${a.current_task}`}>
                  <div className={cn("h-1.5 w-1.5 rounded-full", STATUS_COLOR[a.status])} />
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <>
          {/* Header */}
          <div className="px-3 py-3 border-b">
            <div className="flex items-center gap-2">
              <Activity className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="label-caps">Trading Floor</span>
              {activeAgents > 0 && (
                <span className="ml-auto h-4 min-w-4 px-1 rounded-full bg-success/10 text-success text-[10px] font-bold flex items-center justify-center">
                  {activeAgents}
                </span>
              )}
            </div>
          </div>

          {/* Agent roster */}
          <div className="px-2 pt-2 pb-2 space-y-1 border-b">
            {agents.map((agent) => (
              <div key={agent.id} className="rounded-md px-2 py-2 hover:bg-muted/40 transition-colors">
                <div className="flex items-center gap-2 mb-1">
                  <div className={cn("h-1.5 w-1.5 rounded-full shrink-0", STATUS_COLOR[agent.status])} />
                  <span className="text-xs font-medium truncate flex-1">{agent.name}</span>
                  <span className={cn("text-[10px] font-medium shrink-0",
                    agent.status === "idle" ? "text-muted-foreground/50" :
                    agent.status === "surfacing" ? "text-success" :
                    agent.status === "backtesting" ? "text-warning" :
                    agent.status === "encoding" ? "text-primary" :
                    "text-info"
                  )}>
                    {STATUS_LABEL[agent.status]}
                  </span>
                </div>
                <p className="text-[10px] text-muted-foreground leading-tight truncate pl-3.5">
                  {agent.current_task}
                </p>
                {agent.status !== "idle" && agent.progress > 0 && (
                  <div className="mt-1.5 ml-3.5 h-0.5 rounded-full bg-muted overflow-hidden">
                    <div
                      className={cn("h-full rounded-full transition-all duration-1000",
                        agent.status === "backtesting" ? "bg-warning" :
                        agent.status === "encoding" ? "bg-primary" :
                        agent.status === "surfacing" ? "bg-success" : "bg-info"
                      )}
                      style={{ width: `${agent.progress}%` }}
                    />
                  </div>
                )}
                <div className="flex items-center gap-2 mt-1 pl-3.5">
                  <span className="text-[10px] text-muted-foreground/50">{timeAgo(agent.last_active)} ago</span>
                  <span className="text-[10px] text-muted-foreground/40">·</span>
                  <span className="text-[10px] text-muted-foreground/50">{agent.strategies_surfaced} surfaced</span>
                </div>
              </div>
            ))}
          </div>

          {/* Live activity log */}
          <div className="flex-1 overflow-hidden flex flex-col">
            <div className="px-3 py-2 border-b">
              <span className="label-caps">Activity</span>
            </div>
            <div ref={activityRef} className="flex-1 overflow-y-auto px-2 py-1 space-y-0.5">
              {activity.slice(0, 20).map((entry, i) => (
                <div
                  key={entry.id}
                  className={cn("px-2 py-1.5 rounded text-[10px] leading-snug", i < newCount && "slide-in")}
                >
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span className={cn("font-medium", TYPE_COLOR[entry.type])}>{entry.agent_name}</span>
                    <span className="text-muted-foreground/40 ml-auto shrink-0">{timeAgo(entry.timestamp)}</span>
                  </div>
                  <p className="text-muted-foreground leading-tight">{entry.message}</p>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </aside>
  );
}
