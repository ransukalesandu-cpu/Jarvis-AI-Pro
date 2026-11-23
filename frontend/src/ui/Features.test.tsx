import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { parseHostEvent, FEATURES } from '../bridge/contract';
import { askText, FeaturesView, SPECS } from './Features';

const j = (o: unknown) => JSON.stringify(o);
const v = (o: Partial<Parameters<typeof FeaturesView>[0]> = {}) =>
    renderToStaticMarkup(
        <FeaturesView tab="knowledge" onTab={() => {}} snap={undefined} canAsk result={null} onSubmit={() => {}} onRefresh={() => {}} {...o} />,
    );

describe('feature.snapshot contract', () => {
    it('accepts bounded snapshots for known features', () => {
        const e = parseHostEvent(j({ type: 'feature.snapshot', feature: 'notes', summary: '2 notes', items: [{ title: 'Ideas', detail: '' }] }));
        expect(e).toEqual({ type: 'feature.snapshot', feature: 'notes', summary: '2 notes', items: [{ title: 'Ideas', detail: '' }] });
    });
    it('rejects unknown features, extra keys and oversize data', () => {
        expect(parseHostEvent(j({ type: 'feature.snapshot', feature: 'shell', summary: 'x', items: [] }))).toBeNull();
        expect(parseHostEvent(j({ type: 'feature.snapshot', feature: 'notes', summary: 'x', items: [{ title: 'a', detail: '', path: '/x' }] }))).toBeNull();
        expect(parseHostEvent(j({ type: 'feature.snapshot', feature: 'notes', summary: 'x', items: Array(31).fill({ title: 'a', detail: '' }) }))).toBeNull();
        expect(parseHostEvent(j({ type: 'feature.snapshot', feature: 'notes', summary: 'x'.repeat(201), items: [] }))).toBeNull();
        expect(parseHostEvent(j({ type: 'feature.snapshot', feature: 'notes', summary: 'x', items: [{ title: 'a'.repeat(121), detail: '' }] }))).toBeNull();
    });
});

describe('FeaturesView', () => {
    it('has a tab and a spec for every feature', () => {
        const html = v();
        for (const f of FEATURES) expect(html).toContain(SPECS[f].label);
    });
    it('shows the snapshot summary and items', () => {
        const html = v({ snap: { summary: '1 knowledge base', items: [{ title: 'work (active)', detail: '3 sources' }], at: 1 } });
        expect(html).toContain('1 knowledge base');
        expect(html).toContain('work (active)');
        expect(html).toContain('3 sources');
    });
    it('disables actions while commands are not allowed and explains refusals', () => {
        const html = v({ canAsk: false, result: 'guest' });
        expect((html.match(/disabled=""/g) ?? []).length).toBeGreaterThanOrEqual(SPECS.knowledge.actions.length + 1);
        expect(html).toContain('Guest');
    });
    it('builds bounded command text for the ask box', () => {
        expect(askText(SPECS.knowledge, '  payment terms ')).toBe('Using my knowledge base, answer: payment terms');
        expect(askText(SPECS.knowledge, '   ')).toBe('');
        expect(askText(SPECS.providers, 'x')).toBe('');
        expect(askText(SPECS.notes, 'y'.repeat(900)).length).toBeLessThanOrEqual(500);
    });
});
