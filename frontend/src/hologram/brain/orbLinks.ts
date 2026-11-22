/**
 * Neural links from the brain to the orb: long neurons leave the brain stem and the brain's
 * underside and curve down into the top of the orb. Pure: anchors and per-link shape are chosen
 * once; the curves are re-evaluated each frame because the brain sways while the orb stays put.
 */
import { rng } from '../glass';
import { type BrainCloud, L } from './brainShape';

export const LINK_STEPS = 18;

export interface OrbLink { anchor: number; end: [number, number, number]; bend: [number, number, number]; phase: number; rate: number }

/** Picks `count` anchor neurons (stem first, then the brain's underside) and where each lands on the orb. */
export function orbLinks(cloud: BrainCloud, count: number, orb: { x: number; y: number; z: number; r: number }, seed = 23): OrbLink[] {
  const r = rng(seed);
  const y = (i: number) => cloud.pos[i * 3 + 1];
  const cortex = Array.from({ length: cloud.count }, (_, i) => i).filter((i) => cloud.wander[i] === 0);
  const stem = cortex.filter((i) => cloud.lobe[i] === L.stem).sort((a, b) => y(a) - y(b));
  const under = cortex.filter((i) => (cloud.lobe[i] === L.cerebellum || cloud.lobe[i] === L.temporal) && y(i) < -0.25).sort((a, b) => y(a) - y(b));
  const pick = (from: number[], n: number) => Array.from({ length: Math.min(n, from.length) }, (_, k) => from[Math.floor((k * from.length) / Math.max(1, n))]);
  const anchors = [...pick(stem.slice(0, Math.ceil(stem.length * 0.6)), Math.ceil(count * 0.6)), ...pick(under, Math.floor(count * 0.4))];
  return anchors.map((anchor) => {
    const th = r() * 1.05, ph = r() * Math.PI * 2;
    const dir: [number, number, number] = [Math.sin(th) * Math.cos(ph), Math.cos(th), Math.sin(th) * Math.sin(ph)];
    return {
      anchor,
      end: [orb.x + dir[0] * orb.r, orb.y + dir[1] * orb.r, orb.z + dir[2] * orb.r],
      bend: [(r() - 0.5) * 0.5, 0.25 + r() * 0.3, (r() - 0.5) * 0.3],
      phase: r(), rate: 0.08 + r() * 0.12,
    };
  });
}

/** Cubic Bezier from the anchor (already in the links' space) down into the orb. */
export function linkPoint(a: [number, number, number], l: OrbLink, t: number): [number, number, number] {
  const e = l.end;
  const p1 = [a[0] + l.bend[0] * 0.4, a[1] - 0.3, a[2] + l.bend[2]];
  const p2 = [e[0] + l.bend[0], e[1] + l.bend[1], e[2] + l.bend[2] * 0.5];
  const u = 1 - t;
  return [0, 1, 2].map((k) => u * u * u * a[k] + 3 * u * u * t * p1[k] + 3 * u * t * t * p2[k] + t * t * t * e[k]) as [number, number, number];
}
