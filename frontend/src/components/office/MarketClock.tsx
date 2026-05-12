import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface Session { label: string; open: boolean; tz: string; hours: string; }

function getSessions(): Session[] {
  const now = new Date();
  const hkt = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Hong_Kong" }));
  const et  = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));

  const hktH = hkt.getHours(), hktM = hkt.getMinutes();
  const etH  = et.getHours(),  etM  = et.getMinutes();

  const hktMins = hktH * 60 + hktM;
  const etMins  = etH  * 60 + etM;

  const hkOpen  = hktMins >= 9 * 60 + 30 && hktMins < 16 * 60;
  const usOpen  = etMins  >= 9 * 60 + 30 && etMins  < 16 * 60;

  return [
    { label: "HK",     open: hkOpen, tz: "HKT",  hours: "09:30–16:00" },
    { label: "US",     open: usOpen, tz: "ET",   hours: "09:30–16:00" },
    { label: "Crypto", open: true,   tz: "24/7", hours: "Always open" },
  ];
}

export function MarketClock() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const sessions = getSessions();
  const hkt = time.toLocaleTimeString("en-US", { timeZone: "Asia/Hong_Kong", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

  return (
    <div className="flex items-center gap-3">
      {/* Live clock */}
      <span className="metric-val text-xs text-muted-foreground tabular-nums">{hkt} HKT</span>

      {/* Session pills */}
      <div className="flex items-center gap-1.5">
        {sessions.map((s) => (
          <div
            key={s.label}
            title={`${s.label} ${s.hours} ${s.tz}`}
            className={cn(
              "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium",
              s.open
                ? "bg-success/10 text-success"
                : "bg-muted text-muted-foreground/50"
            )}
          >
            <span className={cn("h-1.5 w-1.5 rounded-full", s.open ? "bg-success pulse-dot" : "bg-muted-foreground/30")} />
            {s.label}
          </div>
        ))}
      </div>
    </div>
  );
}
