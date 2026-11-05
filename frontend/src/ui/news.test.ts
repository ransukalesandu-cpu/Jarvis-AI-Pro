import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { parseHostEvent } from '../bridge/contract';
import { NewsView } from './News';

const j = (o: unknown) => JSON.stringify(o);
const noop = () => {};

describe('news.items', () => {
  it('accepts titles and sources only, bounded', () => {
    expect(parseHostEvent(j({ type: 'news.items', heading: 'H', items: [{ title: 'A', source: 'S', link: true }] }))?.type).toBe('news.items');
    expect(parseHostEvent(j({ type: 'news.items', heading: 'H', items: [{ title: '', source: 'S', link: true }] }))).toBeNull();
    expect(parseHostEvent(j({ type: 'news.items', heading: 'H', items: [{ title: 'A', source: 'S', link: 'yes' }] }))).toBeNull();
    expect(parseHostEvent(j({ type: 'news.items', heading: 'H', items: Array(21).fill({ title: 'A', source: '', link: false }) }))).toBeNull();
  });
});

describe('NewsView', () => {
  it('says so when there is nothing, never invents headlines', () => {
    const h = renderToStaticMarkup(createElement(NewsView, { heading: null, items: [], linked: true, result: null, onOpen: noop }));
    expect(h).toContain('No headlines yet'); expect(h).not.toContain('<li');
  });
  it('shows items, escapes text, and only offers Open for items with a link', () => {
    const h = renderToStaticMarkup(createElement(NewsView, { heading: 'HEADLINES', linked: true, result: 'locked', onOpen: noop,
      items: [{ title: '<b>x</b>', source: 'S', link: true }, { title: 'No link', source: '', link: false }] }));
    expect(h).toContain('&lt;b&gt;x'); expect(h.match(/Open article/g)).toHaveLength(1); expect(h).toContain('locked');
  });
});
