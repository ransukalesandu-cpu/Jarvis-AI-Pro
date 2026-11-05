import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { BentoView } from './Bento';

const base = { assistant: 'idle', persona: 'jarvis', perfTier: null, muted: false, provider: null, cpu: [], ram: [], down: [], up: [], disk: null, battery: '--' };

describe('BentoView', () => {
  it('shows "not reported" and no data instead of inventing values', () => {
    const h = renderToStaticMarkup(createElement(BentoView, base));
    expect(h).toContain('not reported'); expect(h).toContain('collecting'); expect(h).not.toContain('NaN');
  });
  it('shows what it is given', () => {
    const h = renderToStaticMarkup(createElement(BentoView, { ...base, perfTier: 'lite', persona: 'bihansa', muted: true, cpu: [10, 20], provider: { provider: 'gemini', model: 'm1', connected: true, fallback: false } }));
    expect(h).toContain('lite'); expect(h).toContain('bihansa'); expect(h).toContain('muted'); expect(h).toContain('gemini'); expect(h).toContain('configured');
  });
});
