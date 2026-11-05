import { useUi, type Page } from '../store';

const fmt = (n: number | undefined | null, unit = '%') => (n === undefined || n === null ? '--' : `${Math.round(n)}${unit}`);

function Monitor() {
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

function Models() {
  const p = useUi((s) => s.provider);
  return (
    <>
      <h1>AI Models</h1>
      <p>Read-only in Phase 1. Provider switching stays in the existing settings until a safe, authorised request exists for it.</p>
      <div className="row"><span>Provider</span><span>{p?.provider ?? 'not reported'}</span></div>
      <div className="row"><span>Model</span><span>{p?.model ?? '--'}</span></div>
      <div className="row"><span>Connection</span><span>{p ? (p.connected ? 'connected' : 'offline') : '--'}</span></div>
      <div className="row"><span>Fallback active</span><span>{p ? (p.fallback ? 'yes' : 'no') : '--'}</span></div>
    </>
  );
}

function ActivityPage() {
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
      {page === 'monitor' ? <Monitor /> : page === 'models' ? <Models /> : page === 'activity' ? <ActivityPage /> : <h1>Not available yet</h1>}
    </main>
  );
}
