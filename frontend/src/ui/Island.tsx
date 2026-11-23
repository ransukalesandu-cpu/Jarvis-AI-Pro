import { useUi } from '../store';
import { useWindows } from '../workspace/windows';
import { useFlows } from '../taskflow/flows';
import { visualState } from '../hologram/visualState';

/** Dynamic Island: assistant state, open windows, and a way into the palette. Real values only. */
export function Island() {
    const assistant = useUi((s) => visualState(s)); // OFFLINE when the backend is down, never LISTENING with the mic muted
    const setPalette = useUi((s) => s.setPalette);
    const muted = useUi((s) => s.muted);
    const wins = useWindows((s) => s.windows);
    const running = useUi((s) => s.jobs?.filter((j) => j.status === 'running').length ?? 0);
    const minimised = wins.filter((w) => w.state === 'minimized').length;
    const tasks = useFlows((s) => s.flows.filter((f) => f.state === 'running').length);
    return (
        <button className="island glass" onClick={() => setPalette(true)}>
            <span className="dot" data-state={assistant} aria-hidden />
            <span className="island-state" aria-live="polite">
                {assistant.toUpperCase()}
            </span>
            {muted && (
                <span className="island-meta" role="status">
                    MIC MUTED
                </span>
            )}
            {wins.length > 0 && (
                <span className="island-meta">
                    {wins.length} win{minimised ? ` · ${minimised} min` : ''}
                </span>
            )}
            {running > 0 && (
                <span className="island-meta">
                    {running} job{running > 1 ? 's' : ''}
                </span>
            )}
            {tasks > 0 && (
                <span className="island-meta">
                    {tasks} task{tasks > 1 ? 's' : ''} running
                </span>
            )}
            <kbd>Ctrl K</kbd>
            <span className="sr-only">Open command palette</span>
        </button>
    );
}
