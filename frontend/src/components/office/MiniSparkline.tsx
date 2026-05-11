interface Props {
  data: Array<{ t: number; v: number }>;
  width?: number;
  height?: number;
  positive?: boolean;
}

export function MiniSparkline({ data, width = 120, height = 36, positive }: Props) {
  if (!data || data.length < 2) return null;
  const vals = data.map((d) => d.v);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = max - min || 1;
  const pad = 2;
  const w = width - pad * 2;
  const h = height - pad * 2;
  const pts = data.map((d, i) => {
    const x = pad + (i / (data.length - 1)) * w;
    const y = pad + (1 - (d.v - min) / range) * h;
    return `${x},${y}`;
  });
  const isUp = positive ?? vals[vals.length - 1] >= vals[0];
  const color = isUp ? "hsl(142 71% 45%)" : "hsl(0 62% 50%)";
  const fill = isUp ? "hsl(142 71% 45% / 0.08)" : "hsl(0 62% 50% / 0.08)";
  const last = pts[pts.length - 1];
  const [lx, ly] = last.split(",").map(Number);

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      <defs>
        <linearGradient id={`sg-${isUp}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.15" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline
        points={[...pts, `${lx},${pad + h}`, `${pad},${pad + h}`].join(" ")}
        fill={fill}
        stroke="none"
      />
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r="2.5" fill={color} />
    </svg>
  );
}
