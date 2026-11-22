/**
 * A procedural brain as a point cloud: two cerebral hemispheres with a fissure between them and
 * folded (gyri-like) surfaces, temporal lobes bulging low at the sides, a finely folded cerebellum
 * at the back and a brain stem running down into the energy strands. Each point carries its lobe,
 * so the brain can light up where it "thinks". Pure and deterministic; unit-tested.
 *
 * Axes: +x front, +y up, z left/right. Units: the cerebrum is about 1.7 long, 1.2 tall, 1.3 wide.
 */
import { rng } from '../glass';

export const LOBES = ['frontal', 'parietal', 'temporal', 'occipital', 'cerebellum', 'stem'] as const;
export type Lobe = (typeof LOBES)[number];
export const L = Object.fromEntries(LOBES.map((l, i) => [l, i])) as Record<Lobe, number>;

export const STEM_BOTTOM = -1.15;
const HEMI = { cx: 0, cy: 0.08, cz: 0.31, rx: 0.86, ry: 0.62, ryLow: 0.44, rz: 0.33 };
const CEREBELLUM = { cx: -0.6, cy: -0.42, rx: 0.3, ry: 0.2, rz: 0.52 };

/** Folds on the cortex: a few crossed sine ridges, enough to read as gyri and sulci. */
export function gyri(x: number, y: number, z: number): number {
  return 0.035 * (Math.sin(x * 11 + Math.sin(z * 7) * 1.5) * Math.sin(y * 13 + Math.sin(x * 5)) + 0.5 * Math.sin(z * 17 + y * 9));
}

export function lobeOf(x: number, y: number): Lobe {
  if (x > 0.28) return 'frontal';
  if (x < -0.42) return 'occipital';
  if (y < -0.06) return 'temporal';
  return 'parietal';
}

export interface BrainCloud { pos: Float32Array; lobe: Uint8Array; phase: Float32Array; count: number }

function unit(r: () => number): [number, number, number] {
  const u = r() * 2 - 1, a = r() * Math.PI * 2, s = Math.sqrt(1 - u * u);
  return [s * Math.cos(a), u, s * Math.sin(a)];
}

export function brainCloud(count: number, seed = 7): BrainCloud {
  const r = rng(seed);
  const pos = new Float32Array(count * 3), lobe = new Uint8Array(count), phase = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const pick = r();
    const shell = r() < 0.85 ? 1 : 0.45 + r() * 0.45;          // most points on the cortex, some inside
    let x: number, y: number, z: number, lb: Lobe;
    if (pick < 0.8) {                                           // cerebrum, alternating hemispheres
      const side = i % 2 ? 1 : -1;
      // Prefer the ridges of the folds, so the gyri read as lines of light.
      let [dx, dy, dz] = unit(r);
      for (let tries = 0; tries < 6 && gyri(dx, dy, dz) < 0.012 && shell === 1; tries++) [dx, dy, dz] = unit(r);
      const ry = dy >= 0 ? HEMI.ry : HEMI.ryLow;
      const k = shell * (1 + gyri(dx, dy, dz));
      x = HEMI.cx + dx * HEMI.rx * k;
      y = HEMI.cy + dy * ry * k;
      // The inner faces of the hemispheres are flatter (the fissure); temporal lobes bulge out low.
      const inward = dz * side < 0;
      const low = Math.max(0, -dy) * (1 - Math.abs(dx - 0.05) * 0.8);
      z = side * HEMI.cz + dz * HEMI.rz * k * (inward ? 0.55 : 1 + low * 0.35);
      lb = lobeOf(x, y);
    } else if (pick < 0.94) {                                   // cerebellum: fine horizontal folds
      const [dx, dy, dz] = unit(r);
      const k = shell * (1 + 0.04 * Math.sin(dy * 40));
      x = CEREBELLUM.cx + dx * CEREBELLUM.rx * k; y = CEREBELLUM.cy + dy * CEREBELLUM.ry * k; z = dz * CEREBELLUM.rz * k;
      lb = 'cerebellum';
    } else {                                                    // brain stem down into the strands
      const t = r(), a = r() * Math.PI * 2, rad = (0.13 - 0.05 * t) * (0.6 + 0.4 * shell);
      x = -0.3 + 0.08 * t + Math.cos(a) * rad; y = -0.32 + (STEM_BOTTOM + 0.32) * t; z = Math.sin(a) * rad;
      lb = 'stem';
    }
    pos.set([x, y, z], i * 3);
    lobe[i] = L[lb];
    phase[i] = r();
  }
  return { pos, lobe, phase, count };
}

export interface Synapses { a: Uint32Array; b: Uint32Array; phase: Float32Array; rate: Float32Array; count: number }

/**
 * Candidate synapses: each node to its k nearest neighbours (unique pairs), plus a few long fibres
 * across the hemispheres (corpus callosum). Which of them are alive changes all the time (shader).
 */
export const MAX_SYNAPSE = 0.13;   // local synapses longer than this would read as scratches

export function synapses(cloud: BrainCloud, k = 3, cross = 0, seed = 3): Synapses {
  const { pos, count } = cloud;
  const r = rng(seed);
  const seen = new Set<number>();
  const a: number[] = [], b: number[] = [];
  const add = (i: number, j: number) => { const key = i < j ? i * count + j : j * count + i; if (i !== j && !seen.has(key)) { seen.add(key); a.push(i); b.push(j); } };
  const best = new Float64Array(k), idx = new Int32Array(k);
  for (let i = 0; i < count; i++) {
    best.fill(Infinity); idx.fill(-1);
    const xi = pos[i * 3], yi = pos[i * 3 + 1], zi = pos[i * 3 + 2];
    for (let j = 0; j < count; j++) {
      if (j === i) continue;
      const d = (pos[j * 3] - xi) ** 2 + (pos[j * 3 + 1] - yi) ** 2 + (pos[j * 3 + 2] - zi) ** 2;
      if (d >= best[k - 1]) continue;
      let m = k - 1;
      while (m > 0 && best[m - 1] > d) { best[m] = best[m - 1]; idx[m] = idx[m - 1]; m--; }
      best[m] = d; idx[m] = j;
    }
    for (let m = 0; m < k; m++) if (idx[m] >= 0 && best[m] <= MAX_SYNAPSE * MAX_SYNAPSE) add(i, idx[m]);
  }
  // Long fibres between the hemispheres.
  const cerebrum = Array.from({ length: count }, (_, i) => i).filter((i) => cloud.lobe[i] <= L.occipital);
  const left = cerebrum.filter((i) => pos[i * 3 + 2] < 0), right = cerebrum.filter((i) => pos[i * 3 + 2] > 0);
  const fibres = Math.round(a.length * cross);
  for (let f = 0; f < fibres && left.length && right.length; f++) add(left[Math.floor(r() * left.length)], right[Math.floor(r() * right.length)]);
  const n = a.length;
  const phase = new Float32Array(n), rate = new Float32Array(n);
  for (let e = 0; e < n; e++) { phase[e] = r(); rate[e] = 0.05 + r() * 0.15; }
  return { a: Uint32Array.from(a), b: Uint32Array.from(b), phase, rate, count: n };
}
