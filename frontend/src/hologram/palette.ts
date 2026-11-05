import { Color } from 'three';
import type { AssistantState } from '../bridge/contract';

// Standard JARVIS look: saturated blue shaded head, orange eyes, cyan orb, warm heart.
export const COLORS = {
  skin: new Color('#4da3ff'),
  skinEmissive: new Color('#0b3a8a'),
  edge: new Color('#8fd0ff'),
  eye: new Color('#ff9a1a'),
  orb: new Color('#27d9ff'),
  orbCore: new Color('#c9f6ff'),
  heart: new Color('#ff3b4e'),
  heartSoft: new Color('#ff8a5c'),
  wire: new Color('#3fb6ff'),
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
