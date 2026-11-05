import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { beforeEach, describe, expect, it } from 'vitest';
import { clampTarget, elapsed, format, initial, shown, useTimer } from './timer';
import { TimerView } from '../ui/TimerWindow';

beforeEach(() => useTimer.setState({ ...initial }));

describe('timer maths', () => {
  it('formats mm:ss and h:mm:ss', () => {
    expect(format(0)).toBe('00:00'); expect(format(65)).toBe('01:05'); expect(format(3725)).toBe('1:02:05'); expect(format(-4)).toBe('00:00');
  });
  it('counts down from timestamps and survives pause/resume', () => {
    const t = useTimer.getState();
    t.setTarget(60);
    useTimer.getState().start(1000);
    expect(shown(useTimer.getState(), 11_000)).toBe(50);
    useTimer.getState().pause(11_000);
    expect(shown(useTimer.getState(), 99_000)).toBe(50);           // paused time does not count
    useTimer.getState().start(100_000);
    expect(shown(useTimer.getState(), 105_000)).toBe(45);
  });
  it('finishes exactly once and stays at zero', () => {
    useTimer.getState().setTarget(5);
    useTimer.getState().start(0);
    useTimer.getState().tick(4_999); expect(useTimer.getState().finished).toBe(false);
    useTimer.getState().tick(5_000);
    const s = useTimer.getState();
    expect(s.finished).toBe(true); expect(s.running).toBe(false); expect(shown(s, 60_000)).toBe(0);
  });
  it('stopwatch counts up; reset clears; starting after finish restarts', () => {
    useTimer.getState().setMode('stopwatch');
    useTimer.getState().start(0);
    expect(shown(useTimer.getState(), 7_900)).toBe(7);
    useTimer.getState().reset(); expect(elapsed(useTimer.getState(), 9_999)).toBe(0);
    useTimer.getState().setMode('countdown'); useTimer.getState().setTarget(1); useTimer.getState().start(0); useTimer.getState().tick(1_000);
    useTimer.getState().start(2_000);
    expect(useTimer.getState().finished).toBe(false); expect(shown(useTimer.getState(), 2_000)).toBe(1);
  });
  it('clamps silly lengths', () => {
    expect(clampTarget(0)).toBe(1); expect(clampTarget(1e9)).toBe(86400); expect(clampTarget(NaN)).toBe(300);
  });
});

describe('TimerView', () => {
  const noop = () => {};
  const base = { ...initial, now: 0, onStart: noop, onPause: noop, onReset: noop, onMode: noop, onPreset: noop };
  it('shows time, labels and state', () => {
    const idle = renderToStaticMarkup(createElement(TimerView, base));
    expect(idle).toContain('05:00'); expect(idle).toContain('Ready'); expect(idle).toContain('aria-label="Start timer"');
    const done = renderToStaticMarkup(createElement(TimerView, { ...base, finished: true, accumulated: 300_000 }));
    expect(done).toContain('00:00'); expect(done).toContain('Time is up');
  });
});
