import { Spark } from './Spark';
import { useUi } from '../store';

const fmt = (n: number | undefined | null, unit = '%') => (n === undefined || n === null ? '--' : `${Math.round(n)}${unit}`);

export interface BentoProps {
  assistant: string; persona: string; perfTier: string | null; muted: boolean;
  provider: { provider: string; model: string; connected: boolean; fallback: boolean } | null;
  cpu: number[]; ram: number[]; down: number[]; up: number[];
  disk: number | null | undefined; battery: string;
}

/** Bento dashboard: the same real values as the other windows, laid out as cards. Nothing here is invented. */
export function BentoView(p: BentoProps) {
  return (
    <div className="bento">
      <div className="bento-card" role="group" aria-label="Assistant"><h3>Assistant</h3>
        <div className="row"><span>State</span><span>{p.assistant}</span></div>
        <div className="row"><span>Persona</span><span>{p.persona}</span></div>
        <div className="row"><span>Microphone</span><span>{p.muted ? 'muted' : 'on'}</span></div>
        <div className="row"><span>Performance</span><span>{p.perfTier ?? 'not reported'}</span></div>
      </div>
      <div className="bento-card" role="group" aria-label="AI model"><h3>AI model</h3>
        <div className="row"><span>Provider</span><span>{p.provider?.provider ?? 'not reported'}</span></div>
        <div className="row"><span>Model</span><span>{p.provider?.model ?? '--'}</span></div>
        <div className="row"><span>API key</span><span>{p.provider ? (p.provider.connected ? 'configured' : 'missing') : '--'}</span></div>
      </div>
      <div className="bento-card wide" role="group" aria-label="Processor and memory"><h3>CPU and RAM</h3>
        <Spark label="CPU" data={p.cpu} unit="%" max={100} /><Spark label="RAM" data={p.ram} unit="%" max={100} />
      </div>
      <div className="bento-card wide" role="group" aria-label="Network"><h3>Network</h3>
        <Spark label="Down" data={p.down} unit=" KB/s" /><Spark label="Up" data={p.up} unit=" KB/s" />
      </div>
      <div className="bento-card" role="group" aria-label="Storage and power"><h3>Storage and power</h3>
        <div className="row"><span>Disk</span><span>{fmt(p.disk)}</span></div>
        <div className="row"><span>Battery</span><span>{p.battery}</span></div>
      </div>
    </div>
  );
}

export function BentoContent() {
  const s = useUi();
  const m = s.metrics;
  return <BentoView assistant={s.assistant} persona={s.persona} perfTier={s.perfTier} muted={s.muted} provider={s.provider}
    cpu={s.series.cpu} ram={s.series.ram} down={s.series.down} up={s.series.up} disk={m?.disk}
    battery={m ? (m.battery ? `${fmt(m.battery.percent)}${m.battery.charging ? ' charging' : ''}` : 'none') : '--'} />;
}
