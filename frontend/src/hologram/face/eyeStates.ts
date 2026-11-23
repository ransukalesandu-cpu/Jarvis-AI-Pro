/**
 * What each mechanical eye does in each assistant state. Pure and per side, so the two eyes can act
 * independently (counter-rotating scan rings while thinking, alternating sweeps while searching).
 * Audio only modulates (speaking): there is no phoneme or viseme logic here.
 */
import type { VisualState } from '../visualState';

export type Side = 'L' | 'R';
export interface EyeTarget {
    aperture: number; // iris opening 0 (shut) .. 1 (wide)
    glow: number; // emission 0..1
    scan: number; // scan-ring speed, turns/s; sign = direction
    tint: [number, number, number];
}

const WHITE: [number, number, number] = [1, 1, 1];
const AMBER: [number, number, number] = [1, 0.82, 0.35];
const RED: [number, number, number] = [1, 0.25, 0.2];
const DIM: [number, number, number] = [0.5, 0.5, 0.5];
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

export function eyeTarget(state: VisualState, side: Side, t: number, level = 0): EyeTarget {
    const sgn = side === 'L' ? 1 : -1;
    const ph = side === 'L' ? 0 : Math.PI;
    let r: EyeTarget;
    switch (state) {
        case 'offline':
            r = { aperture: 0.08, glow: 0.04, scan: 0, tint: DIM };
            break;
        case 'sleeping':
            r = { aperture: 0.12, glow: 0.08, scan: 0.03, tint: DIM };
            break;
        case 'listening':
            r = { aperture: 0.92, glow: 0.55, scan: 0.25, tint: WHITE };
            break;
        case 'thinking':
            r = { aperture: 0.45 + 0.15 * Math.sin(t * 3 + ph), glow: 0.6, scan: 0.6 * sgn, tint: WHITE };
            break;
        case 'searching':
            r = { aperture: 0.5, glow: 0.35 + 0.45 * Math.max(0, Math.sin(t * 4 + ph)), scan: 1.0 * sgn, tint: WHITE };
            break;
        case 'executing':
            r = { aperture: 0.3, glow: 0.7, scan: 1.2, tint: WHITE };
            break;
        case 'speaking':
            r = { aperture: 0.25 + 0.35 * clamp01(level), glow: 0.3 + 0.7 * clamp01(level * 1.2), scan: 0.3, tint: WHITE };
            break;
        case 'warning':
            r = { aperture: 0.6, glow: Math.sin(t * 10) > 0 ? 0.8 : 0.45, scan: 0.4, tint: AMBER };
            break;
        case 'error':
            r = { aperture: 0.2, glow: 0.8, scan: 0, tint: RED };
            break;
        default:
            r = { aperture: 0.55 + 0.04 * Math.sin(t * 0.7), glow: 0.3, scan: 0.12, tint: WHITE };
    }
    return { ...r, aperture: clamp01(r.aperture), glow: clamp01(r.glow) };
}

/** A blink closes the shutter: the lid factor (1 open .. ~0.06 shut) scales the aperture. */
export const withLid = (aperture: number, lid: number) => clamp01(aperture * clamp01((lid - 0.06) / 0.94));

/** Eases a value toward its target at `rate` per second (frame-rate independent). */
export const ease = (from: number, to: number, rate: number, dt: number) => from + (to - from) * (1 - Math.exp(-rate * dt));
