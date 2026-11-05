import { Activity, BatteryCharging, BatteryFull, BatteryLow, Brain, Cpu, Wifi, WifiOff } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useUi, type Page } from '../store';

const pct = (n: number) => `${Math.round(n)}%`;

function Bar({ value, low = false }: { value: number; low?: boolean }) {
  return <div className={`bar${low ? ' low' : ''}`} role="presentation"><i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>;
}

function Widget({ label, value, sub, icon, to, bar, low }: { label: string; value: string; sub?: string; icon: React.ReactNode; to: Page; bar?: number; low?: boolean }) {
  const go = useUi((s) => s.go);
  return (
    <button className="widget glass" onClick={() => go(to)} aria-label={`${label}: ${value}. Open ${to}`}>
      <div className="label">{icon} {label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
      {bar !== undefined && <Bar value={bar} low={low} />}
    </button>
  );
}

export function ClockWidget() {
  const clock24 = useUi((s) => s.clock24);
  const go = useUi((s) => s.toggleSettings);
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const id = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(id); }, []);
  return (
    <button className="widget glass" onClick={() => go(true)} aria-label="Time and date. Open settings">
      <div className="label">Time</div>
      <div className="value">{now.toLocaleTimeString([], { hour12: !clock24, hour: '2-digit', minute: '2-digit', second: '2-digit' })}</div>
      <div className="sub">{now.toLocaleDateString([], { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })}</div>
    </button>
  );
}

export function BatteryWidget() {
  const m = useUi((s) => s.metrics);
  if (!m) return <Widget label="Battery" value="--" sub="waiting for data" icon={<BatteryFull size={12} />} to="monitor" />;
  if (!m.battery) return <Widget label="Battery" value="No battery" sub="mains power" icon={<BatteryFull size={12} />} to="monitor" />;
  const { percent, charging } = m.battery, low = percent <= 20 && !charging;
  const Icon = charging ? BatteryCharging : low ? BatteryLow : BatteryFull;
  return <Widget label="Battery" value={pct(percent)} sub={charging ? 'charging' : low ? 'low battery' : 'on battery'} icon={<Icon size={12} />} to="monitor" bar={percent} low={low} />;
}

export function SystemWidget() {
  const m = useUi((s) => s.metrics);
  return (
    <Widget label="System" value={m ? `CPU ${pct(m.cpu)}` : '--'} sub={m ? `RAM ${pct(m.ram)}${m.disk !== null ? `  DISK ${pct(m.disk)}` : ''}` : 'waiting for data'}
      icon={<Cpu size={12} />} to="monitor" bar={m?.cpu ?? 0} low={(m?.cpu ?? 0) > 90} />
  );
}

export function BrainWidget() {
  const p = useUi((s) => s.provider);
  return (
    <Widget label="AI Brain" value={p ? p.provider : 'Unknown'} sub={p ? `${p.model} · ${p.connected ? 'connected' : 'offline'}${p.fallback ? ' · fallback' : ''}` : 'no provider reported'}
      icon={<Brain size={12} />} to="models" />
  );
}

export function NetworkWidget() {
  const m = useUi((s) => s.metrics);
  const net = m?.net;
  return (
    <Widget label="Network" value={net ? `↓ ${net.downKBps.toFixed(0)} KB/s` : '--'} sub={net ? `↑ ${net.upKBps.toFixed(0)} KB/s` : 'no network data'}
      icon={net ? <Wifi size={12} /> : <WifiOff size={12} />} to="monitor" />
  );
}

export function ActivityWidget() {
  const a = useUi((s) => s.assistant);
  const last = useUi((s) => s.history.at(-1));
  return <Widget label="Activity" value={a.toUpperCase()} sub={last ? `since ${new Date(last.at).toLocaleTimeString()}` : 'no events yet'} icon={<Activity size={12} />} to="activity" />;
}
