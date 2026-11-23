import type { PerfTier } from '../../bridge/contract';

/** What the hologram draws at each host performance tier (full / balanced / lite = Ultra / Balanced / Eco). */
export interface Quality {
  dpr: number | [number, number];   // device-pixel-ratio range for the canvas
  fpsCap: number | null;            // null = the display's rate
  backdropHalo: boolean;            // glow pass on the background circuit traces
  dust: boolean;                    // drifting background particles
  particles: number;                // neural energy particles (one GPU Points draw)
  arcs: number;                     // lightning arcs face -> orb (one draw)
  brainNodes: number;               // neural brain nodes (synapses scale with them)
}

export const QUALITY: Record<PerfTier, Quality> = {
  full: { dpr: [1, 2], fpsCap: null, backdropHalo: true, dust: true, particles: 3000, arcs: 6, brainNodes: 4200 },
  balanced: { dpr: [1, 1.5], fpsCap: null, backdropHalo: true, dust: true, particles: 1000, arcs: 4, brainNodes: 3000 },
  lite: { dpr: 1, fpsCap: 30, backdropHalo: false, dust: false, particles: 200, arcs: 2, brainNodes: 1500 },
};

/** Before the host reports a tier, draw at Balanced. */
export function qualityFor(tier: PerfTier | null): Quality {
  return QUALITY[tier ?? 'balanced'];
}
