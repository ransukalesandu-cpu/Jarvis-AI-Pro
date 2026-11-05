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
