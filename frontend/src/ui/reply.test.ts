import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { latestExchange, ReplyPanelView } from './Reply';

const L = (id: number, tag: string, text: string) => ({ id, tag, text });

describe('latestExchange', () => {
  it('is null until JARVIS has said something', () => {
    expect(latestExchange([])).toBeNull();
    expect(latestExchange([L(1, 'you', 'hi'), L(2, 'sys', 'SYS: x')])).toBeNull();
  });
  it('pairs the last thing you said with the answer, joining consecutive JARVIS lines', () => {
    const ex = latestExchange([L(1, 'you', 'old'), L(2, 'ai', 'old answer'), L(3, 'you', 'weather?'), L(4, 'ai', 'Sunny.'), L(5, 'ai', 'About 30 C.'), L(6, 'sys', 'SYS: tick')]);
    expect(ex).toEqual({ id: 5, you: 'weather?', reply: 'Sunny.\nAbout 30 C.' });
  });
  it('bounds how many lines are joined', () => {
    const lines = Array.from({ length: 20 }, (_, i) => L(i + 1, 'ai', `l${i}`));
    expect(latestExchange(lines)!.reply.split('\n')).toHaveLength(6);
  });
});

describe('ReplyPanelView', () => {
  it('renders nothing without a reply and escapes text when there is one', () => {
    expect(renderToStaticMarkup(createElement(ReplyPanelView, { ex: null, onClose: () => {} }))).toBe('');
    const html = renderToStaticMarkup(createElement(ReplyPanelView, { ex: { id: 1, you: null, reply: '<img src=x onerror=1>' }, onClose: () => {} }));
    expect(html).not.toContain('<img'); expect(html).toContain('&lt;img');
  });
});
