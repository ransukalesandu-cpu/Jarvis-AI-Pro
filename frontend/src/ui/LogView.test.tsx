import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { LogView } from './Pages';

describe('LogView', () => {
  it('is empty-state honest', () => {
    const h = renderToStaticMarkup(<LogView lines={[]} onClear={() => {}} />);
    expect(h).toContain('No messages yet');
    expect(h).toContain('role="log"');
  });
  it('renders text as text (no HTML injection) and is read-only', () => {
    const h = renderToStaticMarkup(<LogView lines={[{ id: 1, at: 0, tag: 'ai', text: '<img src=x onerror=alert(1)>' }]} onClear={() => {}} />);
    expect(h).not.toContain('<img');
    expect(h).toContain('&lt;img');
    expect(h).not.toContain('<input');
    expect(h).not.toContain('<textarea');
  });
});
