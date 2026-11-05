// JARVIS profile: cyan face and energy network, red quantum heart, cyan/blue orb.
export default Object.freeze({
  id: 'jarvis',
  // linear-ish 0..1 RGB
  face: [0.0, 0.90, 1.0], faceDeep: [0.02, 0.30, 0.85], hair: [0.1, 0.65, 1.0],
  wire: [0.0, 0.85, 1.0], spark: [0.75, 0.97, 1.0],
  heart: [1.0, 0.16, 0.22], heartHot: [1.0, 0.45, 0.2], heartSoft: [1.0, 0.45, 0.6],
  orb: [0.05, 0.62, 1.0], orbCore: [0.55, 0.95, 1.0],
  ring: [0.1, 0.7, 1.0],
  // face shape morph (0 = base head) and animation personality
  shape: 0.0, hairLen: 1.0, hairSwirl: 1.0, pulseRate: 1.0, glow: 1.0,
});
