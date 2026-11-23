import { describe, expect, it } from 'vitest';
import { parseHostEvent } from './contract';

const j = (o: unknown) => JSON.stringify(o);

describe('parseHostEvent', () => {
  it('accepts valid events', () => {
    expect(parseHostEvent(j({ type: 'assistant.state_changed', state: 'speaking' }))).toEqual({ type: 'assistant.state_changed', state: 'speaking' });
    expect(parseHostEvent(j({ type: 'system.metrics_updated', cpu: 12.5, ram: 40, disk: null, battery: { percent: 80, charging: true }, net: null }))?.type).toBe('system.metrics_updated');
  });
  it('rejects unknown types, bad values and oversize input', () => {
    expect(parseHostEvent(j({ type: 'evil', x: 1 }))).toBeNull();
    expect(parseHostEvent(j({ type: 'assistant.state_changed', state: 'dancing' }))).toBeNull();
    expect(parseHostEvent(j({ type: 'assistant.audio_level', level: 2, source: 'output' }))).toBeNull();
    expect(parseHostEvent(j({ type: 'assistant.audio_level', level: NaN, source: 'output' }))).toBeNull();
    expect(parseHostEvent(j({ type: 'system.metrics_updated', cpu: 120, ram: 1, disk: null, battery: null, net: null }))).toBeNull();
    expect(parseHostEvent('x'.repeat(5000))).toBeNull();
    expect(parseHostEvent('not json')).toBeNull();
    expect(parseHostEvent(42)).toBeNull();
    expect(parseHostEvent('[1,2]')).toBeNull();
  });
});

describe('ui.perf', () => {
  it('accepts the three tiers and nothing else', () => {
    for (const tier of ['full', 'balanced', 'lite']) expect(parseHostEvent(j({ type: 'ui.perf', tier }))).toEqual({ type: 'ui.perf', tier });
    for (const tier of ['auto', 'turbo', '', 3, null]) expect(parseHostEvent(j({ type: 'ui.perf', tier }))).toBeNull();
  });
});

describe('ui.prefs', () => {
  const good = { reducedMotion: true, clock24: false, taskflowAutoShow: true, centerStyle: 'brain', faceStyle: 'circuit' };
  it('accepts exactly the three boolean prefs, or null', () => {
    expect(parseHostEvent(j({ type: 'ui.prefs', prefs: good }))).toEqual({ type: 'ui.prefs', prefs: good });
    expect(parseHostEvent(j({ type: 'ui.prefs', prefs: null }))).toEqual({ type: 'ui.prefs', prefs: null });
  });
  it('rejects extra keys, missing keys and non-booleans', () => {
    expect(parseHostEvent(j({ type: 'ui.prefs', prefs: { ...good, x: true } }))).toBeNull();
    expect(parseHostEvent(j({ type: 'ui.prefs', prefs: { clock24: true } }))).toBeNull();
    expect(parseHostEvent(j({ type: 'ui.prefs', prefs: { ...good, clock24: 1 } }))).toBeNull();
    expect(parseHostEvent(j({ type: 'ui.prefs', prefs: { ...good, centerStyle: 'evil' } }))).toBeNull();
  });
});

describe('hologram engine v2 phase 1 messages', () => {
  it('accepts the warning state', () => {
    expect(parseHostEvent(JSON.stringify({ type: 'assistant.state_changed', state: 'warning' }))).toEqual({ type: 'assistant.state_changed', state: 'warning' });
  });
  it('accepts a bounded perf report and rejects bad values', () => {
    const ok = { type: 'hologram.perf_report', cpu: 12.5, ramMb: 410, processes: 3 };
    expect(parseHostEvent(JSON.stringify(ok))).toEqual(ok);
    expect(parseHostEvent(JSON.stringify({ ...ok, cpu: 140 }))).toBeNull();
    expect(parseHostEvent(JSON.stringify({ ...ok, processes: 1.5 }))).toBeNull();
    expect(parseHostEvent(JSON.stringify({ ...ok, ramMb: -1 }))).toBeNull();
  });
});
