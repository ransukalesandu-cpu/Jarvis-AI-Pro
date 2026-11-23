import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';
import { Spark } from './Spark';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const render = (el: React.ReactElement) => {
    const host = document.createElement('div');
    act(() => createRoot(host).render(el));
    return host;
};

describe('Spark', () => {
    it('draws no chart and says so without data', () => {
        const h = render(<Spark label="CPU" data={[]} unit="%" max={100} />);
        expect(h.querySelector('.recharts-wrapper')).toBeNull();
        expect(h.textContent).toContain('no samples yet');
    });
    it('draws a chart hidden from assistive tech, with the numbers as text', () => {
        const h = render(<Spark label="CPU" data={[10, 50, 30]} unit="%" max={100} />);
        expect(h.querySelector('.recharts-area')).not.toBeNull();
        expect(h.querySelector('.ui-chart')?.getAttribute('aria-hidden')).toBe('true');
        expect(h.querySelector('[tabindex]')).toBeNull();
        expect(h.textContent).toContain('now 30%, min 10, max 50');
    });
});
