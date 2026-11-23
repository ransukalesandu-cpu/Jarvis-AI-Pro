/** Geometry of the Task Flow canvas: the brain on the left, steps fanned out in an arc, curved wires between. Pure. */

export const BRAIN_W = 248;
export const BRAIN_H = 292;
export const STEP_W = 214;
export const STEP_H = 86;
export const ROW = 100;
export const PAD = 22;

export interface Pos {
    x: number;
    y: number;
}
export interface View {
    x: number;
    y: number;
    s: number;
}

/** Wire colours, in step order (orange, cyan, teal, blue, pink, yellow, violet, green). */
export const WIRE = ['#ff9466', '#45e3ff', '#38f0c0', '#4d8dff', '#ff5fa8', '#ffd25e', '#a98bff', '#7cf27a'];

export function autoLayout(n: number): { brain: Pos; steps: Pos[] } {
    const cy = BRAIN_H / 2;
    const steps: Pos[] = [];
    for (let i = 0; i < n; i++) {
        const k = i - (n - 1) / 2;
        const a = n > 1 ? (k / ((n - 1) / 2)) * 1.05 : 0; // -1.05 .. 1.05 rad: the middle reaches furthest
        steps.push({ x: Math.round(330 + 150 * Math.cos(a) + (i % 2 ? 40 : 0)), y: Math.round(cy + k * ROW - STEP_H / 2) });
    }
    return { brain: { x: 0, y: 0 }, steps };
}

/** A smooth S-curve from a port on the brain's right edge to the step's left port. */
export function wire(brain: Pos, step: Pos, i: number, n: number) {
    const x1 = brain.x + BRAIN_W;
    const y1 = brain.y + BRAIN_H * 0.42 + (n > 1 ? (i * BRAIN_H * 0.36) / (n - 1) : BRAIN_H * 0.18);
    const x2 = step.x;
    const y2 = step.y + 29;
    const dx = Math.max(60, (x2 - x1) * 0.55);
    return { d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`, x1, y1, x2, y2 };
}

export function bounds(brain: Pos, steps: Pos[]) {
    let x0 = brain.x,
        y0 = brain.y,
        x1 = brain.x + BRAIN_W,
        y1 = brain.y + BRAIN_H;
    for (const p of steps) {
        x0 = Math.min(x0, p.x);
        y0 = Math.min(y0, p.y);
        x1 = Math.max(x1, p.x + STEP_W);
        y1 = Math.max(y1, p.y + STEP_H);
    }
    return { x0, y0, x1, y1 };
}

/**
 * Where the camera goes. `whole`: everything fits. Otherwise (the small window) keep a readable zoom
 * and follow `focusY` (the running step), clamped so the camera never drifts past the content.
 */
export function fitView(b: ReturnType<typeof bounds>, w: number, h: number, whole: boolean, focusY: number | null): View {
    const bw = b.x1 - b.x0,
        bh = b.y1 - b.y0;
    if (w <= 0 || h <= 0) return { x: 0, y: 0, s: 1 };
    if (whole) {
        const s = Math.max(0.2, Math.min(1.1, (w - PAD * 2) / bw, (h - PAD * 2) / bh));
        return { s, x: (w - bw * s) / 2 - b.x0 * s, y: (h - bh * s) / 2 - b.y0 * s };
    }
    const s = Math.max(0.3, Math.min(0.82, (w - PAD * 2) / bw));
    let fy = focusY ?? (b.y0 + b.y1) / 2;
    const half = h / 2 / s;
    if (bh * s <= h - PAD * 2) fy = (b.y0 + b.y1) / 2;
    else fy = Math.max(b.y0 - PAD / s + half, Math.min(b.y1 + PAD / s - half, fy));
    return { s, x: (w - bw * s) / 2 - b.x0 * s, y: h / 2 - fy * s };
}
