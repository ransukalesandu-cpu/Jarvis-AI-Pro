import { beforeEach, describe, expect, it } from 'vitest';
import { DurationModel, estimate, EXPIRE_MS, formatRemaining, phaseFor, PROGRESS_AFTER_MS, SHOW_AFTER_MS } from './phase';
import { usePending } from './pending';

describe('phaseFor (the three rules)', () => {
  it('shows nothing under 1 s', () => {
    for (const ms of [0, 1, 250, 999]) expect(phaseFor(ms)).toBe('none');
  });
  it('shows a skeleton from 1 s up to 10 s', () => {
    for (const ms of [SHOW_AFTER_MS, 2500, PROGRESS_AFTER_MS - 1]) expect(phaseFor(ms)).toBe('skeleton');
  });
  it('shows progress and time left from 10 s', () => {
    for (const ms of [PROGRESS_AFTER_MS, 30_000, 10 ** 7]) expect(phaseFor(ms)).toBe('progress');
  });
  it('treats garbage as nothing', () => {
    for (const v of [NaN, -5, Infinity * 0]) expect(phaseFor(v)).toBe('none');
  });
});

describe('estimate', () => {
  it('never reaches 100 % and never says 0 s left', () => {
    for (const [e, x] of [[10_000, 12_000], [50_000, 12_000], [5, 5]]) {
      const r = estimate(e, x);
      expect(r.fraction).toBeLessThanOrEqual(0.95);
      expect(r.remainingMs).toBeGreaterThanOrEqual(1000);
    }
  });
  it('shrinks the remaining time as it gets closer, and grows the guess when it overruns', () => {
    expect(estimate(11_000, 20_000).remainingMs).toBeLessThan(estimate(10_000, 20_000).remainingMs);
    expect(estimate(60_000, 20_000).remainingMs).toBeGreaterThan(estimate(30_000, 20_000).remainingMs);
  });
  it('formats time left plainly', () => {
    expect(formatRemaining(1500)).toBe('a few seconds left');
    expect(formatRemaining(12_000)).toBe('about 12 s left');
    expect(formatRemaining(47_000)).toBe('about 45 s left');
    expect(formatRemaining(150_000)).toBe('about 3 min left');
  });
});

describe('DurationModel', () => {
  it('starts from defaults, learns, and ignores nonsense', () => {
    const m = new DurationModel(0.5);
    expect(m.expected('startup')).toBe(6000);
    expect(m.expected('something-new')).toBe(5000);
    m.record('startup', 2000);
    expect(m.expected('startup')).toBe(2000);
    m.record('startup', 4000);
    expect(m.expected('startup')).toBe(3000);
    m.record('startup', -1); m.record('startup', NaN);
    expect(m.expected('startup')).toBe(3000);
  });
});

describe('pending store', () => {
  beforeEach(() => usePending.setState({ ops: {}, notice: null }));
  it('tracks an operation once and ends it', () => {
    const p = usePending.getState();
    p.begin('a', 'command', 'Sending', 100);
    p.begin('a', 'command', 'Sending', 999);           // a duplicate begin does not restart the clock
    expect(usePending.getState().ops.a.startedAt).toBe(100);
    p.end('a', true, 400);
    expect(usePending.getState().ops.a).toBeUndefined();
  });
  it('drops an operation that never answers and says so', () => {
    const p = usePending.getState();
    p.begin('x', 'workspace.load', 'Loading workspace', 0);
    p.expireStale(EXPIRE_MS - 1);
    expect(usePending.getState().ops.x).toBeDefined();
    p.expireStale(EXPIRE_MS);
    expect(usePending.getState().ops.x).toBeUndefined();
    expect(usePending.getState().notice?.text).toBe('Loading workspace did not respond');
  });
  it('ending something that is not pending is harmless', () => {
    usePending.getState().end('nope');
    expect(usePending.getState().notice).toBeNull();
  });
});
