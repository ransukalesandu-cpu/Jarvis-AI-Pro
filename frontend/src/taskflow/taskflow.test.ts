import { beforeEach, describe, expect, it } from 'vitest';
import { parseFlow, parseHostEvent, type Flow } from '../bridge/contract';
import { autoLayout, bounds, fitView, STEP_H, STEP_W, wire } from './layout';
import { diffLog, MAX_FLOWS, upsertFlow, useFlows, windowFlow } from './flows';

const step = (id: string, status: Flow['steps'][number]['status'], detail = '') => ({
    id,
    tool: `tool_${id}`,
    label: `Step ${id}`,
    status,
    detail,
    startedAt: status === 'pending' ? null : 1000,
    finishedAt: null,
});
const flow = (id: string, startedAt: number, steps: Flow['steps'] = [], state: Flow['state'] = 'running'): Flow => ({
    id,
    title: `Task ${id}`,
    source: 'command',
    state,
    startedAt,
    finishedAt: null,
    steps,
});
const ev = (f: Flow) => JSON.stringify({ type: 'task.flow', flow: f });

describe('contract', () => {
    it('accepts a valid flow and rejects anything outside the closed sets', () => {
        const f = flow('f1', 1000, [step('s1', 'running')]);
        expect(parseHostEvent(ev(f))).toEqual({ type: 'task.flow', flow: f });
        expect(parseFlow({ ...f, state: 'boom' })).toBeNull();
        expect(parseFlow({ ...f, source: 'page' })).toBeNull();
        expect(parseFlow({ ...f, extra: 1 })).toBeNull();
        expect(parseFlow({ ...f, title: '' })).toBeNull();
        expect(parseFlow({ ...f, steps: [{ ...step('s1', 'done'), status: 'weird' }] })).toBeNull();
        expect(parseFlow({ ...f, steps: [{ ...step('s1', 'done'), detail: 'x'.repeat(101) }] })).toBeNull();
        expect(parseFlow({ ...f, steps: Array.from({ length: 25 }, (_, i) => step(`s${i}`, 'pending')) })).toBeNull();
        expect(parseHostEvent(JSON.stringify({ type: 'ui.task_flow', view: 'page' }))).toEqual({ type: 'ui.task_flow', view: 'page' });
        expect(parseHostEvent(JSON.stringify({ type: 'ui.task_flow', view: 'nuke' }))).toBeNull();
    });
});

describe('flows', () => {
    it('upserts by id, keeps start order and a bounded history', () => {
        let list: Flow[] = [];
        list = upsertFlow(list, flow('b', 2000));
        list = upsertFlow(list, flow('a', 1000));
        list = upsertFlow(list, { ...flow('b', 2000), state: 'done' });
        expect(list.map((f) => `${f.id}:${f.state}`)).toEqual(['a:running', 'b:done']);
        for (let i = 0; i < MAX_FLOWS + 5; i++) list = upsertFlow(list, flow(`x${i}`, 5000 + i));
        expect(list).toHaveLength(MAX_FLOWS);
    });

    it('turns snapshot changes into activity lines', () => {
        const a = flow('f', 0, [step('s1', 'running'), step('s2', 'pending')]);
        expect(diffLog(undefined, a, 5).map((l) => l.text)).toEqual(['command received', 'tool_s1 started']);
        const b = { ...a, steps: [step('s1', 'done', '3 files'), step('s2', 'error', 'offline')] };
        expect(diffLog(a, b, 6).map((l) => [l.text, l.level])).toEqual([
            ['tool_s1 ✓ — 3 files', 'ok'],
            ['tool_s2 ✗ — offline', 'err'],
        ]);
        const c = { ...b, state: 'done' as const };
        expect(diffLog(b, c, 7).map((l) => l.text)).toEqual(['all steps finished']);
        expect(diffLog(c, c, 8)).toEqual([]);
    });
});

describe('window behaviour', () => {
    beforeEach(() =>
        useFlows.setState({ flows: [], logs: {}, win: { open: false, pinned: false, flowId: null }, selected: null, autoShow: true, pageRequested: 0 }),
    );
    const apply = (raw: string, now = 10_000) => useFlows.getState().apply(parseHostEvent(raw)!, now);

    it('a new running task pops the window up unpinned (so it hides itself)', () => {
        apply(ev(flow('f1', 9_000)));
        expect(useFlows.getState().win).toEqual({ open: true, pinned: false, flowId: 'f1' });
        apply(ev({ ...flow('f1', 9_000), state: 'done' })); // an update does not re-open or re-pin
        useFlows.getState().hideWindow();
        apply(ev({ ...flow('f1', 9_000), state: 'done' }));
        expect(useFlows.getState().win.open).toBe(false);
    });

    it('old replayed flows and the auto-show switch do not pop it up', () => {
        apply(ev(flow('old', 1_000)), 200_000);
        expect(useFlows.getState().win.open).toBe(false);
        useFlows.setState({ autoShow: false });
        apply(ev(flow('f2', 9_000)));
        expect(useFlows.getState().win.open).toBe(false);
    });

    it('voice view requests: window stays pinned, page is requested, hide closes', () => {
        apply(ev(flow('f1', 9_000)));
        apply(JSON.stringify({ type: 'ui.task_flow', view: 'window' }));
        expect(useFlows.getState().win).toMatchObject({ open: true, pinned: true, flowId: 'f1' });
        apply(JSON.stringify({ type: 'ui.task_flow', view: 'hide' }));
        expect(useFlows.getState().win.open).toBe(false);
        apply(JSON.stringify({ type: 'ui.task_flow', view: 'page' }));
        expect(useFlows.getState().pageRequested).toBe(1);
    });

    it('a pinned window keeps showing the flow it was pinned to; windowFlow falls back to the newest', () => {
        apply(ev(flow('f1', 9_000)));
        useFlows.getState().showWindow(true, 'f1');
        apply(ev(flow('f2', 9_500)));
        expect(useFlows.getState().win).toMatchObject({ pinned: true });
        expect(windowFlow(useFlows.getState())?.id).toBe('f2');
        useFlows.setState({ win: { open: true, pinned: true, flowId: 'gone' } });
        expect(windowFlow(useFlows.getState())?.id).toBe('f2');
    });
});

describe('layout', () => {
    it('fans steps out without overlap and wires start at the brain and end at each step', () => {
        const { brain, steps } = autoLayout(6);
        for (let i = 1; i < steps.length; i++) expect(steps[i].y - steps[i - 1].y).toBeGreaterThanOrEqual(STEP_H);
        const w = wire(brain, steps[2], 2, 6);
        expect(w.x2).toBe(steps[2].x);
        expect(w.d.startsWith('M248,')).toBe(true);
    });

    it('fits the whole graph on the page and keeps a readable zoom in the small window', () => {
        const { brain, steps } = autoLayout(8);
        const b = bounds(brain, steps);
        const whole = fitView(b, 900, 520, true, null);
        expect((b.x1 - b.x0) * whole.s).toBeLessThanOrEqual(900);
        expect((b.y1 - b.y0) * whole.s).toBeLessThanOrEqual(520);
        const small = fitView(b, 500, 300, false, steps[7].y + STEP_H / 2);
        expect(small.s).toBeGreaterThanOrEqual(0.3);
        expect(small.s).toBeLessThanOrEqual(0.82);
        expect(b.x1 * small.s + small.x).toBeLessThanOrEqual(500); // width always fits
        expect(STEP_W).toBeGreaterThan(0);
    });
});
