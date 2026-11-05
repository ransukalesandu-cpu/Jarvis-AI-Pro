import { create } from 'zustand';
import { clampRect, MAX_WINDOWS, MIN_H, MIN_W, place, snap, tile, TITLES, type Layout, type Viewport, type WinKind, type WindowRec } from './layout';
import type { Page } from '../store';

interface WinStore {
  windows: WindowRec[];
  viewport: Viewport;
  setViewport: (v: Viewport) => void;
  open: (kind: WinKind) => string | null;
  close: (id: string) => void;
  closeAll: () => void;
  focus: (id: string) => void;
  minimize: (id: string) => void;
  minimizeAll: () => void;
  restore: (id: string) => void;
  toggleMaximize: (id: string) => void;
  move: (id: string, x: number, y: number) => void;
  resize: (id: string, x: number, y: number, w: number, h: number) => void;
  tileAll: () => void;
  apply: (layout: Layout) => void;
  snapshot: (page: Page) => Layout;
}

const topZ = (ws: WindowRec[]) => ws.reduce((m, w) => Math.max(m, w.z), 0);
let counter = 0;
export const titleOf = (w: WindowRec) => TITLES[w.kind];

export const useWindows = create<WinStore>((set, get) => ({
  windows: [],
  viewport: { w: 1280, h: 800 },
  setViewport: (viewport) => set((s) => ({ viewport, windows: s.windows.map((w) => (w.state === 'normal' ? { ...w, ...clampRect(w, viewport) } : w)) })),
  open: (kind) => {
    const s = get();
    const existing = s.windows.find((w) => w.kind === kind);   // one window per kind: focus instead of duplicating
    if (existing) { get().restore(existing.id); get().focus(existing.id); return existing.id; }
    if (s.windows.length >= MAX_WINDOWS) return null;
    const id = `${kind}-${Date.now().toString(36)}-${counter++}`;
    set({ windows: [...s.windows, { id, kind, ...place(s.windows, s.viewport), z: topZ(s.windows) + 1, state: 'normal' }] });
    return id;
  },
  close: (id) => set((s) => ({ windows: s.windows.filter((w) => w.id !== id) })),
  closeAll: () => set({ windows: [] }),
  focus: (id) => set((s) => (s.windows.find((w) => w.id === id)?.z === topZ(s.windows) ? s : { windows: s.windows.map((w) => (w.id === id ? { ...w, z: topZ(s.windows) + 1 } : w)) })),
  minimize: (id) => set((s) => ({ windows: s.windows.map((w) => (w.id === id ? { ...w, state: 'minimized' } : w)) })),
  minimizeAll: () => set((s) => ({ windows: s.windows.map((w) => ({ ...w, state: 'minimized' as const })) })),
  restore: (id) => set((s) => ({ windows: s.windows.map((w) => (w.id === id ? { ...w, state: 'normal', z: topZ(s.windows) + 1, ...clampRect(w, s.viewport) } : w)) })),
  toggleMaximize: (id) => set((s) => ({ windows: s.windows.map((w) => (w.id === id ? { ...w, state: w.state === 'maximized' ? 'normal' : 'maximized', z: topZ(s.windows) + 1 } : w)) })),
  move: (id, x, y) => set((s) => ({ windows: s.windows.map((w) => (w.id === id ? { ...w, ...clampRect(snap({ x, y, w: w.w, h: w.h }, s.viewport), s.viewport) } : w)) })),
  resize: (id, x, y, w, h) => set((s) => ({ windows: s.windows.map((r) => (r.id === id ? { ...r, ...clampRect({ x, y, w: Math.max(MIN_W, w), h: Math.max(MIN_H, h) }, s.viewport) } : r)) })),
  tileAll: () => set((s) => ({ windows: tile(s.windows, s.viewport) })),
  apply: (layout) => set((s) => ({ windows: layout.windows.map((w) => ({ ...w, ...(w.state === 'maximized' ? {} : clampRect(w, s.viewport)) })) })),
  snapshot: (page) => ({ windows: get().windows.map((w) => ({ ...w })), page }),
}));
