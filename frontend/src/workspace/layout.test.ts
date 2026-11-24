import { describe, expect, it } from 'vitest';
import { gutterCovered } from './layout';

describe('gutterCovered', () => {
    const vp = { w: 1280, h: 800 };
    const win = (x: number, state: 'normal' | 'minimized' | 'maximized' = 'normal') => ({
        id: 'a',
        kind: 'log' as const,
        x,
        y: 64,
        w: 340,
        h: 300,
        z: 1,
        state,
    });
    it('a window over a widget column hides that column only', () => {
        expect(gutterCovered([win(16)], vp, 'left')).toBe(true);
        expect(gutterCovered([win(16)], vp, 'right')).toBe(false);
        expect(gutterCovered([win(1280 - 356)], vp, 'right')).toBe(true);
        expect(gutterCovered([win(470)], vp, 'left')).toBe(false);
        expect(gutterCovered([win(16, 'minimized')], vp, 'left')).toBe(false);
        expect(gutterCovered([win(470, 'maximized')], vp, 'right')).toBe(true);
    });
});
