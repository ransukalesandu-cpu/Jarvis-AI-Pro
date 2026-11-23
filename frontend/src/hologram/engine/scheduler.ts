/**
 * Frame-budget governor: measures real frame times and steps the canvas DPR down when frames run
 * over budget and back up when there is room, always inside the quality tier's DPR range.
 * Pure logic (no React, no WebGL) so it is unit-tested; PerfGovernor.tsx feeds it.
 */

export interface FrameStats { fps: number; frameMs: number }

export const STEP = 0.25;            // DPR change per adjustment
export const WINDOW_MS = 1000;       // stats window
export const SLOW = 1.2;             // average frame over budget by 20% => step down
export const ROOMY = 0.65;           // under 65% of budget for UP_AFTER windows in a row => step up
export const UP_AFTER = 3;
export const STALL_RUN = 3;           // consecutive >250 ms frames before they count as real

export function dprRange(dpr: number | [number, number]): [number, number] {
  return typeof dpr === 'number' ? [dpr, dpr] : dpr;
}

export class FrameBudget {
  readonly budgetMs: number;
  private range: [number, number];
  private dpr: number;
  private acc = 0;
  private frames = 0;
  private roomy = 0;
  private last: FrameStats = { fps: 0, frameMs: 0 };
  private longRun = 0;

  /** targetFps: the tier's cap, or the display rate we aim for (60). Starts at the top of the range. */
  constructor(range: [number, number], targetFps = 60, startDpr?: number) {
    this.range = range;
    this.budgetMs = 1000 / targetFps;
    this.dpr = clamp(startDpr ?? range[1], range[0], range[1]);
  }

  get current(): number { return this.dpr; }
  get stats(): FrameStats { return this.last; }

  /**
   * Feed one frame's interval in ms. Returns the new DPR when it changes, else null.
   * A single interval over 250 ms (tab switch, breakpoint, GC stall) is ignored rather than
   * punished, but three in a row mean the machine really is that slow, and they count (otherwise
   * a very slow GPU would never get its resolution lowered).
   */
  frame(dtMs: number): number | null {
    if (!(dtMs > 0)) return null;
    if (dtMs > 250) {
      this.longRun += 1;
      if (this.longRun < STALL_RUN) return null;
    } else {
      this.longRun = 0;
    }
    this.acc += dtMs;
    this.frames += 1;
    if (this.acc < WINDOW_MS) return null;
    const avg = this.acc / this.frames;
    this.last = { fps: Math.round((1000 * this.frames) / this.acc), frameMs: Math.round(avg * 10) / 10 };
    this.acc = 0;
    this.frames = 0;
    let next = this.dpr;
    if (avg > this.budgetMs * SLOW) {
      next = this.dpr - STEP;
      this.roomy = 0;
    } else if (avg < this.budgetMs * ROOMY) {
      this.roomy += 1;
      if (this.roomy >= UP_AFTER) { next = this.dpr + STEP; this.roomy = 0; }
    } else {
      this.roomy = 0;
    }
    next = clamp(Math.round(next / STEP) * STEP, this.range[0], this.range[1]);
    if (next === this.dpr) return null;
    this.dpr = next;
    return next;
  }
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}
