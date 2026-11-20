const W = 260, H = 44, PAD = 2;

/** Dependency-free sparkline of real samples. Never draws a line without data. Screen readers get the numbers. */
export function Spark({ label, data, unit, max, tone = 'cyan' }: { label: string; data: number[]; unit: string; max?: number; tone?: 'cyan' | 'amber' }) {
  const last = data.length ? data[data.length - 1] : null;
  const hi = max ?? Math.max(1, ...data);
  const pts = data.length < 2 ? '' : data.map((v, i) => {
    const x = PAD + (i / (data.length - 1)) * (W - 2 * PAD);
    const y = H - PAD - (Math.min(Math.max(v, 0), hi) / hi) * (H - 2 * PAD);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const summary = last === null ? `${label}: no samples yet`
    : `${label}: now ${Math.round(last)}${unit}, min ${Math.round(Math.min(...data))}, max ${Math.round(Math.max(...data))} over ${data.length} s`;
  return (
    <figure className="spark" data-tone={tone}>
      <figcaption><span>{label}</span><span>{last === null ? '--' : `${Math.round(last)}${unit}`}</span></figcaption>
      {max !== undefined && <div className="spark-meter" aria-hidden><i style={{ width: `${last === null ? 0 : Math.min(100, (Math.max(0, last) / max) * 100)}%` }} /></div>}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary} preserveAspectRatio="none">
        <line x1="0" y1={H - PAD} x2={W} y2={H - PAD} className="spark-base" />
        {pts && <polygon points={`${PAD},${H - PAD} ${pts} ${W - PAD},${H - PAD}`} className="spark-area" />}
        {pts ? <polyline points={pts} className="spark-line" /> : <text x="8" y="26" className="spark-empty">collecting…</text>}
      </svg>
    </figure>
  );
}
