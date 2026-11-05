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
