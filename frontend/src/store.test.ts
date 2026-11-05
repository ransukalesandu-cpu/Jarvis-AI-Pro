import { beforeEach, describe, expect, it } from 'vitest';
import { useUi } from './store';

describe('store', () => {
  beforeEach(() => useUi.setState({ assistant: 'idle', metrics: null, link: 'connecting' }));
  it('applies host events', () => {
    useUi.getState().apply({ type: 'assistant.state_changed', state: 'thinking' });
    expect(useUi.getState().assistant).toBe('thinking');
    useUi.getState().apply({ type: 'system.metrics_updated', cpu: 10, ram: 20, disk: null, battery: null, net: null });
    expect(useUi.getState().metrics?.cpu).toBe(10);
  });
  it('has no invented metrics before the host sends any', () => {
    expect(useUi.getState().metrics).toBeNull();
  });
  it('navigation closes the menu', () => {
    useUi.getState().toggleNav(true);
    useUi.getState().go('monitor');
    expect(useUi.getState().page).toBe('monitor');
    expect(useUi.getState().navOpen).toBe(false);
  });
});

import { parseHostEvent as _parse } from './bridge/contract';
describe('assistant.muted', () => {
  it('parses only booleans and updates the store', () => {
    expect(_parse(JSON.stringify({ type: 'assistant.muted', muted: true }))).toEqual({ type: 'assistant.muted', muted: true });
    expect(_parse(JSON.stringify({ type: 'assistant.muted', muted: 'yes' }))).toBeNull();
    useUi.getState().apply({ type: 'assistant.muted', muted: true });
    expect(useUi.getState().muted).toBe(true);
  });
});

import { SERIES_MAX } from './store';
describe('metric series', () => {
  it('records real samples, caps the length and never invents a network sample', () => {
    useUi.setState({ series: { cpu: [], ram: [], down: [], up: [] } });
    for (let i = 0; i < SERIES_MAX + 30; i++) useUi.getState().apply({ type: 'system.metrics_updated', cpu: i % 100, ram: 5, disk: null, battery: null, net: null });
    const s = useUi.getState().series;
    expect(s.cpu).toHaveLength(SERIES_MAX);
    expect(s.cpu[s.cpu.length - 1]).toBe((SERIES_MAX + 29) % 100);
    expect(s.down).toHaveLength(0);                       // net was null -> nothing drawn
    useUi.getState().apply({ type: 'system.metrics_updated', cpu: 1, ram: 1, disk: null, battery: null, net: { downKBps: 7, upKBps: 2 } });
    expect(useUi.getState().series.down.at(-1)).toBe(7);
  });
});

describe('command bar state', () => {
  it('starts unavailable, follows the host, and parses only known values', () => {
    expect(useUi.getState().command.state).toBe('unavailable');
    expect(_parse(JSON.stringify({ type: 'command.availability', state: 'auth_required' }))).not.toBeNull();
    expect(_parse(JSON.stringify({ type: 'command.availability', state: 'whenever' }))).toBeNull();
    expect(_parse(JSON.stringify({ type: 'command.result', reason: 'sent' }))).not.toBeNull();
    expect(_parse(JSON.stringify({ type: 'command.result', reason: 'oops' }))).toBeNull();
    useUi.getState().apply({ type: 'command.availability', state: 'ok' });
    useUi.getState().apply({ type: 'command.result', reason: 'rate_limited' });
    expect(useUi.getState().command).toEqual({ state: 'ok', last: 'rate_limited' });
  });
});
