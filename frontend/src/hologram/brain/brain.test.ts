import { describe, expect, it } from 'vitest';
import { ASSISTANT_STATES } from '../../bridge/contract';
import { brainCloud, L, LOBES, MAX_INNER_SYNAPSE, MAX_SYNAPSE, STEM_BOTTOM, synapses } from './brainShape';
import { brainMood } from './lobes';

const cloud = brainCloud(3000);
const P = (i: number) => [cloud.pos[i * 3], cloud.pos[i * 3 + 1], cloud.pos[i * 3 + 2]];

describe('procedural brain', () => {
    it('is deterministic and every lobe is present', () => {
        expect(Array.from(brainCloud(500).pos)).toEqual(Array.from(brainCloud(500).pos));
        for (const l of LOBES) expect(Array.from(cloud.lobe).filter((x) => x === L[l]).length, l).toBeGreaterThan(40);
    });
    it('has two balanced hemispheres with a fissure between them', () => {
        const cerebrum = Array.from({ length: cloud.count }, (_, i) => i).filter((i) => cloud.lobe[i] <= L.occipital);
        const left = cerebrum.filter((i) => P(i)[2] < 0).length,
            right = cerebrum.length - left;
        expect(Math.abs(left - right) / cerebrum.length).toBeLessThan(0.05);
        const inFissure = cerebrum.filter((i) => Math.abs(P(i)[2]) < 0.03 && P(i)[1] > 0.3).length;
        expect(inFissure / cerebrum.length).toBeLessThan(0.01);
    });
    it('front, back and stem sit where a brain has them', () => {
        const mean = (l: number, axis: number) => {
            const s = Array.from({ length: cloud.count }, (_, i) => i).filter((i) => cloud.lobe[i] === l);
            return s.reduce((a, i) => a + P(i)[axis], 0) / s.length;
        };
        expect(mean(L.frontal, 0)).toBeGreaterThan(mean(L.occipital, 0));
        expect(mean(L.cerebellum, 1)).toBeLessThan(mean(L.parietal, 1));
        expect(mean(L.cerebellum, 0)).toBeLessThan(0);
        const minY = Math.min(...Array.from({ length: cloud.count }, (_, i) => P(i)[1]));
        expect(minY).toBeGreaterThanOrEqual(STEM_BOTTOM - 0.01);
    });
    it('synapses are unique, local and plentiful', () => {
        const s = synapses(brainCloud(1500));
        const c = brainCloud(1500),
            seen = new Set<string>();
        expect(s.count).toBeGreaterThan(1500);
        for (let e = 0; e < s.count; e++) {
            const [a, b] = [s.a[e], s.b[e]];
            expect(a).not.toBe(b);
            const key = a < b ? `${a},${b}` : `${b},${a}`;
            expect(seen.has(key)).toBe(false);
            seen.add(key);
            const d = Math.hypot(c.pos[a * 3] - c.pos[b * 3], c.pos[a * 3 + 1] - c.pos[b * 3 + 1], c.pos[a * 3 + 2] - c.pos[b * 3 + 2]);
            const inner = c.wander[a] > 0 || c.wander[b] > 0;
            expect(d).toBeLessThanOrEqual((inner ? MAX_INNER_SYNAPSE : MAX_SYNAPSE) + 1e-6);
        }
    });
});

describe('brain moods', () => {
    const top = (s: Parameters<typeof brainMood>[0], lv = 0) => {
        const l = brainMood(s, lv).lobes;
        return l.indexOf(Math.max(...l));
    };
    it('every state is bounded', () => {
        for (const s of ASSISTANT_STATES) {
            const m = brainMood(s, 0.8);
            for (const v of [...m.lobes, m.firing, m.growth]) {
                expect(v, s).toBeGreaterThanOrEqual(0);
                expect(v, s).toBeLessThanOrEqual(1);
            }
        }
    });
    it('the right region leads in each state', () => {
        expect(top('thinking')).toBe(L.frontal);
        expect(top('listening', 0.6)).toBe(L.temporal);
        expect(top('executing')).toBe(L.parietal);
        expect(top('searching')).toBe(L.occipital);
    });
    it('voice modulates speaking; sleep is dark; warning and error recolour', () => {
        expect(brainMood('speaking', 1).firing).toBeGreaterThan(brainMood('speaking', 0).firing);
        expect(Math.max(...brainMood('sleeping').lobes)).toBeLessThan(0.15);
        expect(brainMood('warning').tint[2]).toBeLessThan(0.5);
        expect(brainMood('error').tint[1]).toBeLessThan(0.4);
    });
});

describe('living interior and links to the orb', () => {
    it('a share of neurons lives inside the brain and drifts; their synapses turn over faster', async () => {
        const { INTERIOR } = await import('./brainShape');
        const inside = Array.from(cloud.wander).filter((w) => w > 0).length / cloud.count;
        expect(inside).toBeGreaterThan(INTERIOR * 0.7);
        expect(inside).toBeLessThan(INTERIOR * 1.3);
        const s = synapses(cloud);
        let innerRate = 0,
            innerN = 0,
            outerRate = 0,
            outerN = 0;
        for (let e = 0; e < s.count; e++) {
            const inner = cloud.wander[s.a[e]] > 0 || cloud.wander[s.b[e]] > 0;
            if (inner) {
                innerRate += s.rate[e];
                innerN++;
            } else {
                outerRate += s.rate[e];
                outerN++;
            }
        }
        expect(innerN).toBeGreaterThan(200);
        expect(innerRate / innerN).toBeGreaterThan((outerRate / outerN) * 2);
    });
    it('links leave the stem and the underside of the brain and land on the top of the orb', async () => {
        const { linkPoint, orbLinks } = await import('./orbLinks');
        const orb = { x: 0, y: -2, z: 0.1, r: 0.28 };
        const links = orbLinks(cloud, 36, orb);
        expect(links.length).toBe(36);
        expect(links.filter((l) => cloud.lobe[l.anchor] === L.stem).length).toBeGreaterThanOrEqual(20);
        for (const l of links) {
            expect(cloud.wander[l.anchor]).toBe(0);
            expect(Math.hypot(l.end[0] - orb.x, l.end[1] - orb.y, l.end[2] - orb.z)).toBeCloseTo(orb.r, 5);
            expect(l.end[1]).toBeGreaterThan(orb.y); // the upper half of the orb
            const a: [number, number, number] = [cloud.pos[l.anchor * 3], cloud.pos[l.anchor * 3 + 1], cloud.pos[l.anchor * 3 + 2]];
            expect(linkPoint(a, l, 0)).toEqual(a);
            linkPoint(a, l, 1).forEach((v, k) => expect(v).toBeCloseTo(l.end[k], 6));
        }
    });
});
