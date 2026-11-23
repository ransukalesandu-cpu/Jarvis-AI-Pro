// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { parseHostEvent } from '../bridge/contract';
import { useUi } from '../store';
import { ACCESS_LABEL, SECTIONS, SettingsPanel, memoryRows, netText } from './Settings';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root | null = null;
beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
});
afterEach(async () => {
    // Unmount first and let pending Radix/Motion timers run while the DOM still exists.
    act(() => root?.unmount());
    root = null;
    await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
    });
    host.remove();
    act(() => useUi.setState({ settingsOpen: false, link: 'detached', memory: null, provider: null }));
});

describe('memory.status contract', () => {
    it('accepts only the closed shape', () => {
        const ok = { type: 'memory.status', cloud: 'configured', personal: true, encrypted: false };
        expect(parseHostEvent(JSON.stringify(ok))).toEqual(ok);
        expect(parseHostEvent(JSON.stringify({ ...ok, cloud: 'https://x.supabase.co' }))).toBeNull();
        expect(parseHostEvent(JSON.stringify({ ...ok, personal: 'yes' }))).toBeNull();
    });
    it('lands in the store', () => {
        useUi.getState().apply({ type: 'memory.status', cloud: 'not_configured', personal: false, encrypted: true });
        expect(useUi.getState().memory).toEqual({ cloud: 'not_configured', personal: false, encrypted: true });
    });
});

describe('Control Center helpers', () => {
    it('has every section the spec asks for', () => {
        expect(SECTIONS).toEqual(['general', 'ai', 'voice', 'security', 'memory', 'performance', 'devices']);
    });
    it('says "not reported" instead of guessing memory state', () => {
        expect(memoryRows(null)).toEqual([['Memory status', 'not reported yet']]);
        expect(memoryRows({ cloud: 'configured', personal: false, encrypted: true })).toEqual([
            ['Supabase cloud', 'configured'],
            ['Personal cloud memory', 'off'],
            ['Local memory encryption', 'on'],
        ]);
    });
    it('labels every access state and formats network honestly', () => {
        expect(ACCESS_LABEL.guest).toContain('Guest');
        expect(ACCESS_LABEL.unavailable).toBe('Not reported yet');
        expect(netText(null)).toBe('no data');
        expect(netText({ downKBps: 12.4, upKBps: 3.6 })).toBe('↓ 12 KB/s · ↑ 4 KB/s');
    });
});

describe('SettingsPanel', () => {
    function open() {
        act(() => useUi.setState({ settingsOpen: true }));
        root = createRoot(host);
        act(() => root!.render(<SettingsPanel />));
    }
    const tab = (name: string) => [...host.querySelectorAll<HTMLButtonElement>('[role=tab]')].find((b) => b.textContent === name)!;
    // Radix tabs select on mousedown (a real click starts with one) and on focus.
    const pick = (name: string) => act(() => tab(name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 })));
    const panel = () => host.querySelector('[role=tabpanel]:not([hidden])')!;

    it('switches sections with the keyboard (arrows wrap)', async () => {
        open();
        expect(tab('General').getAttribute('aria-selected')).toBe('true');
        tab('General').focus();
        // Roving focus moves on the next tick; focusing a tab selects it.
        await act(async () => {
            tab('General').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
            await new Promise((r) => setTimeout(r, 0));
        });
        expect(tab('Devices').getAttribute('aria-selected')).toBe('true');
        expect(document.activeElement).toBe(tab('Devices'));
    });
    it('shows real provider and memory values, and nothing invented when offline', () => {
        open();
        pick('AI');
        expect(host.textContent).toContain('not reported');
        act(() =>
            useUi.setState({
                link: 'connected',
                provider: { provider: 'Gemini', model: 'gemini-live', connected: true, fallback: false },
                memory: { cloud: 'configured', personal: true, encrypted: false },
            }),
        );
        expect(host.textContent).toContain('Gemini');
        expect(host.textContent).toContain('connected');
        pick('Memory');
        expect(host.textContent).toContain('on (opt-in)');
        act(() => useUi.setState({ link: 'detached' }));
        expect(host.textContent).toContain('not reported yet');
    });
    it('does not claim the microphone is on while the backend is offline', () => {
        open();
        pick('Voice');
        const mic = panel().querySelector<HTMLButtonElement>('.row button')!;
        expect(mic.textContent).toBe('Unknown');
        expect(mic.disabled).toBe(true);
        act(() => useUi.setState({ link: 'connected', muted: true }));
        expect(mic.textContent).toBe('Muted');
    });
    it('shows security as status only, with no control that changes access', () => {
        open();
        act(() => useUi.setState({ link: 'connected', command: { state: 'guest', last: null } }));
        pick('Security');
        expect(panel().textContent).toContain('Guest mode (limited)');
        expect(panel().querySelectorAll('button').length).toBe(0);
    });
});
