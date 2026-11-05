import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { CommandBarView } from './CommandBar';

const view = (o: Partial<Parameters<typeof CommandBarView>[0]> = {}) =>
  renderToStaticMarkup(<CommandBarView state="ok" last={null} linked text="" onText={() => {}} onSubmit={() => {}} {...o} />);

describe('CommandBarView', () => {
  it('is enabled when the host says ok', () => expect(view()).not.toMatch(/<input[^>]*disabled/));
  it.each(['locked', 'auth_required', 'silent', 'guest', 'unavailable'] as const)('is disabled and explains why when %s', (state) => {
    const h = view({ state });
    expect(h).toMatch(/<input[^>]*disabled/);
    expect(h).toContain('cmdbar-note');
    expect(h).not.toContain('></span>');            // the note is never empty when blocked
  });
  it('is disabled until the backend link is up', () => expect(view({ linked: false })).toMatch(/<input[^>]*disabled/));
  it('shows the last result', () => expect(view({ last: 'credential' })).toContain('looks like a credential'));
  it('never reads like a password box', () => {
    const h = view();
    expect(h).not.toContain('type="password"');
    expect(h).toContain('autoComplete="off"');
  });
});
