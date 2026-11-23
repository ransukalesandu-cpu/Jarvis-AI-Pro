import { describe, expect, it } from 'vitest';
import { dprRange, FrameBudget, UP_AFTER } from './scheduler';

const run = (b: FrameBudget, ms: number, seconds: number) => {
  const changes: number[] = [];
  for (let t = 0; t < seconds * 1000; t += ms) { const c = b.frame(ms); if (c !== null) changes.push(c); }
  return changes;
};

describe('FrameBudget (adaptive DPR)', () => {
  it('starts at the top of the range and reports measured fps/frame ms', () => {
    const b = new FrameBudget([1, 2], 60);
    expect(b.current).toBe(2);
    run(b, 16, 1.1);
    expect(b.stats.fps).toBeGreaterThanOrEqual(60);
    expect(b.stats.frameMs).toBeCloseTo(16, 0);
  });
  it('steps DPR down while frames are over budget, never below the range', () => {
    const b = new FrameBudget([1, 2], 60);
    expect(run(b, 40, 10)).toEqual([1.75, 1.5, 1.25, 1]);
    expect(b.current).toBe(1);
  });
  it('steps back up only after sustained headroom, never above the range', () => {
    const b = new FrameBudget([1, 1.5], 60, 1);
    run(b, 8, UP_AFTER - 0.5);
    expect(b.current).toBe(1);
    run(b, 8, 10);
    expect(b.current).toBe(1.5);
  });
  it('holds steady inside the budget band and ignores stalls', () => {
    const b = new FrameBudget([1, 2], 60, 1.5);
    expect(run(b, 15, 5)).toEqual([]);
    expect(b.frame(5000)).toBeNull();
    expect(b.current).toBe(1.5);
  });
  it('a machine that is genuinely slow (every frame > 250 ms) still gets its DPR lowered', () => {
    const b = new FrameBudget([1, 2], 60);
    expect(run(b, 400, 12)).toEqual([1.75, 1.5, 1.25, 1]);
  });
  it('a fixed DPR tier never changes; the budget follows the fps cap', () => {
    const b = new FrameBudget(dprRange(1), 30);
    expect(b.budgetMs).toBeCloseTo(33.3, 1);
    expect(run(b, 80, 5)).toEqual([]);
  });
});
