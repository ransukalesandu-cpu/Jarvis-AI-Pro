// Arc-reactor orb: Canvas 2D + requestAnimationFrame, no CSS filters or blur.
// Glow is drawn with radial gradients; effects scale with the governor tier.
import { THEME } from "./theme.js";

const TAU = Math.PI * 2;

function mix(a, b, t) { return a + (b - a) * t; }
function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgba(hex, a) { const [r, g, b] = hexToRgb(hex); return `rgba(${r},${g},${b},${a})`; }

export class Orb {
  constructor(canvas, governor) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: true, desynchronized: true });
    this.governor = governor;
    this.state = "disconnected";
    this.level = 0;          // smoothed 0..1 audio level
    this.target = 0;
    this.t0 = performance.now();
    this.last = 0;
    this.particles = [];
    this._resize = this.resize.bind(this);
    window.addEventListener("resize", this._resize);
    this.resize();
    this.running = false;
  }

  setState(state) { if (THEME.states[state]) this.state = state; }
  setLevel(v) { this.target = Math.max(0, Math.min(1, v * THEME.orb.levelGain)); }

  resize() {
    const p = this.governor.params();
    const dpr = Math.min(window.devicePixelRatio || 1, p.maxDpr);
    const rect = this.canvas.getBoundingClientRect();
    this.w = Math.max(1, rect.width);
    this.h = Math.max(1, rect.height);
    this.canvas.width = Math.round(this.w * dpr);
    this.canvas.height = Math.round(this.h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this._seed(p.particles);
  }

  _seed(n) {
    this.particles = Array.from({ length: n }, (_, i) => ({
      a: (i / Math.max(1, n)) * TAU + Math.random() * 0.4,
      r: 1.08 + Math.random() * 0.55,
      s: 0.15 + Math.random() * 0.6,
      z: 0.4 + Math.random() * 0.6,
    }));
  }

  start() {
    if (this.running) return;
    this.running = true;
    const loop = (now) => {
      if (!this.running) return;
      requestAnimationFrame(loop);
      const p = this.governor.params();
      if (now - this.last < 1000 / p.maxFps - 1) return;    // frame-rate cap per tier
      this.last = now;
      const t0 = performance.now();
      this.draw(now, p);
      this.governor.frame(now, performance.now() - t0);
    };
    requestAnimationFrame(loop);
  }

  stop() { this.running = false; }

  draw(now, p) {
    const ctx = this.ctx;
    const st = THEME.states[this.state];
    const t = (now - this.t0) / 1000;
    this.level = mix(this.level, this.target, THEME.orb.levelSmoothing);
    const cx = this.w / 2, cy = this.h / 2;
    const R = Math.min(this.w, this.h) * THEME.orb.radiusFrac;
    const pulse = this.state === "listening" ? 0.04 * Math.sin(t * 4) : 0;
    const lv = this.state === "speaking" || this.state === "listening" ? this.level : 0;
    const core = R * (0.36 + 0.16 * lv + pulse);

    ctx.clearRect(0, 0, this.w, this.h);

    // Glow: layered radial gradients (cheap compared with blur filters).
    for (let i = 0; i < p.glowLayers; i++) {
      const gr = R * (1.1 + i * 0.35 + lv * 0.3);
      const g = ctx.createRadialGradient(cx, cy, core * 0.3, cx, cy, gr);
      g.addColorStop(0, rgba(st.core, 0.32 * st.glow / (i + 1)));
      g.addColorStop(1, rgba(st.core, 0));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(cx, cy, gr, 0, TAU);
      ctx.fill();
    }

    // Rings: rotating arc segments.
    ctx.lineCap = "round";
    for (let i = 0; i < p.rings; i++) {
      const rr = R * (0.55 + i * 0.12);
      const dir = i % 2 ? -1 : 1;
      const seg = 3 + i;
      const rot = t * st.spin * dir * (1 + i * 0.15);
      ctx.strokeStyle = rgba(i % 2 ? st.ring : st.core, 0.35 + 0.4 * st.glow / (i + 1) + lv * 0.2);
      ctx.lineWidth = Math.max(1, R * (0.018 - i * 0.002));
      for (let k = 0; k < seg; k++) {
        const a0 = rot + (k / seg) * TAU;
        ctx.beginPath();
        ctx.arc(cx, cy, rr, a0, a0 + (TAU / seg) * 0.62);
        ctx.stroke();
      }
    }

    // Core.
    const cg = ctx.createRadialGradient(cx, cy, 0, cx, cy, core);
    cg.addColorStop(0, "rgba(255,255,255,0.95)");
    cg.addColorStop(0.35, rgba(st.core, 0.9));
    cg.addColorStop(1, rgba(st.core, 0.05));
    ctx.fillStyle = cg;
    ctx.beginPath();
    ctx.arc(cx, cy, core, 0, TAU);
    ctx.fill();

    // Particles orbiting outside the rings.
    if (this.particles.length !== p.particles) this._seed(p.particles);
    ctx.fillStyle = rgba(st.core, 0.8);
    for (const q of this.particles) {
      q.a += 0.004 * q.s * (1 + st.spin + lv * 2);
      const rr = R * (q.r + lv * 0.25 * q.z);
      const x = cx + Math.cos(q.a) * rr, y = cy + Math.sin(q.a) * rr * 0.92;
      const size = 0.6 + q.z * 1.8 + (p.sparks ? lv * 2 : 0);
      ctx.globalAlpha = 0.25 + q.z * 0.6;
      ctx.fillRect(x - size / 2, y - size / 2, size, size);
    }
    ctx.globalAlpha = 1;
  }
}
