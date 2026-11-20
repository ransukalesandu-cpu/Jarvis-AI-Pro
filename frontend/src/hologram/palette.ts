import { Color } from 'three';
import type { AssistantState } from '../bridge/contract';

// JARVIS look: glass hologram head with a neural brain, orange eyes, cyan glass orb.
export const COLORS = {
  skin: new Color('#0d4a72'),       // glass body (barely there)
  rim: new Color('#5fe6ff'),        // glass silhouette glow
  edge: new Color('#6fdcff'),       // edge net
  node: new Color('#d8f7ff'),       // twinkling mesh nodes
  brain: new Color('#7fe9ff'),      // neural lines in the cranium
  eye: new Color('#ff9a1a'),
  eyeCore: new Color('#ffd27a'),
  orb: new Color('#27d9ff'),
  orbCore: new Color('#d9fbff'),
  heart: new Color('#ff3b4e'),
  heartSoft: new Color('#ff8a5c'),
  wire: new Color('#3fd0ff'),
  ring: new Color('#2fb8ff'),
  error: new Color('#ff5a4a'),
};

export function orbColor(state: AssistantState): Color {
  switch (state) {
    case 'error': return COLORS.error;
    case 'thinking': return new Color('#7aa8ff');
    case 'searching': return new Color('#58f0c8');
    case 'executing': return new Color('#ffc14d');
    default: return COLORS.orb;
  }
}
