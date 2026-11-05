// Single animation loop, visibility pausing, resize handling, context loss and disposal.
// There is exactly one requestAnimationFrame chain; start() is idempotent.

export class Lifecycle {
  constructor({ canvas, onFrame, onResize, onContextLost, onContextRestored }) {
    this.canvas = canvas; this.onFrame = onFrame; this.onResize = onResize;
    this.onContextLost = onContextLost; this.onContextRestored = onContextRestored;
    this.raf = 0; this.running = false; this.hostVisible = true; this.contextLost = false;
    this.last = 0; this.minFrameMs = 0; this.disposed = false;
    this._tick = this._tick.bind(this);
    this._vis = () => this._sync();
    this._lost = (e) => { e.preventDefault(); this.contextLost = true; this._sync(); this.onContextLost?.(); };
    this._restored = () => { this.contextLost = false; this.onContextRestored?.(); this._sync(); };
    document.addEventListener('visibilitychange', this._vis);
    canvas.addEventListener('webglcontextlost', this._lost);
    canvas.addEventListener('webglcontextrestored', this._restored);
    this.ro = new ResizeObserver(() => this._resize());
    this.ro.observe(canvas);
    this.listeners = [];
  }
  get shouldRun() { return !this.disposed && !document.hidden && this.hostVisible && !this.contextLost; }
  setHostVisible(v) { this.hostVisible = !!v; this._sync(); }
  setFrameInterval(ms) { this.minFrameMs = Math.max(0, ms); }
  _resize() {
    const r = this.canvas.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) this.onResize?.(r.width, r.height);
  }
  _sync() {
    if (this.shouldRun) this.start(); else this.stop();
  }
  start() {
    if (this.running || this.disposed) return;
    this.running = true; this.last = 0;
    this.raf = requestAnimationFrame(this._tick);
  }
  stop() {
    this.running = false;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
  }
  _tick(now) {
    if (!this.running) return;
    this.raf = requestAnimationFrame(this._tick);
    if (this.last && now - this.last < this.minFrameMs - 1) return;
    const dt = this.last ? Math.min(0.1, (now - this.last) / 1000) : 1 / 60;
    const frameMs = this.last ? now - this.last : 16.7;
    this.last = now;
    this.onFrame(dt, now / 1000, frameMs);
  }
  dispose() {
    this.disposed = true; this.stop();
    document.removeEventListener('visibilitychange', this._vis);
    this.canvas.removeEventListener('webglcontextlost', this._lost);
    this.canvas.removeEventListener('webglcontextrestored', this._restored);
    this.ro.disconnect();
  }
}
