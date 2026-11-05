// JARVIS client theme: orb colors per state and effect parameters per quality
// tier. The renderer (orb.js) and governor (governor.js) read only from here.
export const THEME = {
  states: {
    disconnected: { core: "#4a5670", ring: "#2c3650", glow: 0.15, spin: 0.15 },
    idle:         { core: "#39c6ff", ring: "#1d6f9c", glow: 0.45, spin: 0.25 },
    listening:    { core: "#5fe0ff", ring: "#39c6ff", glow: 0.85, spin: 0.6 },
    thinking:     { core: "#ffb547", ring: "#8a7dff", glow: 0.7,  spin: 1.6 },
    speaking:     { core: "#7fe6ff", ring: "#39c6ff", glow: 1.0,  spin: 0.9 },
    error:        { core: "#ff5d6c", ring: "#7a1f2a", glow: 0.6,  spin: 0.2 },
  },
  // Tiers lower particles, glow and frame rate first; layout never changes.
  tiers: {
    full:    { particles: 90, rings: 5, glowLayers: 3, maxFps: 60, maxDpr: 2,   sparks: true },
    reduced: { particles: 36, rings: 4, glowLayers: 2, maxFps: 45, maxDpr: 1.5, sparks: true },
    minimal: { particles: 0,  rings: 2, glowLayers: 1, maxFps: 24, maxDpr: 1,   sparks: false },
  },
  tierOrder: ["full", "reduced", "minimal"],
  governor: {
    targetFps: 30,          // the floor a tier must hold
    sampleMs: 2000,         // window per decision
    downAfter: 1,           // windows below target before stepping down
    upAfter: 5,             // comfortable windows before trying a richer tier
    upHeadroom: 1.6,        // fps must exceed target * this to step up
  },
  orb: { radiusFrac: 0.34, levelGain: 1.6, levelSmoothing: 0.25 },
};
