import { create } from 'zustand';

export type TimerMode = 'countdown' | 'stopwatch';
export const MAX_COUNTDOWN_S = 24 * 3600;
export const PRESETS_S = [60, 300, 600, 1500] as const;

export interface TimerState {
  mode: TimerMode;
  target: number;             // countdown length in seconds
  running: boolean;
  startedAt: number;          // ms timestamp of the current run (valid while running)
  accumulated: number;        // ms already counted before the current run
  finished: boolean;
}

export const initial: TimerState = { mode: 'countdown', target: 300, running: false, startedAt: 0, accumulated: 0, finished: false };

/** Elapsed ms, computed from timestamps so it stays right while the window is minimised or the tab is throttled. */
export function elapsed(s: TimerState, now: number): number {
  return s.accumulated + (s.running ? Math.max(0, now - s.startedAt) : 0);
}

/** What the display shows, in whole seconds: time left for a countdown, time counted for a stopwatch. */
export function shown(s: TimerState, now: number): number {
  const e = elapsed(s, now);
  return s.mode === 'countdown' ? Math.max(0, Math.ceil((s.target * 1000 - e) / 1000)) : Math.floor(e / 1000);
}

export function format(totalS: number): string {
  const t = Math.max(0, Math.floor(totalS));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  const mm = String(m).padStart(2, '0'), ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export const clampTarget = (s: number): number => (Number.isFinite(s) ? Math.min(MAX_COUNTDOWN_S, Math.max(1, Math.round(s))) : initial.target);

interface TimerStore extends TimerState {
  start: (now?: number) => void;
  pause: (now?: number) => void;
  reset: () => void;
  setMode: (m: TimerMode) => void;
  setTarget: (s: number) => void;
  tick: (now?: number) => void;
}

export const useTimer = create<TimerStore>((set, get) => ({
  ...initial,
  start: (now = Date.now()) => { const s = get(); if (s.running) return; if (s.finished) set({ accumulated: 0, finished: false }); set({ running: true, startedAt: now }); },
  pause: (now = Date.now()) => { const s = get(); if (!s.running) return; set({ running: false, accumulated: elapsed(s, now) }); },
  reset: () => set({ running: false, startedAt: 0, accumulated: 0, finished: false }),
  setMode: (mode) => set({ ...initial, target: get().target, mode }),
  setTarget: (sec) => set({ target: clampTarget(sec), running: false, startedAt: 0, accumulated: 0, finished: false }),
  tick: (now = Date.now()) => {
    const s = get();
    if (s.running && s.mode === 'countdown' && elapsed(s, now) >= s.target * 1000) set({ running: false, accumulated: s.target * 1000, finished: true });
  },
}));
