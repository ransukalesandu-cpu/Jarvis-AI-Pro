import { describe, expect, it } from 'vitest';
import mesh from '../headMesh.json';
import { mirrorMap } from '../faceCircuit';
import { buildMechanicalFace, PANEL } from './panels';
import { JAW_MIN } from './regions';

const face = buildMechanicalFace();

describe('mechanical face panels', () => {
  it('covers the head (not the neck) with a few dozen named panels', () => {
    expect(face.panels.length).toBeGreaterThanOrEqual(20);
    const covered = face.partition.triRegion.filter((r) => r >= 0).length;
    expect(covered / face.partition.triRegion.length).toBeGreaterThan(0.85);
    for (const n of ['forehead', 'noseTip', 'chin', 'jawL', 'jawR', 'cheekboneL', 'cheekboneR', 'crown']) expect(face.panels.some((p) => p.name === n), n).toBe(true);
  });

  it('every panel is a closed, consistently wound shell', () => {
    for (const p of face.panels) {
      const count = new Map<string, number>();
      for (let i = 0; i < p.index.length; i += 3) for (let k = 0; k < 3; k++) {
        const e = `${p.index[i + k]},${p.index[i + (k + 1) % 3]}`;
        count.set(e, (count.get(e) ?? 0) + 1);
      }
      for (const [e, c] of count) { const [a, b] = e.split(','); expect(count.get(`${b},${a}`), `${p.name} edge ${e}`).toBe(c); }
      expect(p.positions.every(Number.isFinite), p.name).toBe(true);
    }
  });

  it('plates rise above the skull and leave a groove at their edges', () => {
    const forehead = face.panels.find((p) => p.name === 'forehead')!;
    const n = forehead.positions.length / 6;
    let maxLift = 0;
    for (let i = 0; i < n; i++) {
      const t = forehead.positions.subarray(i * 3, i * 3 + 3), b = forehead.positions.subarray((n + i) * 3, (n + i) * 3 + 3);
      maxLift = Math.max(maxLift, Math.hypot(t[0] - b[0], t[1] - b[1], t[2] - b[2]));
    }
    expect(maxLift).toBeGreaterThan(PANEL.height * 0.9);
    expect(face.engravings.length).toBeGreaterThan(100);
  });

  it('is symmetric: every panel triangle has its mirror in the mirrored panel', () => {
    const mir = mirrorMap();
    const { regions, triRegion } = face.partition;
    const name = (r: number) => (r < 0 ? '-' : regions[r].name);
    const flip = (s: string) => (s.endsWith('L') ? s.slice(0, -1) + 'R' : s.endsWith('R') ? s.slice(0, -1) + 'L' : s);
    const f = mesh.faces;
    const byVerts = new Map<string, number>();
    for (let t = 0; t < triRegion.length; t++) byVerts.set([f[t * 3], f[t * 3 + 1], f[t * 3 + 2]].sort((a, b) => a - b).join(','), t);
    let checked = 0, same = 0;
    for (let t = 0; t < triRegion.length; t++) {
      const m = byVerts.get([mir[f[t * 3]], mir[f[t * 3 + 1]], mir[f[t * 3 + 2]]].sort((a, b) => a - b).join(','));
      if (m === undefined) continue;
      checked++;
      if (name(triRegion[m]) === flip(name(triRegion[t]))) same++;
    }
    expect(checked).toBeGreaterThan(800);   // the face proper (the generated skull is not vertex-symmetric)
    expect(same / checked).toBeGreaterThan(0.97);
  });

  it('the jaw is a separate part: only jaw-weighted vertices, hinged at the pivot', () => {
    const { regions, vertexRegion } = face.partition;
    vertexRegion.forEach((r, v) => { if (r >= 0) expect(regions[r].jaw, `vertex ${v}`).toBe(mesh.jaw[v] >= JAW_MIN); });
    const jawPanels = face.panels.filter((p) => p.jaw).map((p) => p.name).sort();
    expect(jawPanels).toEqual(['chin', 'jawL', 'jawR']);
  });
});

describe('neck rings and borders', () => {
  it('rings stack down the neck with real, shrinking-or-steady radii', async () => {
    const { neckRings } = await import('./neck');
    const { NECK_BOTTOM } = await import('../shape');
    const rings = neckRings();
    expect(rings.length).toBe(7);
    for (let i = 1; i < rings.length; i++) expect(rings[i].y).toBeLessThan(rings[i - 1].y);
    for (const r of rings) { expect(r.rx).toBeGreaterThan(0.05); expect(r.rz).toBeGreaterThan(0.05); expect(r.height).toBeGreaterThan(0); expect(r.y).toBeGreaterThan(NECK_BOTTOM - 0.01); }
  });
  it('border relaxing moves only border vertices, and only a little', async () => {
    const { SHAPED } = await import('../shape');
    let moved = 0, maxMove = 0;
    for (let i = 0; i < SHAPED.length; i += 3) {
      const d = Math.hypot(face.positions[i] - SHAPED[i], face.positions[i + 1] - SHAPED[i + 1], face.positions[i + 2] - SHAPED[i + 2]);
      if (d > 1e-7) moved++;
      maxMove = Math.max(maxMove, d);
    }
    expect(moved).toBeGreaterThan(50);
    expect(moved).toBeLessThan(SHAPED.length / 3 / 2);
    expect(maxMove).toBeLessThanOrEqual(0.0901);
  });
});
