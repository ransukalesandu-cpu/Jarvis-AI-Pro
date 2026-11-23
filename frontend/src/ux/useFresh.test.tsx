import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useFresh } from './useFresh';

function Probe({ v, k }: { v: string | null; k: number }) {
    return <span>{useFresh(v, k, 1000) ?? '-'}</span>;
}
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

describe('useFresh', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());
    it('shows a note, clears it after the timeout, and shows the same note again for a new result', () => {
        const el = document.createElement('div');
        const root = createRoot(el);
        act(() => root.render(<Probe v="Too fast" k={1} />));
        expect(el.textContent).toBe('Too fast');
        act(() => {
            vi.advanceTimersByTime(1100);
        });
        expect(el.textContent).toBe('-');
        act(() => root.render(<Probe v="Too fast" k={2} />));
        expect(el.textContent).toBe('Too fast');
        act(() => root.unmount());
    });
});
