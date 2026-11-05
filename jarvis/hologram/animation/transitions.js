// Frame-rate independent smoothing helpers. No allocation, no DOM.

export function damp(current, target, rate, dt) {
  if (!Number.isFinite(current)) return Number.isFinite(target) ? target : 0;
  if (!Number.isFinite(target)) return current;
  const d = Math.max(0, Math.min(0.25, dt));
  return current + (target - current) * (1 - Math.exp(-Math.max(0.1, rate) * d));
}

export const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
export const smoothstep = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

/** Move every numeric field of `cur` toward `tgt` (same keys). Returns cur. */
export function dampParams(cur, tgt, rates, defaultRate, dt) {
  for (const k in tgt) cur[k] = damp(cur[k] ?? tgt[k], tgt[k], rates[k] ?? defaultRate, dt);
  return cur;
}
