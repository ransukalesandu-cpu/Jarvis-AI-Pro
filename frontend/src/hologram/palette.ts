import type { Color } from 'three';
import { stageColor } from './stageColor';
import type { VisualState } from './visualState';

// JARVIS look: a dark circuit-board head in orange: glowing traces and vias over the face, orange
// rim light, burning orange eyes, orange strands into an orange glass orb. (UI chrome stays cyan.)
export const COLORS = {
    skin: stageColor('stage-skin'), // glass body (dark, barely there)
    rim: stageColor('stage-rim'), // glass silhouette glow
    edge: stageColor('stage-edge'), // faint edge net, plexus, dust
    node: stageColor('stage-node'), // twinkling nodes, pulses
    circuit: stageColor('stage-circuit'), // circuit traces on the face
    via: stageColor('stage-via'), // trace ends
    contour: stageColor('stage-contour'), // lips, eyes, brows, face outline
    blue: stageColor('stage-blue'), // nose ridge and forehead chips
    eye: stageColor('stage-eye'),
    eyeCore: stageColor('stage-eye-core'),
    orb: stageColor('stage-orb'),
    orbCore: stageColor('stage-orb-core'),
    orbBody: stageColor('stage-orb-body'),
    heart: stageColor('stage-heart'),
    heartSoft: stageColor('stage-heart-soft'),
    wire: stageColor('stage-wire'),
    ring: stageColor('stage-ring'),
    warning: stageColor('stage-warning'), // something needs attention, still working
    error: stageColor('stage-error'),
    offline: stageColor('stage-offline'), // backend link down: cold grey, no energy
    backdrop: stageColor('stage-backdrop'), // blue circuits behind the head
    spark: stageColor('stage-spark'), // orange sparks among them
};

/** How often the glass glitches (chance per 1/8 s): only when something is wrong, never at rest. */
export function glitchChance(state: VisualState): number {
    return state === 'error' ? 0.3 : state === 'warning' ? 0.12 : 0;
}

export function orbColor(state: VisualState): Color {
    switch (state) {
        case 'offline':
            return COLORS.offline;
        case 'error':
            return COLORS.error;
        case 'warning':
            return COLORS.warning;
        case 'thinking':
            return stageColor('stage-thinking');
        case 'searching':
            return stageColor('stage-searching');
        case 'executing':
            return stageColor('stage-executing');
        default:
            return COLORS.orb;
    }
}
