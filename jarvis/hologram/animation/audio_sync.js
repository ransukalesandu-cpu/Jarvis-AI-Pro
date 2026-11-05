// Output-audio synchronisation. Only a single level (0..1) per update arrives from
// the host (never raw audio). We keep a fast-attack / slow-release envelope and,
// when the host also sends mouth shapes (openness / width), smooth those too.
// The mouth is driven by the envelope or the supplied openness; there is no
// invented lip-sync, and jaw travel is clamped so the face cannot deform wildly.

import { damp, clamp } from './transitions.js';

export class AudioSync {
  constructor() {
    this.outEnv = 0; this.inEnv = 0;
    this.outTarget = 0; this.inTarget = 0;
    this.openTarget = -1; this.widthTarget = 0;   // openTarget < 0: derive from the envelope
    this.mouth = 0; this.width = 0;
    this.lastOutputAt = -Infinity;
  }
  pushOutput(level, now, open, width) {
    this.outTarget = clamp(level, 0, 1);
    this.openTarget = open === undefined ? -1 : clamp(open, 0, 1);
    this.widthTarget = width === undefined ? 0 : clamp(width, -1, 1);
    if (level > 0.02) this.lastOutputAt = now;
  }
  endOutput() { this.outTarget = 0; this.openTarget = -1; this.widthTarget = 0; }
  pushInput(level) { this.inTarget = clamp(level, 0, 1); }

  update(dt, now, speaking) {
    // Output: quick attack, slower release so chunk boundaries do not flicker.
    const silent = now - this.lastOutputAt > 0.35;
    const outT = speaking && !silent ? this.outTarget : 0;
    this.outEnv = damp(this.outEnv, outT, outT > this.outEnv ? 22 : 7, dt);
    this.inEnv = damp(this.inEnv, this.inTarget, this.inTarget > this.inEnv ? 16 : 6, dt);
    const openT = outT <= 0 ? 0 : (this.openTarget >= 0 ? this.openTarget * clamp(this.outEnv * 1.6, 0, 1) : this.outEnv);
    this.mouth = damp(this.mouth, clamp(openT, 0, 1) * 0.9, 18, dt);   // 0.9 caps jaw travel
    this.width = damp(this.width, outT > 0 ? this.widthTarget : 0, 14, dt);
    return this;
  }
}
