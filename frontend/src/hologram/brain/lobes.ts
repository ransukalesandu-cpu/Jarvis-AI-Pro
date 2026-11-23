/**
 * Which parts of the brain light up in each assistant state (index order = LOBES). Pure: the scene
 * eases toward these. Audio only modulates (speaking / listening level); nothing here is lip-sync.
 */
import type { VisualState } from '../visualState';

export interface BrainMood {
    lobes: [number, number, number, number, number, number]; // frontal, parietal, temporal, occipital, cerebellum, stem
    firing: number; // how often nodes fire, 0..1
    growth: number; // share of synapses alive at a time, 0..1
    flow: number; // signal speed along synapses
    tint: [number, number, number];
}

const ORANGE: [number, number, number] = [1, 1, 1];
const AMBER: [number, number, number] = [1, 0.85, 0.4];
const RED: [number, number, number] = [1, 0.3, 0.25];
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

export function brainMood(state: VisualState, level = 0): BrainMood {
    const lv = clamp01(level);
    switch (state) {
        case 'listening':
            return { lobes: [0.3, 0.3, 0.6 + 0.4 * lv, 0.2, 0.2, 0.4], firing: 0.4 + 0.4 * lv, growth: 0.55, flow: 0.6, tint: ORANGE };
        case 'thinking':
            return { lobes: [1, 0.6, 0.3, 0.3, 0.3, 0.3], firing: 0.85, growth: 0.75, flow: 1.4, tint: ORANGE };
        case 'searching':
            return { lobes: [0.6, 0.5, 0.4, 0.9, 0.3, 0.3], firing: 0.75, growth: 0.7, flow: 1.6, tint: ORANGE };
        case 'executing':
            return { lobes: [0.6, 1, 0.3, 0.3, 0.8, 0.6], firing: 0.8, growth: 0.7, flow: 1.8, tint: ORANGE };
        case 'speaking':
            return {
                lobes: [0.5 + 0.5 * lv, 0.3, 0.5 + 0.4 * lv, 0.2, 0.3, 0.5 + 0.5 * lv],
                firing: 0.4 + 0.6 * lv,
                growth: 0.6,
                flow: 0.8 + lv,
                tint: ORANGE,
            };
        case 'warning':
            return { lobes: [0.6, 0.6, 0.6, 0.6, 0.6, 0.6], firing: 0.6, growth: 0.5, flow: 1, tint: AMBER };
        case 'error':
            return { lobes: [0.9, 0.9, 0.9, 0.9, 0.9, 0.9], firing: 0.9, growth: 0.35, flow: 2, tint: RED };
        case 'offline':
            return { lobes: [0.08, 0.08, 0.08, 0.08, 0.08, 0.1], firing: 0.03, growth: 0.22, flow: 0.08, tint: [0.45, 0.5, 0.55] };
        case 'sleeping':
            return { lobes: [0.05, 0.05, 0.05, 0.05, 0.05, 0.1], firing: 0.05, growth: 0.2, flow: 0.15, tint: [0.6, 0.6, 0.6] };
        default:
            return { lobes: [0.25, 0.25, 0.25, 0.25, 0.25, 0.3], firing: 0.25, growth: 0.45, flow: 0.4, tint: ORANGE };
    }
}
