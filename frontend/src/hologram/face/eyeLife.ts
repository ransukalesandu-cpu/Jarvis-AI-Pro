/**
 * Shared eye behaviour for every face style: blinks, saccades, pupil by state. Pure apart from the
 * objects it writes to, so both the circuit and the mechanical head behave identically.
 */
import type { Mesh, ShaderMaterial } from 'three';
import type { VisualState } from '../visualState';

export interface EyeLife {
    blink: number;
    nextBlink: number;
    gx: number;
    gy: number;
    tx: number;
    ty: number;
    nextLook: number;
    dilate: number;
}
export const newEyeLife = (): EyeLife => ({ blink: 0, nextBlink: 2.5, gx: 0, gy: 0, tx: 0, ty: 0, nextLook: 1.5, dilate: 0.3 });

export interface EyeInputs {
    state: VisualState;
    outputLevel: number;
    reducedMotion: boolean;
    t: number;
    dt: number;
    random?: () => number;
}

/** How open the lids are right now (1 open, ~0.08 shut), from the blink phase. */
export function lidOpen(st: EyeLife): number {
    return Math.max(0.06, 1 - Math.sin((1 - st.blink) * Math.PI) * (st.blink > 0 ? 0.92 : 0));
}

export function stepEyes(st: EyeLife, eyes: (Mesh | null)[], mats: ShaderMaterial[], u: EyeInputs): void {
    const { t, dt } = u,
        rnd = u.random ?? Math.random;
    const speaking = u.state === 'speaking';
    const working = speaking || u.state === 'thinking' || u.state === 'executing' || u.state === 'searching';
    if (st.blink <= 0 && t > st.nextBlink) {
        st.blink = 1;
        st.nextBlink = t + 2.5 + rnd() * 3.5;
    }
    if (st.blink > 0) st.blink = Math.max(0, st.blink - dt / 0.16);
    const lid = lidOpen(st);
    const reduced = u.reducedMotion ? 0.3 : 1;
    for (const e of eyes) if (e) e.scale.set(1, lid, 1);
    // Gaze: small saccades to a new point every 1.5-4 s (centred while listening or speaking).
    const attentive = u.state === 'listening' || speaking;
    if (t > st.nextLook) {
        st.tx = attentive ? (rnd() - 0.5) * 0.15 : (rnd() - 0.5) * 0.9;
        st.ty = attentive ? 0 : (rnd() - 0.5) * 0.5;
        st.nextLook = t + 1.5 + rnd() * 2.5;
    }
    const k = Math.min(1, dt * 14 * reduced + (reduced < 1 ? dt * 2 : 0));
    st.gx += (st.tx - st.gx) * k;
    st.gy += (st.ty - st.gy) * k;
    // Pupil: wide while listening, narrow while speaking, breathing a little while thinking.
    const dil = u.state === 'listening' ? 0.9 : speaking ? 0.15 : working ? 0.45 + 0.2 * Math.sin(t * 3) : 0.35;
    st.dilate += (dil - st.dilate) * Math.min(1, dt * 3);
    for (const m of mats) {
        m.uniforms.time.value = t * reduced;
        m.uniforms.gaze.value.set(st.gx, st.gy);
        m.uniforms.dilate.value = st.dilate;
        m.uniforms.glow.value = speaking ? Math.min(1, u.outputLevel * 1.5) : working ? 0.6 : 0.3;
    }
}
