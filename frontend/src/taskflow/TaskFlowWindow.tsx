import { Maximize2, Pin, PinOff, X } from 'lucide-react';
import { Presence } from '../motion/Presence';
import { useEffect, useState } from 'react';
import { useUi } from '../store';
import { FlowCanvas, useNow } from './FlowCanvas';
import { AUTO_HIDE_MS, counts, elapsed, useFlows, windowFlow, type FlowLogLine } from './flows';
import { SPACE } from '../styles/tokens';

const NO_LOG: FlowLogLine[] = [];

/**
 * The small Task Flow window. A new task pops it up and it hides itself after AUTO_HIDE_MS
 * (paused while the pointer is over it). Asked for by voice ("show the task progress window"),
 * from the palette or the island, it stays until closed.
 */
export function TaskFlowWindow() {
    const win = useFlows((s) => s.win);
    const flow = useFlows(windowFlow);
    const log = useFlows((s) => (flow ? s.logs[flow.id] : undefined)) ?? NO_LOG;
    const { showWindow, hideWindow } = useFlows.getState();
    const reduced = useUi((s) => s.reducedMotion);
    const go = useUi((s) => s.go);
    const [hover, setHover] = useState(false);
    const open = win.open && flow !== null;
    const now = useNow(open && flow?.state === 'running', 100);

    useEffect(() => {
        if (!open || win.pinned || hover) return;
        const id = setTimeout(() => useFlows.getState().hideWindow(), AUTO_HIDE_MS);
        return () => clearTimeout(id);
    }, [open, win.pinned, win.flowId, hover]);

    const c = flow ? counts(flow) : null;
    return (
        <Presence<HTMLElement> show={Boolean(open && flow && c)} reduced={reduced} offset={{ y: SPACE['space-3-5'], scale: 0.97 }}>
            {(ref) =>
                flow && c ? (
                    <section
                        ref={ref}
                        className="tf-win glass"
                        role="dialog"
                        aria-label="Task progress"
                        aria-live="polite"
                        onPointerEnter={() => setHover(true)}
                        onPointerLeave={() => setHover(false)}
                    >
                        <header className="tf-hd">
                            <span className="tf-dot" data-state={flow.state} />
                            <span className="tf-ttl">
                                <small>TASK FLOW</small>
                                <span title={flow.title}>{flow.title}</span>
                            </span>
                            <span className="tf-clock">{elapsed(flow.startedAt, flow.finishedAt, now)}</span>
                            <button
                                onClick={() => (win.pinned ? hideWindow() : showWindow(true, flow.id))}
                                aria-label={win.pinned ? 'Unpin (close)' : 'Keep open'}
                                title={win.pinned ? 'Pinned' : 'Keep open'}
                            >
                                {win.pinned ? <PinOff size={12} /> : <Pin size={12} />}
                            </button>
                            <button
                                onClick={() => {
                                    useFlows.getState().select(flow.id);
                                    hideWindow();
                                    go('tasks');
                                }}
                                aria-label="Open Task Progress page"
                                title="Open page"
                            >
                                <Maximize2 size={12} />
                            </button>
                            <button onClick={hideWindow} aria-label="Close task window">
                                <X size={12} />
                            </button>
                        </header>
                        <div className="tf-prog">
                            <i style={{ width: `${flow.state === 'done' ? 100 : c.total ? (c.done / c.total) * 100 : 3}%` }} />
                        </div>
                        <FlowCanvas flow={flow} log={log} whole={false} reduced={reduced} />
                        {!win.pinned && !hover && (
                            <div className="tf-autohide" style={{ animationDuration: `${AUTO_HIDE_MS}ms` }} key={`${flow.id}-${win.flowId}`} aria-hidden />
                        )}
                    </section>
                ) : (
                    <span />
                )
            }
        </Presence>
    );
}
