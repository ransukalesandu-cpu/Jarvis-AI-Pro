import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useUi } from '../store';
import { usePending } from './pending';
import { onHostEvent, onRequest, resetActions } from './actions';
import { PageSkeleton, SyncStatusView } from '../ui/Feedback';

beforeEach(() => { vi.useFakeTimers(); resetActions(); usePending.setState({ ops: {}, notice: null }); useUi.setState({ muted: false, workspaceNames: ['a'] }); });

describe('optimistic mute (tap first, sync later)', () => {
  it('flips at once and keeps the value when the backend confirms', () => {
    onRequest({ kind: 'control.do', action: 'mute' });
    expect(useUi.getState().muted).toBe(true);
    onHostEvent({ type: 'assistant.muted', muted: true } as never);
    expect(useUi.getState().muted).toBe(true);
    expect(usePending.getState().ops.mute).toBeUndefined();
  });
  it('rolls back and says why when the backend refuses', () => {
    onRequest({ kind: 'control.do', action: 'mute' });
    onHostEvent({ type: 'control.result', action: 'mute', reason: 'locked' } as never);
    expect(useUi.getState().muted).toBe(false);
    expect(usePending.getState().notice?.text).toBe('Microphone change refused');
  });
  it('rolls back when the backend never answers', () => {
    onRequest({ kind: 'control.do', action: 'mute' });
    vi.advanceTimersByTime(6001);
    expect(useUi.getState().muted).toBe(false);
    expect(usePending.getState().notice).not.toBeNull();
  });
  it('does nothing when already in that state', () => {
    onRequest({ kind: 'control.do', action: 'unmute' });
    expect(usePending.getState().ops.mute).toBeUndefined();
  });
});

describe('optimistic workspace list', () => {
  it('adds and removes names immediately; autosave stays silent', () => {
    onRequest({ kind: 'workspace.save', name: 'b', layout: {} as never });
    expect(useUi.getState().workspaceNames).toEqual(['a', 'b']);
    onRequest({ kind: 'workspace.delete', name: 'a' });
    expect(useUi.getState().workspaceNames).toEqual(['b']);
    onRequest({ kind: 'workspace.save', name: '_last', layout: {} as never });
    expect(useUi.getState().workspaceNames).toEqual(['b']);
  });
});

describe('views', () => {
  it('renders nothing under 1 s, a label in the middle, progress + time left after 10 s', () => {
    const r = (p: Parameters<typeof SyncStatusView>[0]) => renderToStaticMarkup(createElement(SyncStatusView, p));
    expect(r({ phase: 'none', label: 'Loading', est: null })).toBe('');
    const mid = r({ phase: 'skeleton', label: 'Loading', est: null });
    expect(mid).toContain('Loading…'); expect(mid).not.toContain('progressbar');
    const long = r({ phase: 'progress', label: 'Loading', est: { fraction: 0.4, remainingMs: 12000 } });
    expect(long).toContain('role="progressbar"'); expect(long).toContain('about 12 s left (estimate)');
  });
  it('skeleton is hidden from assistive tech', () => {
    expect(renderToStaticMarkup(createElement(PageSkeleton))).toContain('aria-hidden="true"');
  });
});
