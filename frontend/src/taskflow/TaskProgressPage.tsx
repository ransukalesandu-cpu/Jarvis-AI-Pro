import { PictureInPicture2 } from 'lucide-react';
import { useUi } from '../store';
import { FlowCanvas, useNow } from './FlowCanvas';
import { AUTO_HIDE_MS, counts, elapsed, useFlows } from './flows';

const STATE_LABEL = { running: 'Running', done: 'Done', failed: 'Failed', cancelled: 'Stopped' } as const;

/** Full page: every flow this session (newest first) and the selected one on a big canvas. Read-only. */
export function TaskProgressPage() {
    const flows = useFlows((s) => s.flows);
    const selected = useFlows((s) => s.selected);
    const logs = useFlows((s) => s.logs);
    const autoShow = useFlows((s) => s.autoShow);
    const { select, setAutoShow, showWindow } = useFlows.getState();
    const reduced = useUi((s) => s.reducedMotion);
    const anyRunning = flows.some((f) => f.state === 'running');
    const now = useNow(anyRunning, 500);
    const list = [...flows].reverse();
    const flow = flows.find((f) => f.id === selected) ?? list[0] ?? null;
    return (
        <div className="tf-page">
            <div className="tf-page-hd">
                <div>
                    <h1 className="ui-sr-only">Task Progress</h1>
                    <p>What JARVIS did for each command and task this session, step by step. Read-only; say “stop” to stop a task.</p>
                </div>
                <label className="tf-switch" title={`Pop up the task window for ${AUTO_HIDE_MS / 1000} s when a task starts`}>
                    <input type="checkbox" checked={autoShow} onChange={(e) => setAutoShow(e.target.checked)} />
                    <span>Show window for {AUTO_HIDE_MS / 1000} s on new tasks</span>
                </label>
            </div>
            <div className="tf-page-body">
                <aside className="tf-list" aria-label="Tasks">
                    {list.length === 0 && <p className="tf-none">No tasks yet this session. Give JARVIS a command and it appears here.</p>}
                    {list.map((f) => {
                        const c = counts(f);
                        return (
                            <button key={f.id} className="tf-item" aria-current={flow?.id === f.id ? 'true' : undefined} onClick={() => select(f.id)}>
                                <span className="tf-dot" data-state={f.state} />
                                <span className="tf-item-txt">
                                    <b>{f.title}</b>
                                    <small>
                                        {STATE_LABEL[f.state]} · {c.done}/{c.total} steps · {elapsed(f.startedAt, f.finishedAt, now)} ·{' '}
                                        {new Date(f.startedAt).toLocaleTimeString()}
                                    </small>
                                </span>
                            </button>
                        );
                    })}
                </aside>
                <section className="tf-stage" aria-label="Selected task">
                    {flow ? (
                        <>
                            <div className="tf-stage-hd">
                                <span className="tf-dot" data-state={flow.state} />
                                <b>{flow.title}</b>
                                <button className="toggle" onClick={() => showWindow(true, flow.id)}>
                                    <PictureInPicture2 size={12} /> Window
                                </button>
                            </div>
                            <FlowCanvas key={flow.id} flow={flow} log={logs[flow.id] ?? []} whole reduced={reduced} />
                        </>
                    ) : (
                        <div className="tf-empty">Nothing to show yet.</div>
                    )}
                </section>
            </div>
        </div>
    );
}
