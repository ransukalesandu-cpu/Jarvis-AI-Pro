import type { Page } from '../store';

export const WINDOW_KINDS = ['monitor', 'models', 'activity', 'log'] as const;
export type WinKind = (typeof WINDOW_KINDS)[number];
export const WINDOW_STATES = ['normal', 'minimized', 'maximized'] as const;
export type WinState = (typeof WINDOW_STATES)[number];
export const PAGE_IDS: Page[] = ['home', 'chat', 'activity', 'models', 'research', 'reminders', 'apps', 'files', 'memory', 'automation', 'monitor', 'security'];

export interface WindowRec { id: string; kind: WinKind; x: number; y: number; w: number; h: number; z: number; state: WinState }
export interface Layout { windows: WindowRec[]; page: Page }

export const MIN_W = 280;
export const MIN_H = 180;
export const MAX_WINDOWS = 12;
export const TOP = 64;      // below the top bar
export const MARGIN = 16;
export const TITLES: Record<WinKind, string> = { monitor: 'System Monitor', models: 'AI Models', activity: 'Activity Center', log: 'Conversation Log' };

const isNum = (v: unknown, lo: number, hi: number): v is number => typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi;

/** Mirror of jarvis/webui/workspace_store.validate_layout: a bad or outdated layout is dropped, never applied. */
export function validateLayout(l: unknown): Layout | null {
  if (l === null || typeof l !== 'object' || Array.isArray(l)) return null;
  const o = l as Record<string, unknown>;
  if (Object.keys(o).some((k) => k !== 'windows' && k !== 'page')) return null;
  const page = (o.page ?? 'home') as Page;
  if (!PAGE_IDS.includes(page) || !Array.isArray(o.windows) || o.windows.length > MAX_WINDOWS) return null;
  const seen = new Set<string>();
  const windows: WindowRec[] = [];
  for (const w of o.windows as Record<string, unknown>[]) {
    if (w === null || typeof w !== 'object') return null;
    if (typeof w.id !== 'string' || w.id.length === 0 || w.id.length > 40 || seen.has(w.id)) return null;
    if (!(WINDOW_KINDS as readonly unknown[]).includes(w.kind) || !(WINDOW_STATES as readonly unknown[]).includes(w.state)) return null;
    if (!isNum(w.x, -4000, 8000) || !isNum(w.y, -4000, 8000) || !isNum(w.w, 200, 8000) || !isNum(w.h, 120, 8000) || !isNum(w.z, 0, 100000)) return null;
    seen.add(w.id);
    windows.push({ id: w.id, kind: w.kind as WinKind, x: w.x, y: w.y, w: w.w, h: w.h, z: Math.round(w.z), state: w.state as WinState });
  }
  return { windows, page };
}

export interface Viewport { w: number; h: number }
const rect = (r: Pick<WindowRec, 'x' | 'y' | 'w' | 'h'>) => ({ l: r.x, t: r.y, r: r.x + r.w, b: r.y + r.h });
const overlaps = (a: Pick<WindowRec, 'x' | 'y' | 'w' | 'h'>, b: Pick<WindowRec, 'x' | 'y' | 'w' | 'h'>) => {
  const p = rect(a), q = rect(b);
  return p.l < q.r && p.r > q.l && p.t < q.b && p.b > q.t;
};

/** Keep a window fully reachable inside the viewport and above the minimum size. */
export function clampRect(r: Pick<WindowRec, 'x' | 'y' | 'w' | 'h'>, vp: Viewport) {
  const w = Math.max(MIN_W, Math.min(r.w, vp.w - 2 * MARGIN));
  const h = Math.max(MIN_H, Math.min(r.h, vp.h - TOP - MARGIN));
  const x = Math.max(MARGIN, Math.min(r.x, vp.w - w - MARGIN));
  const y = Math.max(TOP, Math.min(r.y, vp.h - h - MARGIN));
  return { x, y, w, h };
}

/** The central band where the hologram lives. New windows are placed in the side gutters first. */
export function hologramZone(vp: Viewport) { return { x: vp.w * 0.32, y: TOP, w: vp.w * 0.36, h: vp.h - TOP } ; }

/** Intelligent placement: left gutter, then right gutter, stacked; only then cascade. Never over the hologram when avoidable. */
export function place(existing: WindowRec[], vp: Viewport): { x: number; y: number; w: number; h: number } {
  const w = Math.min(340, Math.max(MIN_W, vp.w * 0.26)), h = Math.min(320, Math.max(MIN_H, (vp.h - TOP - MARGIN) / 2 - MARGIN / 2));
  const visible = existing.filter((e) => e.state === 'normal');
  const slots: { x: number; y: number; w: number; h: number }[] = [];
  for (const x of [MARGIN, vp.w - w - MARGIN]) for (let y = TOP; y + h <= vp.h - MARGIN + 1; y += h + MARGIN) slots.push({ x, y, w, h });
  const zone = hologramZone(vp);
  const free = slots.find((s) => !visible.some((e) => overlaps(s, e)) && !overlaps(s, zone));
  if (free) return free;
  const n = visible.length;
  return clampRect({ x: MARGIN + 28 * (n % 6), y: TOP + 28 * (n % 6), w, h }, vp);
}

/** Arrange all non-minimised windows in the two side gutters. */
export function tile(windows: WindowRec[], vp: Viewport): WindowRec[] {
  const w = Math.min(340, Math.max(MIN_W, vp.w * 0.26));
  const list = windows.filter((x) => x.state !== 'minimized').sort((a, b) => a.z - b.z);
  const perCol = Math.max(1, Math.ceil(list.length / 2));
  const h = Math.max(MIN_H, Math.min(360, (vp.h - TOP - MARGIN - (perCol - 1) * MARGIN) / perCol));
  const out = new Map<string, WindowRec>();
  list.forEach((win, i) => {
    const col = i < perCol ? 0 : 1, row = col === 0 ? i : i - perCol;
    out.set(win.id, { ...win, state: 'normal', ...clampRect({ x: col === 0 ? MARGIN : vp.w - w - MARGIN, y: TOP + row * (h + MARGIN), w, h }, vp) });
  });
  return windows.map((x) => out.get(x.id) ?? x);
}

/** Snap to the viewport edges when released within 24 px of them. */
export function snap(r: { x: number; y: number; w: number; h: number }, vp: Viewport) {
  let { x, y } = r;
  if (x < MARGIN + 24) x = MARGIN;
  if (x + r.w > vp.w - MARGIN - 24) x = vp.w - r.w - MARGIN;
  if (y < TOP + 24) y = TOP;
  return { ...r, x, y };
}
