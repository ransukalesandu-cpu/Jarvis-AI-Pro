import { useEffect, useRef } from 'react';
import { Spark } from './Spark';
import type { LogTag } from '../bridge/contract';
import { useUi } from '../store';
import { Button, StateView } from '../components/ui';

/** Whether live data can arrive: 'wait' while connecting, 'offline' with no backend, else 'ok'. */
export function useLink(): 'wait' | 'offline' | 'ok' {
    const link = useUi((s) => s.link);
    return link === 'connected' ? 'ok' : link === 'connecting' ? 'wait' : 'offline';
}

/** Shown instead of live data while there is none to show. */
export function NoData({ link, what }: { link: 'wait' | 'offline' | 'ok'; what: string }) {
    if (link === 'offline') return <StateView kind="offline" title="JARVIS is not connected" message={`${what} appears when JARVIS is running.`} />;
    if (link === 'ok') return <StateView kind="empty" title="Not reported yet" message={`${what} shows here as soon as JARVIS reports it.`} />;
    return <StateView kind="loading" title={`Loading ${what.toLowerCase()}`} />;
}

const fmt = (n: number | undefined | null, unit = '%') => (n === undefined || n === null ? '--' : `${Math.round(n)}${unit}`);

export function MonitorContent() {
    const m = useUi((s) => s.metrics);
    const sr = useUi((s) => s.series);
    const link = useLink();
    if (!m) return <NoData link={link} what="Live system data" />;
    return (
        <>
            <h1 className="ui-sr-only">System Monitor</h1>
            <p>This computer, live. Charts show the last two minutes.</p>
            <Spark label="CPU" data={sr.cpu} unit="%" max={100} />
            <Spark label="RAM" data={sr.ram} unit="%" max={100} tone="amber" />
            <Spark label="Network ↓" data={sr.down} unit=" KB/s" />
            <Spark label="Network ↑" data={sr.up} unit=" KB/s" />
            <div className="row">
                <span>CPU</span>
                <span>{fmt(m?.cpu)}</span>
            </div>
            <div className="row">
                <span>RAM</span>
                <span>{fmt(m?.ram)}</span>
            </div>
            <div className="row">
                <span>Disk</span>
                <span>{fmt(m?.disk)}</span>
            </div>
            <div className="row">
                <span>Battery</span>
                <span>{m ? (m.battery ? `${fmt(m.battery.percent)}${m.battery.charging ? ' charging' : ''}` : 'none') : '--'}</span>
            </div>
            <div className="row">
                <span>Network ↓ / ↑</span>
                <span>{m?.net ? `${m.net.downKBps.toFixed(0)} / ${m.net.upKBps.toFixed(0)} KB/s` : '--'}</span>
            </div>
        </>
    );
}

export function ModelsContent() {
    const p = useUi((s) => s.provider);
    const link = useLink();
    if (!p) return <NoData link={link} what="The AI model in use" />;
    return (
        <>
            <h1 className="ui-sr-only">AI Models</h1>
            <p>Voice always runs on Gemini Live. Typed requests use the text model below; change it in the classic settings.</p>
            <div className="row">
                <span>Text provider</span>
                <span>{p.provider}</span>
            </div>
            <div className="row">
                <span>Model</span>
                <span>{p.model}</span>
            </div>
            <div className="row">
                <span>API key</span>
                <span>{p.connected ? 'configured' : 'missing'}</span>
            </div>
            <div className="row">
                <span>Fallback active</span>
                <span>{p.fallback ? 'yes' : 'no'}</span>
            </div>
        </>
    );
}

export function ActivityContent() {
    const history = useUi((s) => s.history);
    const a = useUi((s) => s.assistant);
    return (
        <>
            <h1 className="ui-sr-only">Activity Center</h1>
            <p>What JARVIS has been doing this session. Step-by-step task progress is in Task Progress.</p>
            <div className="row">
                <span>Current</span>
                <span>{a}</span>
            </div>
            {[...history].reverse().map((h, i) => (
                <div className="row" key={i}>
                    <span>{new Date(h.at).toLocaleTimeString()}</span>
                    <span>{h.state}</span>
                </div>
            ))}
            {history.length === 0 && <StateView kind="empty" title="Nothing yet" message="Talk to JARVIS or give it a task; each change shows here." />}
        </>
    );
}

const TAG_LABEL: Record<LogTag, string> = { you: 'You', ai: 'JARVIS', sys: 'System', err: 'Error', file: 'File' };

/** Read-only mirror of the assistant's log. Redacted and filtered in Python; nothing here can write back. */
export function LogView({ lines, onClear }: { lines: { id: number; at: number; tag: LogTag; text: string }[]; onClear: () => void }) {
    const box = useRef<HTMLDivElement>(null);
    const stick = useRef(true);
    useEffect(() => {
        const el = box.current;
        if (el && stick.current) el.scrollTop = el.scrollHeight;
    }, [lines]);
    return (
        <>
            <h1 className="ui-sr-only">Conversation Log</h1>
            <p>Read-only. Sensitive values are hidden, and nothing shows while JARVIS is locked or asking for a PIN.</p>
            <div
                className="logbox"
                ref={box}
                role="log"
                aria-label="Conversation log"
                aria-live="off"
                tabIndex={0}
                onScroll={(e) => {
                    const t = e.currentTarget;
                    stick.current = t.scrollHeight - t.scrollTop - t.clientHeight < 24;
                }}
            >
                {lines.length === 0 && <StateView kind="empty" title="No messages yet" message="What you and JARVIS say this session appears here." />}
                {lines.map((l) => (
                    <div key={l.id} className={`log-line log-${l.tag}`}>
                        <span className="log-tag">{TAG_LABEL[l.tag]}</span>
                        <span className="log-text">{l.text}</span>
                    </div>
                ))}
            </div>
            <Button variant="outline" tone="neutral" size="sm" onClick={onClear} disabled={lines.length === 0}>
                Clear view
            </Button>
        </>
    );
}

export function LogContent() {
    const log = useUi((s) => s.log);
    const clear = useUi((s) => s.clearLog);
    return <LogView lines={log} onClear={clear} />;
}
