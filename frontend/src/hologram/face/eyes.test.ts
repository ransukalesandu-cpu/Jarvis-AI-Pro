import { describe, expect, it } from 'vitest';
import { ASSISTANT_STATES } from '../../bridge/contract';
import { ease, eyeTarget, withLid } from './eyeStates';
import { BLADES, bladeOutline, MASK_INNER, openingRadius } from './iris';

describe('mechanical iris geometry', () => {
    it('opening grows with the aperture: shut at 0, past the socket ring at 1', () => {
        const r = [0, 0.25, 0.5, 0.75, 1].map((a) => openingRadius(a));
        for (let i = 1; i < r.length; i++) expect(r[i]).toBeGreaterThan(r[i - 1]);
        expect(r[0]).toBeLessThan(0.02);
        expect(r[4]).toBeGreaterThan(MASK_INNER * 0.95);
    });
    it('the opening tracks the aperture closely (sin phi law)', () => {
        for (const a of [0.2, 0.4, 0.6]) expect(openingRadius(a)).toBeCloseTo(a * 0.95, 1);
    });
    it('blades are closed outlines with real width', () => {
        const o = bladeOutline();
        expect(o.length).toBeGreaterThan(20);
        expect(Math.min(...o.map((p) => p[1]))).toBeLessThan(-0.7);
        expect(BLADES).toBeGreaterThanOrEqual(7);
    });
});

describe('eye state mapping', () => {
    it('every state gives bounded values for both eyes', () => {
        for (const s of ASSISTANT_STATES)
            for (const side of ['L', 'R'] as const)
                for (const t of [0, 0.37, 1.9]) {
                    const e = eyeTarget(s, side, t, 0.7);
                    expect(e.aperture, s).toBeGreaterThanOrEqual(0);
                    expect(e.aperture, s).toBeLessThanOrEqual(1);
                    expect(e.glow, s).toBeGreaterThanOrEqual(0);
                    expect(e.glow, s).toBeLessThanOrEqual(1);
                    expect(Math.abs(e.scan), s).toBeLessThanOrEqual(2);
                    expect(
                        e.tint.every((c) => c >= 0 && c <= 1),
                        s,
                    ).toBe(true);
                }
    });
    it('listening opens wide, executing and error narrow, sleeping nearly shuts', () => {
        expect(eyeTarget('listening', 'L', 0).aperture).toBeGreaterThan(0.85);
        expect(eyeTarget('executing', 'L', 0).aperture).toBeLessThan(0.4);
        expect(eyeTarget('error', 'L', 0).aperture).toBeLessThan(0.3);
        expect(eyeTarget('sleeping', 'L', 0).aperture).toBeLessThan(0.2);
    });
    it('the eyes act independently while thinking and searching', () => {
        expect(eyeTarget('thinking', 'L', 1).scan).toBe(-eyeTarget('thinking', 'R', 1).scan);
        expect(eyeTarget('thinking', 'L', 0.5).aperture).not.toBeCloseTo(eyeTarget('thinking', 'R', 0.5).aperture, 2);
        expect(eyeTarget('searching', 'L', 0.3).glow).not.toBeCloseTo(eyeTarget('searching', 'R', 0.3).glow, 2);
        expect(eyeTarget('idle', 'L', 2)).toEqual(eyeTarget('idle', 'R', 2));
    });
    it('speaking opens with the voice level; warning and error recolour', () => {
        expect(eyeTarget('speaking', 'L', 0, 1).aperture).toBeGreaterThan(eyeTarget('speaking', 'L', 0, 0).aperture);
        expect(eyeTarget('speaking', 'L', 0, 1).glow).toBeGreaterThan(eyeTarget('speaking', 'L', 0, 0).glow);
        expect(eyeTarget('warning', 'L', 0).tint[2]).toBeLessThan(0.5);
        expect(eyeTarget('error', 'L', 0).tint[1]).toBeLessThan(0.4);
    });
    it('a blink shuts the iris, and easing converges independent of frame rate', () => {
        expect(withLid(0.8, 1)).toBeCloseTo(0.8);
        expect(withLid(0.8, 0.06)).toBe(0);
        let a = 0,
            b = 0;
        for (let i = 0; i < 60; i++) a = ease(a, 1, 6, 1 / 60);
        for (let i = 0; i < 30; i++) b = ease(b, 1, 6, 1 / 30);
        expect(a).toBeCloseTo(b, 6);
    });
});
