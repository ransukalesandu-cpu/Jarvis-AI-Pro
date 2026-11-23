import { describe, expect, it } from 'vitest';
import { QUALITY } from '../engine/quality';
import { ARC_STEPS, arcSegments, LAYOUT, MAX_ARCS, particleSeeds, STRANDS, strandSegments } from './paths';

describe('energy layer geometry', () => {
  it('strands are one segment list running neck -> orb, along 0..1', () => {
    const s = strandSegments(40);
    expect(s.position.length / 3).toBe(STRANDS * 40 * 2);
    expect(Math.min(...s.along)).toBe(0);
    expect(Math.max(...s.along)).toBe(1);
    for (let v = 0; v < s.along.length; v++) if (s.along[v] === 0) expect(s.position[v * 3 + 1]).toBeCloseTo(LAYOUT.neckY, 5);
  });
  it('arcs start on the face side and end on the orb, mirrored left/right', () => {
    const a = arcSegments();
    expect(a.arc.length).toBe(MAX_ARCS * ARC_STEPS * 2);
    for (let v = 0; v < a.along.length; v++) {
      if (a.along[v] !== 1) continue;
      const x = a.position[v * 3], y = a.position[v * 3 + 1];
      expect(Math.hypot(x - LAYOUT.orb.x, y - LAYOUT.orb.y)).toBeLessThan(LAYOUT.orb.r * 1.05);
    }
    const startX = (arc: number) => a.position[a.arc.indexOf(arc) * 3];
    for (let k = 0; k < MAX_ARCS; k += 2) expect(startX(k)).toBeCloseTo(-startX(k + 1), 5);
    for (let v = 0; v < a.along.length; v++) expect(Math.hypot(a.side[v * 3], a.side[v * 3 + 1])).toBeCloseTo(1, 5);
  });
  it('particle seeds are deterministic and bounded', () => {
    const p = particleSeeds(500), q = particleSeeds(500);
    expect(Array.from(p.phase)).toEqual(Array.from(q.phase));
    expect(Math.max(...p.radius)).toBeLessThanOrEqual(0.5);
    expect(p.spin.every((s) => Math.abs(s) >= 0.5 && Math.abs(s) <= 2)).toBe(true);
  });
  it('quality profiles scale the energy layer down from Ultra to Eco', () => {
    expect(QUALITY.full.particles).toBeGreaterThan(QUALITY.balanced.particles);
    expect(QUALITY.balanced.particles).toBeGreaterThan(QUALITY.lite.particles);
    expect(QUALITY.full.arcs).toBeGreaterThanOrEqual(QUALITY.balanced.arcs);
    expect(QUALITY.lite.arcs).toBeLessThanOrEqual(MAX_ARCS);
    expect(QUALITY.full.arcs).toBeLessThanOrEqual(MAX_ARCS);
  });
});
