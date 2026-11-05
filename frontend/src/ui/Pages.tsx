import { Maximize2 } from 'lucide-react';
import { useUi, type Page } from '../store';
import { useWindows } from '../workspace/windows';
import type { WinKind } from '../workspace/layout';

const fmt = (n: number | undefined | null, unit = '%') => (n === undefined || n === null ? '--' : `${Math.round(n)}${unit}`);

export function MonitorContent() {
  const m = useUi((s) => s.metrics);
  return (
    <>
      <h1>System Monitor</h1>
      <p>Live values from the Python backend (psutil). History charts arrive in Phase 3.</p>
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

export function PageView() {
  const page = useUi((s) => s.page) as Page;
  if (page === 'home') return null;
  return (
    <main className="page glass" aria-live="polite">
      {(page === 'monitor' || page === 'models' || page === 'activity') && (
        <button className="toggle detach" onClick={() => { useWindows.getState().open(page as WinKind); useUi.getState().go('home'); }} aria-label="Open as floating window"><Maximize2 size={12} /> Window</button>
      )}
      {page === 'monitor' ? <MonitorContent /> : page === 'models' ? <ModelsContent /> : page === 'activity' ? <ActivityContent /> : <h1>Not available yet</h1>}
    </main>
  );
}
