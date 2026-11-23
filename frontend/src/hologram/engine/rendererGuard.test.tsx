// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RendererGuard } from './RendererGuard';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement | null = null;
function mount(node: React.ReactNode) {
  host = document.createElement('div'); document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(node));
  return { root, el: host };
}
afterEach(() => { host?.remove(); host = null; });

describe('RendererGuard', () => {
  it('explains a missing WebGL 2 instead of drawing nothing, with no pointless retry', () => {
    const { el } = mount(<RendererGuard webgl2={false} scene={() => <p>scene</p>} />);
    expect(el.textContent).toContain('3D hologram unavailable');
    expect(el.querySelector('button')).toBeNull();
  });
  it('shows a notice when the GPU context is lost and remounts the scene on restart', () => {
    let lose: () => void = () => {};
    let mounts = 0;
    const Scene = ({ onLost }: { onLost: () => void }) => { lose = onLost; mounts++; return <p>scene</p>; };
    const { el } = mount(<RendererGuard webgl2 scene={(onLost) => <Scene onLost={onLost} />} />);
    expect(el.textContent).toBe('scene');
    act(() => lose());
    expect(el.textContent).toContain('Graphics renderer was reset');
    const before = mounts;
    act(() => el.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    expect(el.textContent).toBe('scene');
    expect(mounts).toBeGreaterThan(before);
  });
  it('contains a crash in the scene and keeps the page alive', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const Boom = () => { throw new Error('shader failed'); };
    const { el } = mount(<RendererGuard webgl2 scene={() => <Boom />} />);
    expect(el.textContent).toContain('Hologram renderer stopped');
    spy.mockRestore();
  });
});
