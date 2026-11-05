import { useUi } from '../store';
import { useWindows } from '../workspace/windows';

/** Dynamic Island: assistant state, open windows, and a way into the palette. Real values only. */
export function Island() {
  const assistant = useUi((s) => s.assistant);
  const setPalette = useUi((s) => s.setPalette);
  const link = useUi((s) => s.link);
  const muted = useUi((s) => s.muted);
  const wins = useWindows((s) => s.windows);
  const running = useUi((s) => s.jobs?.filter((j) => j.status === 'running').length ?? 0);
  const minimised = wins.filter((w) => w.state === 'minimized').length;
  return (
    <button className="island glass" onClick={() => setPalette(true)}>
      <span className="dot" data-state={assistant} aria-hidden />
      <span className="island-state" aria-live="polite">{assistant.toUpperCase()}</span>
      {muted && <span className="island-meta" role="status">MIC MUTED</span>}
      {wins.length > 0 && <span className="island-meta">{wins.length} win{minimised ? ` · ${minimised} min` : ''}</span>}
      {running > 0 && <span className="island-meta">{running} job{running > 1 ? 's' : ''}</span>}
      {link === 'detached' && <span className="island-meta">offline</span>}
      <kbd>Ctrl K</kbd>
      <span className="sr-only">Open command palette</span>
    </button>
  );
}
