import { describe, expect, it } from 'vitest';
import mesh from './headMesh.json';
import { chipData } from './FaceData';
import { adjacency, buildFaceCircuit, meshPath, mirrorMap, neckRuns, neckZ } from './faceCircuit';

const x = (i: number) => mesh.verts[i * 3];

describe('circuit face', () => {
    it('mirror map pairs the two sides of the face', () => {
        const m = mirrorMap();
        expect(m[33]).toBe(263); // outer eye corners
        expect(m[61]).toBe(291); // mouth corners
        expect(m[1]).toBe(1); // nose tip is on the midline
    });

    it('mesh paths walk along edges from one landmark to another', () => {
        const adj = adjacency();
        const p = meshPath(adj, 109, 107);
        expect(p[0]).toBe(109);
        expect(p[p.length - 1]).toBe(107);
        for (let i = 0; i < p.length - 1; i++) expect(adj[p[i]]).toContain(p[i + 1]);
    });

    it('designed traces are symmetric and every index is a real vertex', () => {
        const c = buildFaceCircuit();
        const n = mesh.verts.length / 3;
        for (const arr of [c.main, c.contour, c.fill, c.nose, c.vias])
            for (const v of arr) {
                expect(v).toBeGreaterThanOrEqual(0);
                expect(v).toBeLessThan(n);
            }
        const left = c.main.filter((v) => x(v) < -0.02).length,
            right = c.main.filter((v) => x(v) > 0.02).length;
        expect(Math.abs(left - right)).toBeLessThanOrEqual(Math.max(4, left * 0.1));
        expect(c.main.length % 2).toBe(0);
        expect(c.contour.length).toBeGreaterThan(100);
    });

    it('neck runs sit on the front of the neck', () => {
        const { segs, rings } = neckRuns();
        expect(segs.length % 6).toBe(0);
        for (let i = 0; i < segs.length; i += 3) {
            expect(segs[i + 1]).toBeLessThanOrEqual(-1.0);
            expect(segs[i + 2]).toBeCloseTo(neckZ(segs[i]), 5);
        }
        expect(rings.length).toBeGreaterThan(2);
    });
});

describe('forehead chips', () => {
    it('show live CPU and RAM, and "--" without a sample', () => {
        const [cpu, ram] = chipData({ cpu: 42.4, ram: 63.6 }, 'listening');
        expect(cpu).toMatchObject({ label: 'CPU', value: '42%', frac: 0.424, foot: 'JARVIS · LISTENING' });
        expect(ram).toMatchObject({ label: 'RAM', value: '64%' });
        const [none] = chipData(null, 'idle');
        expect(none.value).toBe('--');
        expect(none.frac).toBeNull();
        expect(chipData({ cpu: 140, ram: -3 }, 'idle')[0].frac).toBe(1);
    });
});

describe('reference head shape', () => {
    it('keeps the eyes, raises the dome, narrows and lengthens the neck', async () => {
        const { reshape, CROWN, NECK_BOTTOM } = await import('./shape');
        expect(reshape(0.28, 0.08, 0.32)).toEqual([0.28, 0.08, 0.32]); // eye line unchanged
        expect(reshape(0, 1, 0)[1]).toBeGreaterThan(1.1); // taller dome
        expect(reshape(0.5, -1.2, 0.1)[0]).toBeCloseTo(0.4); // narrower neck
        expect(reshape(0.5, -1.2, 0.1)[1]).toBeLessThan(-1.3); // longer neck
        expect(CROWN).toBeGreaterThan(1.1);
        expect(NECK_BOTTOM).toBeLessThan(-1.45);
        const [l] = reshape(-0.4, -0.6, 0.3),
            [r] = reshape(0.4, -0.6, 0.3);
        expect(l).toBeCloseTo(-r); // still symmetric
    });
});
