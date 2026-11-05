// Performance governor: measures frame time and moves between quality tiers.
// Pure logic (no DOM) so it is testable with node; app.js wires it up.
export class Governor {
  constructor(theme, { initialTier = "reduced", override = null, onChange = () => {} } = {}) {
    this.theme = theme;
    this.order = theme.tierOrder;
    this.cfg = theme.governor;
    this.override = override;                 // a tier name, or null for auto
    this.tier = override || initialTier;
    this.onChange = onChange;
    this.windowStart = null;
    this.frames = 0;
    this.slow = 0;
    this.fast = 0;
  }

  static initialTierFor(nav = {}) {
    // Budget Android tablets: few cores or little memory start one tier down.
    const cores = nav.hardwareConcurrency || 4;
    const mem = nav.deviceMemory || 4;
    if (cores <= 2 || mem <= 2) return "minimal";
    if (cores <= 4 || mem <= 4) return "reduced";
    return "full";
  }

  setOverride(tier) {
    this.override = tier && tier !== "auto" ? tier : null;
    if (this.override) this._set(this.override);
  }

  params() { return this.theme.tiers[this.tier]; }

  // nowMs: rAF timestamp; renderMs: time this frame's drawing took.
  // A capped frame rate hides headroom, so stepping up looks at render cost.
  frame(nowMs, renderMs = 0) {
    if (this.windowStart === null) { this.windowStart = nowMs; this.frames = 0; this.work = 0; return; }
    this.frames += 1;
    this.work += renderMs;
    const span = nowMs - this.windowStart;
    if (span < this.cfg.sampleMs) return;
    const fps = (this.frames * 1000) / span;
    const avgRender = this.work / Math.max(1, this.frames);
    this.windowStart = nowMs;
    this.frames = 0;
    this.work = 0;
    this.lastFps = fps;
    this.lastRenderMs = avgRender;
    if (this.override) return;
    const budget = 1000 / this.cfg.targetFps;
    const delivered = Math.min(this.cfg.targetFps, this.params().maxFps);
    if (fps < delivered * 0.92 || avgRender > budget * 0.8) {
      this.fast = 0;
      if (++this.slow >= this.cfg.downAfter) { this.slow = 0; this._step(+1); }
      return;
    }
    this.slow = 0;
    const richer = this.order[this.order.indexOf(this.tier) - 1];
    if (!richer) { this.fast = 0; return; }
    // The richer tier draws more: only try it when this one costs little.
    const richerBudget = 1000 / Math.min(this.theme.tiers[richer].maxFps, 60);
    if (avgRender < richerBudget / this.cfg.upHeadroom / 2) {
      if (++this.fast >= this.cfg.upAfter) { this.fast = 0; this._step(-1); }
    } else {
      this.fast = 0;
    }
  }

  _step(dir) {
    const i = this.order.indexOf(this.tier) + dir;
    if (i >= 0 && i < this.order.length) this._set(this.order[i]);
  }

  _set(tier) {
    if (tier !== this.tier) {
      this.tier = tier;
      this.onChange(tier);
    }
  }
}
