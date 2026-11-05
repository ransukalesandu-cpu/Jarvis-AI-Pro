import { useUi } from '../store';
import { usePending } from './pending';
import type { HostEvent, UiRequest } from '../bridge/contract';

/** Optimistic apply + bookkeeping for requests ("tap first, sync later"), and the settle step for host events.
 *  The UI changes at once; the Python backend stays the authority and its answer either confirms or rolls back. */
export const OPTIMISTIC_TIMEOUT_MS = 6000;
export const REFUSALS = new Set(['locked', 'auth_required', 'silent', 'guest', 'rate_limited', 'unavailable', 'credential']);

let muteOp: { from: boolean; to: boolean; timer: ReturnType<typeof setTimeout> } | null = null;
let resync: (() => void) | null = null;
export const setResync = (fn: (() => void) | null) => { resync = fn; };

function clearMute() { if (muteOp) clearTimeout(muteOp.timer); muteOp = null; usePending.getState().end('mute', false); }

function rollbackMute(why: string) {
  if (!muteOp) return;
  const from = muteOp.from;
  clearMute();
  useUi.setState({ muted: from });
  usePending.getState().notify(why);
}

export function onRequest(r: UiRequest): void {
  const p = usePending.getState();
  switch (r.kind) {
    case 'workspace.load': p.begin('ws.load', 'workspace.load', 'Loading workspace'); break;
    case 'command.submit': p.begin('cmd', 'command', 'Sending'); break;
    case 'workspace.save': case 'workspace.delete': {
      if (r.name === '_last') break;                      // autosave is silent
      const names = useUi.getState().workspaceNames;
      const next = r.kind === 'workspace.save' ? (names.includes(r.name) ? names : [...names, r.name].sort()) : names.filter((n) => n !== r.name);
      useUi.setState({ workspaceNames: next });           // optimistic; workspace.list reconciles
      p.begin('ws.' + r.kind, r.kind, r.kind === 'workspace.save' ? 'Saving workspace' : 'Deleting workspace');
      setTimeout(() => { if (usePending.getState().ops['ws.' + r.kind]) { usePending.getState().end('ws.' + r.kind, false); resync?.(); } }, OPTIMISTIC_TIMEOUT_MS);
      break;
    }
    case 'control.do': {
      if (r.action === 'mute' || r.action === 'unmute') {
        if (muteOp) break;
        const to = r.action === 'mute';
        const from = useUi.getState().muted;
        if (from === to) break;
        useUi.setState({ muted: to });                    // the tap shows its effect immediately
        p.begin('mute', 'mute', 'Microphone');
        muteOp = { from, to, timer: setTimeout(() => rollbackMute('Microphone change was not confirmed'), OPTIMISTIC_TIMEOUT_MS) };
      } else p.begin('control', 'control', 'Action');
      break;
    }
  }
}

export function onHostEvent(e: HostEvent): void {
  const p = usePending.getState();
  switch (e.type) {
    case 'host.hello': p.end('startup'); p.begin('metrics', 'startup', 'Loading live data'); break;
    case 'system.metrics_updated': p.end('metrics'); break;
    case 'workspace.loaded': p.end('ws.load'); break;
    case 'workspace.list': p.end('ws.workspace.save'); p.end('ws.workspace.delete'); break;
    case 'command.result': p.end('cmd', e.reason === 'sent' || e.reason === 'done'); if (REFUSALS.has(e.reason)) p.notify('Not sent'); break;
    case 'assistant.muted': if (muteOp) clearMute(); break;       // backend agrees: the optimistic value stands
    case 'control.result':
      p.end('control');
      if (muteOp && REFUSALS.has(e.reason)) rollbackMute('Microphone change refused'); // backend said no: undo
      else if (muteOp && (e.reason === 'done' || e.reason === 'noop')) clearMute();
      break;
  }
}

export function resetActions(): void { clearMute(); resync = null; }
