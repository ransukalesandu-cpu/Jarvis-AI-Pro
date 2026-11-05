import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ControlsView } from './Controls';

const v = (o: Partial<Parameters<typeof ControlsView>[0]> = {}) =>
  renderToStaticMarkup(<ControlsView muted={false} busy linked result={null} onDo={() => {}} {...o} />);

describe('ControlsView', () => {
  it('offers mute when not muted and unmute when muted', () => {
    expect(v()).toContain('Mute microphone');
    expect(v({ muted: true })).toContain('Unmute microphone');
    expect(v({ muted: true })).toContain('aria-pressed="true"');
  });
  it('interrupt is only enabled while JARVIS is busy', () => {
    expect(v({ busy: false })).toMatch(/<button disabled=""[^>]*aria-label="Interrupt JARVIS"/);
    expect(v({ busy: true })).not.toMatch(/<button disabled=""[^>]*aria-label="Interrupt JARVIS"/);
  });
  it('everything is disabled until the backend link is up', () => {
    expect((v({ linked: false }).match(/disabled=""/g) ?? []).length).toBe(3);
  });
  it('explains a refusal, and stays quiet on success', () => {
    expect(v({ result: 'guest' })).toContain('Guest mode');
    expect(v({ result: 'done' })).not.toContain('Done');
  });
});
