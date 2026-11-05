import { useUi } from '../store';
import { useWindows } from '../workspace/windows';

/** Dynamic Island: assistant state, open windows, and a way into the palette. Real values only. */
export function Island() {
  const assistant = useUi((s) => s.assistant);
  const setPalette = useUi((s) => s.setPalette);
  const link = useUi((s) => s.link);
  const wins = useWindows((s) => s.windows);
  const minimised = wins.filter((w) => w.state === 'minimized').length;
  return (
    <button className="island glass" onClick={() => setPalette(true)} aria-label={`JARVIS ${assistant}. ${wins.length} windows. Open command palette`}>
      <span className="dot" data-state={assistant} aria-hidden />
      <span className="island-state" aria-live="polite">{assistant.toUpperCase()}</span>
      {wins.length > 0 && <span className="island-meta">{wins.length} win{minimised ? ` · ${minimised} min` : ''}</span>}
      {link === 'detached' && <span className="island-meta">offline</span>}
      <kbd>Ctrl K</kbd>
    </button>
  );
}
