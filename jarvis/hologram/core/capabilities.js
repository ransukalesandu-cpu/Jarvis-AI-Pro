// Capability detection and the initial quality tier. Measures what the browser
// reports; does not assume a powerful GPU.

export const QUALITY = Object.freeze({
  high:     { name: 'high',     pixelRatio: 2.0, grid: [96, 72], hair: 3600, nodes: 1.0, orbPts: 2400, heartPts: 1500, wire: 90, rings: 5, fpsTarget: 60 },
  balanced: { name: 'balanced', pixelRatio: 1.5, grid: [72, 54], hair: 2400, nodes: 0.7, orbPts: 1500, heartPts: 900,  wire: 60, rings: 4, fpsTarget: 45 },
  low:      { name: 'low',      pixelRatio: 1.0, grid: [48, 36], hair: 1100,  nodes: 0.4, orbPts: 700,  heartPts: 420,  wire: 36, rings: 3, fpsTarget: 30 },
});
export const TIER_ORDER = ['high', 'balanced', 'low'];

export function isSoftwareRenderer(name = '') {
  return /swiftshader|llvmpipe|software|softpipe|microsoft basic render/i.test(name);
}

export function pickInitialTier({ webgl2, rendererName = '', maxTextureSize = 0, deviceMemory = 4, cores = 4 } = {}) {
  if (!webgl2) return 'low';
  if (isSoftwareRenderer(rendererName)) return 'low';
  if (maxTextureSize && maxTextureSize < 8192) return 'low';
  if (deviceMemory < 4 || cores <= 2) return 'balanced';
  if (/intel/i.test(rendererName) && !/arc|iris xe/i.test(rendererName)) return 'balanced';
  return maxTextureSize >= 16384 ? 'high' : 'balanced';
}

export function stepDown(tier) { const i = TIER_ORDER.indexOf(tier); return TIER_ORDER[Math.min(TIER_ORDER.length - 1, i + 1)]; }
export function stepUp(tier) { const i = TIER_ORDER.indexOf(tier); return TIER_ORDER[Math.max(0, i - 1)]; }

/** Rolling frame-time monitor: suggests a tier change from measured frame times. */
export class FrameMonitor {
  constructor(window = 90) { this.n = window; this.samples = []; this.sinceChange = 0; }
  push(ms) { this.samples.push(ms); if (this.samples.length > this.n) this.samples.shift(); this.sinceChange++; }
  average() { return this.samples.length ? this.samples.reduce((a, b) => a + b, 0) / this.samples.length : 0; }
  fps() { const a = this.average(); return a > 0 ? 1000 / a : 0; }
  /** 'down' | 'up' | null. Hysteresis: at least one full window between changes. */
  suggest(tier) {
    if (this.samples.length < this.n || this.sinceChange < this.n) return null;
    const target = QUALITY[tier].fpsTarget, f = this.fps();
    if (f < target * 0.7 && tier !== 'low') return 'down';
    if (f > target * 1.25 && tier !== 'high' && f > 58) return 'up';
    return null;
  }
  reset() { this.samples.length = 0; this.sinceChange = 0; }
}

export function detect(canvas) {
  const gl = canvas.getContext('webgl2', { alpha: true, antialias: false, powerPreference: 'high-performance' });
  if (!gl) return { webgl2: false, rendererName: '', maxTextureSize: 0 };
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  return {
    webgl2: true,
    rendererName: ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : String(gl.getParameter(gl.RENDERER)),
    maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE),
    deviceMemory: navigator.deviceMemory || 4,
    cores: navigator.hardwareConcurrency || 4,
    gl,
  };
}
