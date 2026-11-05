import { create } from 'zustand';
import { DurationModel, EXPIRE_MS } from './phase';

export interface Op { id: string; kind: string; label: string; startedAt: number }
export interface Notice { id: number; text: string }

export const durations = new DurationModel();
let noticeId = 0;

interface PendingState {
  ops: Record<string, Op>;
  notice: Notice | null;
  begin: (id: string, kind: string, label: string, now?: number) => void;
  /** ok=true records the duration so future estimates improve; failures never skew them. */
  end: (id: string, ok?: boolean, now?: number) => void;
  expireStale: (now?: number) => void;
  notify: (text: string) => void;
  dismiss: () => void;
}

export const usePending = create<PendingState>((set, get) => ({
  ops: {},
  notice: null,
  begin: (id, kind, label, now = Date.now()) => set((s) => (s.ops[id] ? s : { ops: { ...s.ops, [id]: { id, kind, label, startedAt: now } } })),
  end: (id, ok = true, now = Date.now()) => {
    const op = get().ops[id];
    if (!op) return;
    if (ok) durations.record(op.kind, now - op.startedAt);
    set((s) => { const { [id]: _gone, ...rest } = s.ops; return { ops: rest }; });
  },
  expireStale: (now = Date.now()) => {
    const stale = Object.values(get().ops).filter((o) => now - o.startedAt >= EXPIRE_MS);
    if (stale.length === 0) return;
    set((s) => {
      const ops = { ...s.ops };
      for (const o of stale) delete ops[o.id];
      return { ops, notice: { id: ++noticeId, text: `${stale[0].label} did not respond` } };
    });
  },
  notify: (text) => set({ notice: { id: ++noticeId, text } }),
  dismiss: () => set({ notice: null }),
}));
