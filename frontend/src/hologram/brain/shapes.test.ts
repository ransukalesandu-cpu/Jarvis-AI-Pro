import { describe, expect, it } from 'vitest';
import { parseHostEvent } from '../../bridge/contract';
import { assign, CENTER_Y, inHeart, SHAPES, shapePoints, textPoints, validText } from './shapes';

const GEN = SHAPES.filter((s) => s !== 'brain' && s !== 'text') as Exclude<(typeof SHAPES)[number], 'brain' | 'text'>[];

describe('brain shapes', () => {
    it('every shape gives exactly n finite points, deterministic, inside the stage', () => {
        for (const s of GEN) {
            const p = shapePoints(s, 1200);
            expect(p.length, s).toBe(3600);
            expect(Array.from(p)).toEqual(Array.from(shapePoints(s, 1200)));
            for (let i = 0; i < p.length; i += 3) {
                expect(Number.isFinite(p[i] + p[i + 1] + p[i + 2]), s).toBe(true);
                expect(Math.hypot(p[i], p[i + 1] - CENTER_Y, p[i + 2]), s).toBeLessThan(1.1);
            }
        }
    });
    it('the sphere is a sphere and the heart fills the heart curve', () => {
        const sp = shapePoints('sphere', 500);
        for (let i = 0; i < sp.length; i += 3) expect(Math.hypot(sp[i], sp[i + 1] - CENTER_Y, sp[i + 2])).toBeCloseTo(0.72, 5);
        const h = shapePoints('heart', 900);
        let inside = 0;
        for (let i = 0; i < h.length; i += 3) if (inHeart(h[i] / 0.62, (h[i + 1] - CENTER_Y) / 0.62 + 0.15)) inside++;
        expect(inside / 900).toBeGreaterThan(0.6); // the rest are on the outline
    });
    it('text points land only on lit pixels of the mask', () => {
        const w = 20,
            h = 10,
            mask = new Uint8Array(w * h);
        for (let y = 2; y < 8; y++) for (let x = 3; x < 6; x++) mask[y * w + x] = 255; // one block
        const p = textPoints(mask, w, h, 300, 2);
        const scale = 2 / w;
        for (let i = 0; i < p.length; i += 3) {
            const px = p[i] / scale + w / 2,
                py = h / 2 - (p[i + 1] - CENTER_Y) / scale;
            expect(px).toBeGreaterThanOrEqual(3);
            expect(px).toBeLessThanOrEqual(6);
            expect(py).toBeGreaterThanOrEqual(2);
            expect(py).toBeLessThanOrEqual(8);
        }
    });
    it('assign keeps every target point exactly once and maps top to top', () => {
        const from = shapePoints('cube', 400),
            to = shapePoints('torus', 400);
        const res = assign(from, to);
        const key = (a: Float32Array) => Array.from({ length: 400 }, (_, i) => `${a[i * 3]},${a[i * 3 + 1]},${a[i * 3 + 2]}`).sort();
        expect(key(res)).toEqual(key(to));
        let top = 0,
            topI = 0;
        for (let i = 0; i < 400; i++)
            if (from[i * 3 + 1] > top) {
                top = from[i * 3 + 1];
                topI = i;
            }
        expect(res[topI * 3 + 1]).toBeCloseTo(Math.max(...Array.from({ length: 400 }, (_, i) => to[i * 3 + 1])), 5);
    });
    it('text is short and plain, and the contract enforces the same rules', () => {
        expect(validText('JARVIS')).toBe(true);
        expect(validText('<b>')).toBe(false);
        expect(validText('A'.repeat(17))).toBe(false);
        const ev = (m: object) => parseHostEvent(JSON.stringify({ type: 'hologram.shape', ...m }));
        expect(ev({ shape: 'heart', text: '' })).toEqual({ type: 'hologram.shape', shape: 'heart', text: '' });
        expect(ev({ shape: 'text', text: 'JARVIS' })).not.toBeNull();
        expect(ev({ shape: 'text', text: '' })).toBeNull();
        expect(ev({ shape: 'heart', text: 'HI' })).toBeNull();
        expect(ev({ shape: 'dragon', text: '' })).toBeNull();
    });
    it('the shape list matches the Python side', async () => {
        const fs = await import('node:fs'),
            path = await import('node:path');
        const py = fs.readFileSync(path.resolve(process.cwd(), '..', 'jarvis', 'core', 'brain_shapes.py'), 'utf8'); // vitest runs in frontend/
        const m = py.match(/SHAPES = \(([^)]*)\)/)!;
        expect(
            m[1]
                .split(',')
                .map((s) => s.trim().replace(/"/g, ''))
                .filter(Boolean),
        ).toEqual([...SHAPES]);
        expect(py).toContain('TEXT_MAX = 16');
    });
});
