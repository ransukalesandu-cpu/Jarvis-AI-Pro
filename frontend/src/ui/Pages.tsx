import { useEffect, useRef } from 'react';
import { Spark } from './Spark';
import type { LogTag } from '../bridge/contract';
import { useUi } from '../store';
import { Button, StateView } from '../components/ui';
import { useT } from '../i18n';

/** Whether live data can arrive: 'wait' while connecting, 'offline' with no backend, else 'ok'. */
export function useLink(): 'wait' | 'offline' | 'ok' {
    const link = useUi((s) => s.link);
    return link === 'connected' ? 'ok' : link === 'connecting' ? 'wait' : 'offline';
}

/** Shown instead of live data while there is none to show. */
export function NoData({ link, what }: { link: 'wait' | 'offline' | 'ok'; what: string }) {
    const T = useT();
    if (link === 'offline') return <StateView kind="offline" title={T('s.notConnected')} message={T('s.appearsWhenRunning', { what })} />;
    if (link === 'ok') return <StateView kind="empty" title={T('s.notReported')} message={T('s.showsWhenReported', { what })} />;
    return <StateView kind="loading" title={T('s.loading', { what: what.toLowerCase() })} />;
}

const fmt = (n: number | undefined | null, unit = '%') => (n === undefined || n === null ? '--' : `${Math.round(n)}${unit}`);

export function MonitorContent() {
    const m = useUi((s) => s.metrics);
    const sr = useUi((s) => s.series);
    const link = useLink();
    const T = useT();
    if (!m) return <NoData link={link} what={T('monitor.what')} />;
    return (
        <>
            <h1 className="ui-sr-only">{T('win.monitor')}</h1>
            <p>{T('monitor.intro')}</p>
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
    const T = useT();
    if (!p) return <NoData link={link} what={T('models.what')} />;
    return (
        <>
            <h1 className="ui-sr-only">{T('win.models')}</h1>
            <p>{T('models.intro')}</p>
            <div className="row">
                <span>{T('models.provider')}</span>
                <span>{p.provider}</span>
            </div>
            <div className="row">
                <span>{T('models.model')}</span>
                <span>{p.model}</span>
            </div>
            <div className="row">
                <span>{T('models.key')}</span>
                <span>{p.connected ? 'configured' : 'missing'}</span>
            </div>
            <div className="row">
                <span>{T('models.fallback')}</span>
                <span>{p.fallback ? 'yes' : 'no'}</span>
            </div>
        </>
    );
}

export function ActivityContent() {
    const history = useUi((s) => s.history);
    const a = useUi((s) => s.assistant);
    const T = useT();
    return (
        <>
            <h1 className="ui-sr-only">{T('win.activity')}</h1>
            <p>{T('activity.intro')}</p>
            <div className="row">
                <span>{T('activity.current')}</span>
                <span>{a}</span>
            </div>
            {[...history].reverse().map((h, i) => (
                <div className="row" key={i}>
                    <span>{new Date(h.at).toLocaleTimeString()}</span>
                    <span>{h.state}</span>
                </div>
            ))}
            {history.length === 0 && <StateView kind="empty" title={T('activity.emptyTitle')} message={T('activity.empty')} />}
        </>
    );
}

const TAG_LABEL: Record<LogTag, string> = { you: 'You', ai: 'JARVIS', sys: 'System', err: 'Error', file: 'File' };

/** Read-only mirror of the assistant's log. Redacted and filtered in Python; nothing here can write back. */
export function LogView({ lines, onClear }: { lines: { id: number; at: number; tag: LogTag; text: string }[]; onClear: () => void }) {
    const box = useRef<HTMLDivElement>(null);
    const stick = useRef(true);
    const T = useT();
    useEffect(() => {
        const el = box.current;
        if (el && stick.current) el.scrollTop = el.scrollHeight;
    }, [lines]);
    return (
        <>
            <h1 className="ui-sr-only">{T('win.log')}</h1>
            <p>{T('log.intro')}</p>
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
                {lines.length === 0 && <StateView kind="empty" title={T('log.emptyTitle')} message={T('log.empty')} />}
                {lines.map((l) => (
                    <div key={l.id} className={`log-line log-${l.tag}`}>
                        <span className="log-tag">{TAG_LABEL[l.tag]}</span>
                        <span className="log-text">{l.text}</span>
                    </div>
                ))}
            </div>
            <Button variant="outline" tone="neutral" size="sm" onClick={onClear} disabled={lines.length === 0}>
                {T('log.clear')}
            </Button>
        </>
    );
}

export function LogContent() {
    const log = useUi((s) => s.log);
    const clear = useUi((s) => s.clearLog);
    return <LogView lines={log} onClear={clear} />;
}
