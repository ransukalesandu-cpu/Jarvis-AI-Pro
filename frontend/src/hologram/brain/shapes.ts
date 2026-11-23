/**
 * Point-cloud shapes the brain can flow into (same closed set as jarvis/core/brain_shapes.py).
 * Every generator returns exactly `n` points in brain space (about 0.75 in radius, centred where
 * the brain is), facing the camera (+z). Pure and deterministic; text comes from a raster mask.
 */
// No imports: the bridge contract uses this file, so it stays free of three.js.
function rng(seed: number) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}

export const SHAPES = ['brain', 'sphere', 'cube', 'torus', 'helix', 'heart', 'globe', 'star', 'text'] as const;
export type ShapeName = (typeof SHAPES)[number];
export const TEXT_MAX = 16;
export const TEXT_OK = /^[A-Za-z0-9 .!?&+\-]*$/;
export const CENTER_Y = -0.05;

type Gen = (n: number, r: () => number) => Float32Array;

const out = (n: number, f: (i: number) => [number, number, number]) => {
  const a = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) a.set(f(i), i * 3);
  return a;
};

const sphere: Gen = (n) => out(n, (i) => {
  const y = 1 - (2 * (i + 0.5)) / n, rad = Math.sqrt(1 - y * y), th = i * 2.399963;
  return [Math.cos(th) * rad * 0.72, CENTER_Y + y * 0.72, Math.sin(th) * rad * 0.72];
});

const cube: Gen = (n, r) => out(n, () => {
  const s = 0.48, p = [r() * 2 - 1, r() * 2 - 1, r() * 2 - 1];
  const axis = Math.floor(r() * 3);
  p[axis] = r() < 0.5 ? -1 : 1;                                   // on a face
  if (r() < 0.4) { const b = (axis + 1) % 3; p[b] = r() < 0.5 ? -1 : 1; }   // 40% on the edges
  const c = Math.cos(0.6), sn = Math.sin(0.6), x = p[0] * c - p[2] * sn, z = p[0] * sn + p[2] * c;  // turned to show 3 faces
  const ct = Math.cos(0.45), st = Math.sin(0.45), y = p[1] * ct - z * st, z2 = p[1] * st + z * ct;
  return [x * s, CENTER_Y + y * s, z2 * s];
});

const torus: Gen = (n, r) => out(n, () => {
  const u = r() * Math.PI * 2, v = r() * Math.PI * 2, R = 0.55, rr = 0.2;
  const x = (R + rr * Math.cos(v)) * Math.cos(u), y = (R + rr * Math.cos(v)) * Math.sin(u), z = rr * Math.sin(v);
  const t = 1.1, c = Math.cos(t), s = Math.sin(t);
  return [x, CENTER_Y + y * c - z * s, y * s + z * c];
});

const helix: Gen = (n, r) => out(n, (i) => {
  const t = r(), ang = t * Math.PI * 2 * 3, y = CENTER_Y + (t - 0.5) * 1.6, rad = 0.3;
  if (i % 5 === 0) {                                              // rungs between the strands
    const k = Math.round(t * 30) / 30, a = k * Math.PI * 2 * 3, f = r() * 2 - 1;
    return [Math.cos(a) * rad * f, CENTER_Y + (k - 0.5) * 1.6, Math.sin(a) * rad * f];
  }
  const off = i % 2 ? Math.PI : 0, j = (r() - 0.5) * 0.03;
  return [Math.cos(ang + off) * rad + j, y, Math.sin(ang + off) * rad + j];
});

/** Inside the classic heart curve (x^2 + y^2 - 1)^3 - x^2 y^3 <= 0, as a puffy 3D heart. */
export const inHeart = (x: number, y: number) => (x * x + y * y - 1) ** 3 - x * x * y ** 3 <= 0;
const heart: Gen = (n, r) => out(n, (i) => {
  const k = 0.62;
  if (i % 3 === 0) {                                              // a third on the outline, so the shape reads
    const t = r() * Math.PI * 2;
    const hx = 16 * Math.sin(t) ** 3, hy = 13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t);
    return [hx / 17 * k * 1.1, CENTER_Y + (hy / 17 + 0.05) * k * 1.1, (r() - 0.5) * 0.06];
  }
  for (;;) {                                                      // the rest fill it evenly
    const x = r() * 2.4 - 1.2, y = r() * 2.4 - 1.1;
    if (!inHeart(x, y)) continue;
    const depth = Math.sqrt(Math.max(0, 1 - (x * x + (y - 0.2) ** 2) / 1.6)) * 0.22;
    return [x * k, CENTER_Y + (y - 0.15) * k, (r() * 2 - 1) * depth];
  }
});

const globe: Gen = (n, r) => out(n, (i) => {
  const R = 0.72;
  let lat: number, lon: number;
  if (i % 2 === 0) { lat = (Math.round((r() - 0.5) * 8) / 8) * Math.PI; lon = r() * Math.PI * 2; }   // parallels
  else { lon = (Math.round(r() * 12) / 12) * Math.PI * 2; lat = (r() - 0.5) * Math.PI; }               // meridians
  const tilt = 0.4, x = Math.cos(lat) * Math.cos(lon), y = Math.sin(lat), z = Math.cos(lat) * Math.sin(lon);
  return [x * R, CENTER_Y + (y * Math.cos(tilt) - z * Math.sin(tilt)) * R, (y * Math.sin(tilt) + z * Math.cos(tilt)) * R];
});

const star: Gen = (n, r) => out(n, () => {
  const spike = Math.floor(r() * 10), a0 = (spike / 10) * Math.PI * 2 + Math.PI / 2, a1 = ((spike + 1) / 10) * Math.PI * 2 + Math.PI / 2;
  const R0 = spike % 2 ? 0.32 : 0.78, R1 = spike % 2 ? 0.78 : 0.32;
  const u = r(), v = Math.sqrt(r());                              // a point in the triangle centre-p0-p1
  const px = (Math.cos(a0) * R0 * (1 - u) + Math.cos(a1) * R1 * u) * v, py = (Math.sin(a0) * R0 * (1 - u) + Math.sin(a1) * R1 * u) * v;
  return [px, CENTER_Y + py, (r() - 0.5) * 0.18 * (1 - v * 0.7)];
});

/** Points spread over the lit pixels of a text mask (w x h, row 0 at the top), `width` wide in brain space. */
export function textPoints(mask: Uint8Array, w: number, h: number, n: number, width = 1.9, seed = 5): Float32Array {
  const lit: number[] = [];
  for (let i = 0; i < w * h; i++) if (mask[i] > 127) lit.push(i);
  const r = rng(seed), scale = width / w;
  return out(n, () => {
    if (!lit.length) return [0, CENTER_Y, 0];
    const p = lit[Math.floor(r() * lit.length)], x = (p % w) + r(), y = Math.floor(p / w) + r();
    return [(x - w / 2) * scale, CENTER_Y + (h / 2 - y) * scale, (r() - 0.5) * 0.03];
  });
}

const GENERATORS: Record<Exclude<ShapeName, 'brain' | 'text'>, Gen> = { sphere, cube, torus, helix, heart, globe, star };

export function shapePoints(shape: Exclude<ShapeName, 'brain' | 'text'>, n: number, seed = 9): Float32Array {
  return GENERATORS[shape](n, rng(seed));
}

/**
 * Which target point each node flows to: both sets are ordered top to bottom (then left to right),
 * so nodes travel short, mostly vertical paths and the morph reads as the brain reshaping itself.
 */
export function assign(from: Float32Array, to: Float32Array): Float32Array {
  const n = from.length / 3;
  const order = (a: Float32Array) => Array.from({ length: n }, (_, i) => i).sort((i, j) => (a[j * 3 + 1] - a[i * 3 + 1]) || (a[i * 3] - a[j * 3]));
  const fo = order(from), tor = order(to);
  const res = new Float32Array(n * 3);
  for (let k = 0; k < n; k++) res.set(to.subarray(tor[k] * 3, tor[k] * 3 + 3), fo[k] * 3);
  return res;
}

export function validText(text: string): boolean {
  return text.length <= TEXT_MAX && TEXT_OK.test(text);
}
