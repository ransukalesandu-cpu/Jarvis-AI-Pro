import { Maximize2 } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { Spark } from './Spark';
import type { LogTag } from '../bridge/contract';
import { useUi, type Page } from '../store';
import { useWindows } from '../workspace/windows';
import type { WinKind } from '../workspace/layout';

const fmt = (n: number | undefined | null, unit = '%') => (n === undefined || n === null ? '--' : `${Math.round(n)}${unit}`);

export function MonitorContent() {
  const m = useUi((s) => s.metrics);
  const sr = useUi((s) => s.series);
  return (
    <>
      <h1>System Monitor</h1>
      <p>Live values from the Python backend (psutil), last two minutes.</p>
      <Spark label="CPU" data={sr.cpu} unit="%" max={100} />
      <Spark label="RAM" data={sr.ram} unit="%" max={100} />
      <Spark label="Network ↓" data={sr.down} unit=" KB/s" />
      <Spark label="Network ↑" data={sr.up} unit=" KB/s" />
      <div className="row"><span>CPU</span><span>{fmt(m?.cpu)}</span></div>
      <div className="row"><span>RAM</span><span>{fmt(m?.ram)}</span></div>
      <div className="row"><span>Disk</span><span>{fmt(m?.disk)}</span></div>
      <div className="row"><span>Battery</span><span>{m ? (m.battery ? `${fmt(m.battery.percent)}${m.battery.charging ? ' charging' : ''}` : 'none') : '--'}</span></div>
      <div className="row"><span>Network ↓ / ↑</span><span>{m?.net ? `${m.net.downKBps.toFixed(0)} / ${m.net.upKBps.toFixed(0)} KB/s` : '--'}</span></div>
    </>
  );
}

export function ModelsContent() {
  const p = useUi((s) => s.provider);
  return (
    <>
      <h1>AI Models</h1>
      <p>Read-only. Live voice always runs on Gemini Live. This is the one-shot text provider chosen in the classic settings; switching it stays there until a safe, authorised request exists for it.</p>
      <div className="row"><span>Text provider</span><span>{p?.provider ?? 'not reported'}</span></div>
      <div className="row"><span>Model</span><span>{p?.model ?? '--'}</span></div>
      <div className="row"><span>API key</span><span>{p ? (p.connected ? 'configured' : 'missing') : '--'}</span></div>
      <div className="row"><span>Fallback active</span><span>{p ? (p.fallback ? 'yes' : 'no') : '--'}</span></div>
    </>
  );
}

export function ActivityContent() {
  const history = useUi((s) => s.history);
  const a = useUi((s) => s.assistant);
  return (
    <>
      <h1>Activity Center</h1>
      <p>Assistant state changes reported by the backend this session. Task progress and cancellation arrive with the task events in Phase 3.</p>
      <div className="row"><span>Current</span><span>{a}</span></div>
      {[...history].reverse().map((h, i) => <div className="row" key={i}><span>{new Date(h.at).toLocaleTimeString()}</span><span>{h.state}</span></div>)}
      {history.length === 0 && <p>No state changes yet.</p>}
    </>
  );
}

const TAG_LABEL: Record<LogTag, string> = { you: 'You', ai: 'JARVIS', sys: 'System', err: 'Error', file: 'File' };

/** Read-only mirror of the assistant's log. Redacted and filtered in Python; nothing here can write back. */
export function LogView({ lines, onClear }: { lines: { id: number; at: number; tag: LogTag; text: string }[]; onClear: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  useEffect(() => { const el = box.current; if (el && stick.current) el.scrollTop = el.scrollHeight; }, [lines]);
  return (
    <>
      <h1>Conversation Log</h1>
      <p>Read-only. Sensitive values are redacted, and nothing is shown while JARVIS is locked or asking for a PIN.</p>
      <div className="logbox" ref={box} role="log" aria-label="Conversation log" aria-live="off" tabIndex={0}
        onScroll={(e) => { const t = e.currentTarget; stick.current = t.scrollHeight - t.scrollTop - t.clientHeight < 24; }}>
        {lines.length === 0 && <div className="log-empty">No messages yet this session.</div>}
        {lines.map((l) => (
          <div key={l.id} className={`log-line log-${l.tag}`}>
            <span className="log-tag">{TAG_LABEL[l.tag]}</span><span className="log-text">{l.text}</span>
          </div>
        ))}
      </div>
      <button className="toggle" onClick={onClear} disabled={lines.length === 0}>Clear view</button>
    </>
  );
}

export function LogContent() {
  const log = useUi((s) => s.log);
  const clear = useUi((s) => s.clearLog);
  return <LogView lines={log} onClear={clear} />;
}

export function PageView() {
  const page = useUi((s) => s.page) as Page;
  if (page === 'home') return null;
  return (
    <main className="page glass" aria-live="polite">
      {(page === 'monitor' || page === 'models' || page === 'activity' || page === 'chat') && (
        <button className="toggle detach" onClick={() => { useWindows.getState().open((page === 'chat' ? 'log' : page) as WinKind); useUi.getState().go('home'); }} aria-label="Open as floating window"><Maximize2 size={12} /> Window</button>
      )}
      {page === 'monitor' ? <MonitorContent /> : page === 'models' ? <ModelsContent /> : page === 'activity' ? <ActivityContent /> : page === 'chat' ? <LogContent /> : <h1>Not available yet</h1>}
    </main>
  );
}
