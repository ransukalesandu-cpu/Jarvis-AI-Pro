/** Pure geometry for the energy layer: strand curves, arc polylines and particle seeds. */
import { CatmullRomCurve3, Vector3 } from 'three';
import { rng } from '../glass';

export const LAYOUT = { head: { x: 0, y: 0.55 }, neckY: -0.88, orb: { x: 0, y: -1.62, r: 0.28 } };
export const STRANDS = 28;
export const MAX_ARCS = 6;
export const ARC_STEPS = 24;

export function strandCurves(): CatmullRomCurve3[] {
    const r = rng(19);
    const top = LAYOUT.neckY,
        bottom = LAYOUT.orb.y + LAYOUT.orb.r * 0.75;
    return Array.from({ length: STRANDS }, (_, i) => {
        const k = (i - (STRANDS - 1) / 2) / ((STRANDS - 1) / 2);
        const z = (r() - 0.5) * 0.25;
        return new CatmullRomCurve3([
            new Vector3(k * 0.34, top, z),
            new Vector3(k * 0.3 + (r() - 0.5) * 0.06, top - 0.14, z * 0.8),
            new Vector3(k * 0.2 + (r() - 0.5) * 0.08, (top + bottom) / 2, z * 0.5),
            new Vector3(k * 0.1, bottom + 0.06, z * 0.2),
            new Vector3(k * 0.05, bottom, 0.05),
        ]);
    });
}

/** All strands as one line-segment list (one draw), with `along` 0..1 and a per-strand `seed`. */
export function strandSegments(points = 40): { position: Float32Array; along: Float32Array; seed: Float32Array } {
    const curves = strandCurves();
    const n = STRANDS * points * 2;
    const position = new Float32Array(n * 3),
        along = new Float32Array(n),
        seed = new Float32Array(n);
    let v = 0;
    curves.forEach((c, i) => {
        const pts = c.getPoints(points);
        for (let k = 0; k < points; k++)
            for (const j of [k, k + 1]) {
                position.set([pts[j].x, pts[j].y, pts[j].z], v * 3);
                along[v] = j / points;
                seed[v] = (i * 0.137) % 1;
                v++;
            }
    });
    return { position, along, seed };
}

/**
 * Arcs from the jaw line and neck sides down to the orb's shoulders, alternating left and right.
 * Returned as line segments with `along`, `arc` and a `side` direction (perpendicular, in the view plane).
 */
export function arcSegments(): { position: Float32Array; along: Float32Array; arc: Float32Array; side: Float32Array } {
    const { orb } = LAYOUT;
    const starts: [number, number][] = [
        [-0.36, -0.62],
        [0.36, -0.62],
        [-0.3, -0.8],
        [0.3, -0.8],
        [-0.42, -0.45],
        [0.42, -0.45],
    ];
    const n = MAX_ARCS * ARC_STEPS * 2;
    const position = new Float32Array(n * 3),
        along = new Float32Array(n),
        arc = new Float32Array(n),
        side = new Float32Array(n * 3);
    let v = 0;
    for (let a = 0; a < MAX_ARCS; a++) {
        const [sx, sy] = starts[a];
        const ex = orb.x + Math.sign(sx) * orb.r * 0.85,
            ey = orb.y + orb.r * 0.35;
        const dx = ex - sx,
            dy = ey - sy,
            len = Math.hypot(dx, dy);
        const px = -dy / len,
            py = dx / len;
        const bow = 0.18 * Math.sign(sx); // arcs bow outward
        const at = (u: number): [number, number] => [sx + dx * u + bow * Math.sin(Math.PI * u), sy + dy * u];
        for (let k = 0; k < ARC_STEPS; k++)
            for (const j of [k, k + 1]) {
                const u = j / ARC_STEPS,
                    [x, y] = at(u);
                position.set([x, y, 0.15], v * 3);
                along[v] = u;
                arc[v] = a;
                side.set([px, py, 0], v * 3);
                v++;
            }
    }
    return { position, along, arc, side };
}

/** Particle seeds for a helix from the orb up the strands to the neck (motion is in the shader). */
export function particleSeeds(count: number, seed = 11): { phase: Float32Array; radius: Float32Array; speed: Float32Array; spin: Float32Array } {
    const r = rng(seed);
    const phase = new Float32Array(count),
        radius = new Float32Array(count),
        speed = new Float32Array(count),
        spin = new Float32Array(count);
    for (let i = 0; i < count; i++) {
        phase[i] = r();
        radius[i] = 0.05 + r() * 0.45;
        speed[i] = 0.08 + r() * 0.12;
        spin[i] = (r() < 0.5 ? -1 : 1) * (0.5 + r() * 1.5);
    }
    return { phase, radius, speed, spin };
}
