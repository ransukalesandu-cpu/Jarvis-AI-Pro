import { beforeEach, describe, expect, it } from 'vitest';
import { clampRect, hologramZone, MIN_H, MIN_W, place, snap, tile, validateLayout, type WindowRec } from './layout';
import { useWindows } from './windows';

const VP = { w: 1280, h: 800 };
const rec = (o: Partial<WindowRec> = {}): WindowRec => ({ id: 'a', kind: 'monitor', x: 20, y: 80, w: 320, h: 300, z: 1, state: 'normal', ...o });
const hit = (a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }) =>
  a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;

describe('validateLayout', () => {
  it('accepts a good layout', () => expect(validateLayout({ windows: [rec()], page: 'home' })).not.toBeNull());
  it('rejects unknown keys, kinds, states and page ids', () => {
    expect(validateLayout({ windows: [], page: 'home', extra: 1 })).toBeNull();
    expect(validateLayout({ windows: [rec({ kind: 'evil' as never })], page: 'home' })).toBeNull();
    expect(validateLayout({ windows: [rec({ state: 'gone' as never })], page: 'home' })).toBeNull();
    expect(validateLayout({ windows: [], page: 'nope' })).toBeNull();
  });
  it('rejects NaN, huge numbers and duplicate ids', () => {
    expect(validateLayout({ windows: [rec({ x: NaN })], page: 'home' })).toBeNull();
    expect(validateLayout({ windows: [rec({ w: 1e9 })], page: 'home' })).toBeNull();
    expect(validateLayout({ windows: [rec(), rec()], page: 'home' })).toBeNull();
  });
  it('rejects non-objects', () => {
    for (const v of [null, 4, 'x', [], undefined]) expect(validateLayout(v)).toBeNull();
  });
});

describe('geometry', () => {
  it('clamps into the viewport and enforces minimum size', () => {
    const r = clampRect({ x: -500, y: -500, w: 10, h: 10 }, VP);
    expect(r.w).toBe(MIN_W); expect(r.h).toBe(MIN_H); expect(r.x).toBeGreaterThanOrEqual(0); expect(r.y).toBeGreaterThanOrEqual(0);
    const big = clampRect({ x: 5000, y: 5000, w: 9000, h: 9000 }, VP);
    expect(big.x + big.w).toBeLessThanOrEqual(VP.w); expect(big.y + big.h).toBeLessThanOrEqual(VP.h);
  });
  it('places new windows beside, not over, the hologram', () => {
    const zone = hologramZone(VP);
    const existing: WindowRec[] = [];
    for (let i = 0; i < 4; i++) {
      const p = place(existing, VP);
      expect(hit(p, zone)).toBe(false);
      existing.push(rec({ id: `w${i}`, ...p }));
    }
  });
  it('tiles into side gutters without overlap', () => {
    const t = tile([rec({ id: 'a', z: 1 }), rec({ id: 'b', z: 2 }), rec({ id: 'c', z: 3 })], VP);
    for (let i = 0; i < t.length; i++) for (let j = i + 1; j < t.length; j++) expect(hit(t[i], t[j])).toBe(false);
  });
  it('snaps near edges only', () => {
    expect(snap({ x: 20, y: 70, w: 300, h: 200 }, VP)).toMatchObject({ x: 16, y: 64 });
    expect(snap({ x: 400, y: 300, w: 300, h: 200 }, VP)).toMatchObject({ x: 400, y: 300 });
  });
});

describe('window store', () => {
  beforeEach(() => useWindows.setState({ windows: [], viewport: VP }));
  it('opens one window per kind and focuses it again', () => {
    const a = useWindows.getState().open('monitor');
    const b = useWindows.getState().open('monitor');
    expect(a).toBe(b); expect(useWindows.getState().windows).toHaveLength(1);
  });
  it('focus raises z, minimise/restore round-trips, close removes', () => {
    const s = useWindows.getState();
    const a = s.open('monitor')!, b = s.open('models')!;
    s.focus(a);
    const z = (id: string) => useWindows.getState().windows.find((w) => w.id === id)!.z;
    expect(z(a)).toBeGreaterThan(z(b));
    s.minimize(a); expect(useWindows.getState().windows.find((w) => w.id === a)!.state).toBe('minimized');
    s.restore(a); expect(useWindows.getState().windows.find((w) => w.id === a)!.state).toBe('normal');
    s.close(a); expect(useWindows.getState().windows.map((w) => w.id)).toEqual([b]);
  });
  it('snapshot output passes validation and apply restores it', () => {
    const s = useWindows.getState();
    s.open('monitor'); s.open('activity');
    const snap1 = validateLayout(useWindows.getState().snapshot('home'));
    expect(snap1).not.toBeNull();
    s.closeAll(); s.apply(snap1!);
    expect(useWindows.getState().windows).toHaveLength(2);
  });
  it('keeps windows inside the viewport when it shrinks', () => {
    useWindows.getState().open('monitor');
    useWindows.getState().setViewport({ w: 700, h: 500 });
    const w = useWindows.getState().windows[0];
    expect(w.x + w.w).toBeLessThanOrEqual(700); expect(w.y + w.h).toBeLessThanOrEqual(500);
  });
});
