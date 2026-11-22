import { create } from 'zustand';
import type { Flow, FlowStep, HostEvent, StepStatus } from '../bridge/contract';

/** How long the Task Flow window stays up on its own when a new task starts (owner can pin it by asking). */
export const AUTO_HIDE_MS = 5000;
export const MAX_FLOWS = 20;
export const MAX_LOG = 40;

export interface FlowLogLine { at: number; text: string; level: 'info' | 'ok' | 'err' }

/** Insert or replace by id, oldest first, bounded. */
export function upsertFlow(list: Flow[], flow: Flow): Flow[] {
  const i = list.findIndex((f) => f.id === flow.id);
  const next = i >= 0 ? list.map((f, j) => (j === i ? flow : f)) : [...list, flow];
  next.sort((a, b) => a.startedAt - b.startedAt);
  return next.length > MAX_FLOWS ? next.slice(next.length - MAX_FLOWS) : next;
}

const WORD: Partial<Record<StepStatus, [string, FlowLogLine['level']]>> = {
  running: ['started', 'info'], done: ['✓', 'ok'], error: ['✗', 'err'], skipped: ['skipped', 'info'],
};

/** Activity lines for the brain node: what changed between two snapshots of the same flow. */
export function diffLog(prev: Flow | undefined, next: Flow, at: number): FlowLogLine[] {
  const out: FlowLogLine[] = [];
  if (!prev) out.push({ at, text: next.source === 'agent' ? 'task received' : 'command received', level: 'info' });
  const before = new Map<string, FlowStep>((prev?.steps ?? []).map((s) => [s.id, s]));
  for (const s of next.steps) {
    const old = before.get(s.id);
    if (old && old.status === s.status) continue;
    if (!old && s.status === 'pending') continue;
    const w = WORD[s.status];
    if (!w) continue;
    const tail = s.status === 'running' ? '' : s.detail && s.detail !== 'done' ? ` — ${s.detail}` : '';
    out.push({ at, text: `${s.tool} ${w[0]}${tail}`, level: w[1] });
  }
  if (prev && prev.state !== next.state && next.state !== 'running') {
    out.push({ at, text: next.state === 'done' ? 'all steps finished' : next.state, level: next.state === 'done' ? 'ok' : 'err' });
  }
  return out;
}

export interface FlowWin { open: boolean; pinned: boolean; flowId: string | null }

interface FlowsState {
  flows: Flow[];
  logs: Record<string, FlowLogLine[]>;
  win: FlowWin;
  selected: string | null;      // the flow shown on the Task Progress page
  autoShow: boolean;
  pageRequested: number;        // bumped when the owner asks for the page (App switches to it)
  apply: (e: HostEvent, now?: number) => void;
  showWindow: (pinned: boolean, flowId?: string | null) => void;
  hideWindow: () => void;
  select: (id: string | null) => void;
  setAutoShow: (v: boolean) => void;
}

const readAuto = (): boolean => { try { return localStorage.getItem('jarvis.taskflow.autoshow') !== '0'; } catch { return true; } };

export const useFlows = create<FlowsState>((set, get) => ({
  flows: [], logs: {}, win: { open: false, pinned: false, flowId: null }, selected: null, autoShow: readAuto(), pageRequested: 0,
  apply: (e, now = Date.now()) => {
    if (e.type === 'task.flow') {
      const s = get();
      const prev = s.flows.find((f) => f.id === e.flow.id);
      const lines = diffLog(prev, e.flow, now);
      const logs = { ...s.logs };
      if (lines.length) logs[e.flow.id] = [...(logs[e.flow.id] ?? []), ...lines].slice(-MAX_LOG);
      const flows = upsertFlow(s.flows, e.flow);
      const kept = new Set(flows.map((f) => f.id));
      for (const id of Object.keys(logs)) if (!kept.has(id)) delete logs[id];
      // A task that just started pops the window up (unpinned: it hides itself after AUTO_HIDE_MS).
      const isNew = !prev && e.flow.state === 'running' && now - e.flow.startedAt < 60_000;
      const win = isNew && s.autoShow ? { open: true, pinned: s.win.open && s.win.pinned, flowId: e.flow.id }
        : s.win.open && !s.win.pinned && isNew ? { ...s.win, flowId: e.flow.id } : s.win;
      set({ flows, logs, win });
    } else if (e.type === 'ui.task_flow') {
      if (e.view === 'window') get().showWindow(true);
      else if (e.view === 'hide') get().hideWindow();
      else set((s) => ({ pageRequested: s.pageRequested + 1, win: { ...s.win, open: false } }));
    }
  },
  showWindow: (pinned, flowId = null) => set((s) => ({ win: { open: true, pinned, flowId: flowId ?? s.flows[s.flows.length - 1]?.id ?? null } })),
  hideWindow: () => set((s) => ({ win: { ...s.win, open: false, pinned: false } })),
  select: (selected) => set({ selected }),
  setAutoShow: (autoShow) => { try { localStorage.setItem('jarvis.taskflow.autoshow', autoShow ? '1' : '0'); } catch { /* storage may be off */ } set({ autoShow }); },
}));

/** The flow the window shows: the one it was opened for, else the newest. */
export function windowFlow(s: Pick<FlowsState, 'flows' | 'win'>): Flow | null {
  return s.flows.find((f) => f.id === s.win.flowId) ?? s.flows[s.flows.length - 1] ?? null;
}

export const counts = (f: Flow) => ({
  total: f.steps.length,
  done: f.steps.filter((s) => s.status === 'done').length,
  errors: f.steps.filter((s) => s.status === 'error').length,
});

export function elapsed(from: number, to: number | null, now: number): string {
  const s = Math.max(0, ((to ?? now) - from) / 1000);
  return s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

// Dev preview only (npm run dev has no backend): lets a test script drive the window. Stripped from builds.
if (import.meta.env.DEV) (globalThis as Record<string, unknown>).__jarvisFlows = useFlows;
