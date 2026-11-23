import { Color } from 'three';
import type { VisualState } from './visualState';

// JARVIS look: a dark circuit-board head in orange: glowing traces and vias over the face, orange
// rim light, burning orange eyes, orange strands into an orange glass orb. (UI chrome stays cyan.)
export const COLORS = {
  skin: new Color('#3a1404'),       // glass body (dark, barely there)
  rim: new Color('#ff7418'),        // glass silhouette glow
  edge: new Color('#ff8a2a'),       // faint edge net, plexus, dust
  node: new Color('#ffd7a3'),       // twinkling nodes, pulses
  circuit: new Color('#ff5a00'),    // circuit traces on the face
  via: new Color('#ffa24a'),        // trace ends
  contour: new Color('#ff7a1a'),    // lips, eyes, brows, face outline
  blue: new Color('#3cc4ff'),       // nose ridge and forehead chips
  eye: new Color('#ff6a00'),
  eyeCore: new Color('#ffd08a'),
  orb: new Color('#ff8a24'),
  orbCore: new Color('#fff0d6'),
  orbBody: new Color('#2a1004'),
  heart: new Color('#ff3b4e'),
  heartSoft: new Color('#ff8a5c'),
  wire: new Color('#ff8a2a'),
  ring: new Color('#ff7a1a'),
  warning: new Color('#ffc21a'),   // something needs attention, still working
  error: new Color('#ff3030'),
  offline: new Color('#5d6f80'),   // backend link down: cold grey, no energy
  backdrop: new Color('#1e8fff'),   // blue circuits behind the head
  spark: new Color('#ff7a1a'),      // orange sparks among them
};

/** How often the glass glitches (chance per 1/8 s): only when something is wrong, never at rest. */
export function glitchChance(state: VisualState): number {
  return state === 'error' ? 0.3 : state === 'warning' ? 0.12 : 0;
}

export function orbColor(state: VisualState): Color {
  switch (state) {
    case 'offline': return COLORS.offline;
    case 'error': return COLORS.error;
    case 'warning': return COLORS.warning;
    case 'thinking': return new Color('#ffb15c');
    case 'searching': return new Color('#ffd36b');
    case 'executing': return new Color('#ff9d3d');
    default: return COLORS.orb;
  }
}
