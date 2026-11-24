import { Activity, BatteryCharging, BatteryFull, BatteryLow, Brain, Cpu, Mic, MicOff, Plug, Volume2, Wifi, WifiOff, Workflow } from 'lucide-react';
import type { AssistantState, Flow } from '../bridge/contract';
import { useFlows } from '../taskflow/flows';
import { visualState } from '../hologram/visualState';
import { useEffect, useState } from 'react';
import { useUi, type Page } from '../store';
import { useT } from '../i18n';

const pct = (n: number) => `${Math.round(n)}%`;

function Bar({ value, low = false }: { value: number; low?: boolean }) {
    return (
        <div className={`bar${low ? ' low' : ''}`} role="presentation">
            <i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
        </div>
    );
}

function Widget({
    label,
    value,
    sub,
    icon,
    to,
    bar,
    low,
}: {
    label: string;
    value: string;
    sub?: string;
    icon: React.ReactNode;
    to: Page;
    bar?: number;
    low?: boolean;
}) {
    const go = useUi((s) => s.go);
    return (
        <button className="widget glass" onClick={() => go(to)}>
            <div className="label">
                {icon} {label}
            </div>
            <div className="value">{value}</div>
            {sub && <div className="sub">{sub}</div>}
            {bar !== undefined && <Bar value={bar} low={low} />}
            <span className="sr-only">Open {to}</span>
        </button>
    );
}

export function ClockWidget() {
    const clock24 = useUi((s) => s.clock24);
    const go = useUi((s) => s.toggleSettings);
    const T = useT();
    const locale = useUi((s) => (s.lang === 'si' ? 'si-LK' : undefined));
    const [now, setNow] = useState(() => new Date());
    useEffect(() => {
        const id = setInterval(() => setNow(new Date()), 1000);
        return () => clearInterval(id);
    }, []);
    return (
        <button className="widget glass" onClick={() => go(true)}>
            <div className="label">{T('w.time')}</div>
            <div className="value">{now.toLocaleTimeString(locale ?? [], { hour12: !clock24, hour: '2-digit', minute: '2-digit', second: '2-digit' })}</div>
            <div className="sub">{now.toLocaleDateString(locale ?? [], { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })}</div>
            <span className="sr-only">Open settings</span>
        </button>
    );
}

export function BatteryWidget() {
    const m = useUi((s) => s.metrics);
    const T = useT();
    if (!m) return <Widget label={T('w.battery')} value="--" sub={T('w.waiting')} icon={<BatteryFull size={12} />} to="monitor" />;
    if (!m.battery) return <Widget label={T('w.battery')} value={T('w.noBattery')} sub={T('w.mains')} icon={<BatteryFull size={12} />} to="monitor" />;
    const { percent, charging } = m.battery,
        low = percent <= 20 && !charging;
    const Icon = charging ? BatteryCharging : low ? BatteryLow : BatteryFull;
    return (
        <Widget
            label={T('w.battery')}
            value={pct(percent)}
            sub={charging ? 'charging' : low ? 'low battery' : 'on battery'}
            icon={<Icon size={12} />}
            to="monitor"
            bar={percent}
            low={low}
        />
    );
}

export function SystemWidget() {
    const m = useUi((s) => s.metrics);
    const T = useT();
    return (
        <Widget
            label={T('w.system')}
            value={m ? `CPU ${pct(m.cpu)}` : '--'}
            sub={m ? `RAM ${pct(m.ram)}${m.disk !== null ? `  DISK ${pct(m.disk)}` : ''}` : T('w.waiting')}
            icon={<Cpu size={12} />}
            to="monitor"
            bar={m?.cpu ?? 0}
            low={(m?.cpu ?? 0) > 90}
        />
    );
}

export function BrainWidget() {
    const p = useUi((s) => s.provider);
    const link = useUi((s) => s.link);
    const T = useT();
    const waiting =
        link === 'detached'
            ? [T('w.offline'), T('w.offlineSub')]
            : link === 'connected'
              ? [T('w.notReported'), T('w.notReportedSub')]
              : [T('w.connecting'), T('w.connectingSub')];
    return (
        <Widget
            label={T('w.brain')}
            value={p ? p.provider : waiting[0]}
            sub={p ? `${p.model} · ${p.connected ? 'connected' : 'offline'}${p.fallback ? ' · fallback' : ''}` : waiting[1]}
            icon={<Brain size={12} />}
            to="models"
        />
    );
}

export function NetworkWidget() {
    const m = useUi((s) => s.metrics);
    const net = m?.net;
    const T = useT();
    return (
        <Widget
            label={T('w.network')}
            value={net ? `↓ ${net.downKBps.toFixed(0)} KB/s` : '--'}
            sub={net ? `↑ ${net.upKBps.toFixed(0)} KB/s` : 'no network data'}
            icon={net ? <Wifi size={12} /> : <WifiOff size={12} />}
            to="monitor"
        />
    );
}

export function ActivityWidget() {
    const a = useUi((s) => visualState(s));
    const last = useUi((s) => s.history.at(-1));
    const T = useT();
    return (
        <Widget
            label={T('w.activity')}
            value={a.toUpperCase()}
            sub={last ? T('w.since', { time: new Date(last.at).toLocaleTimeString() }) : T('w.noEvents')}
            icon={<Activity size={12} />}
            to="activity"
        />
    );
}

export type Link = 'connecting' | 'connected' | 'detached';
export interface VoiceLinkInput {
    link: Link;
    muted: boolean;
    assistant: AssistantState;
    flows: Flow[];
}
export interface VoiceLinkRow {
    key: 'mic' | 'output' | 'backend' | 'task';
    label: string;
    value: string;
    tone: 'ok' | 'warn' | 'dim';
}

/** The four live status lines, from real state only: no value is shown that the backend did not report. */
export function voiceLinkRows(s: VoiceLinkInput): VoiceLinkRow[] {
    const up = s.link === 'connected';
    const task = s.flows.filter((f) => f.state === 'running').at(-1);
    return [
        {
            key: 'mic',
            label: 'Mic',
            tone: !up ? 'dim' : s.muted ? 'warn' : 'ok',
            value: !up ? 'unknown' : s.muted ? 'muted' : s.assistant === 'listening' ? 'listening' : 'on',
        },
        {
            key: 'output',
            label: 'Voice',
            tone: up && s.assistant === 'speaking' ? 'ok' : 'dim',
            value: !up ? 'unknown' : s.assistant === 'speaking' ? 'speaking' : 'quiet',
        },
        {
            key: 'backend',
            label: 'Backend',
            tone: up ? 'ok' : s.link === 'connecting' ? 'warn' : 'dim',
            value: up ? 'connected' : s.link === 'connecting' ? 'connecting' : 'offline',
        },
        { key: 'task', label: 'Task', tone: task ? 'ok' : 'dim', value: task ? task.title : 'none' },
    ];
}

const ROW_ICON = { mic: Mic, output: Volume2, backend: Plug, task: Workflow } as const;

export function VoiceLinkView({ rows, level }: { rows: VoiceLinkRow[]; level: number | null }) {
    const T = useT();
    return (
        <>
            <div className="label">{T('w.voiceLink')}</div>
            <ul className="vl-rows">
                {rows.map((r) => {
                    const Icon = r.key === 'mic' && r.value === 'muted' ? MicOff : ROW_ICON[r.key];
                    return (
                        <li key={r.key} data-tone={r.tone}>
                            <Icon size={12} aria-hidden />
                            <span className="vl-label">{r.label}</span>
                            <span className="vl-value" title={r.value}>
                                {r.value}
                            </span>
                        </li>
                    );
                })}
            </ul>
            {level !== null && <Bar value={level * 100} />}
        </>
    );
}

/** Mic, voice output, backend link and the running task in one small, live indicator. Opens the Activity Center. */
export function VoiceLinkWidget() {
    const link = useUi((s) => s.link);
    const muted = useUi((s) => s.muted);
    const assistant = useUi((s) => s.assistant);
    const go = useUi((s) => s.go);
    const listening = link === 'connected' && !muted && assistant === 'listening';
    const inputLevel = useUi((s) => (listening ? Math.round(s.inputLevel * 20) / 20 : 0)); // 5% steps: no re-render per audio frame
    const flows = useFlows((s) => s.flows);
    const rows = voiceLinkRows({ link, muted, assistant, flows });
    return (
        <button
            className="widget glass voice-link"
            onClick={() => go('activity')}
            aria-label={`Voice and link: ${rows.map((r) => `${r.label} ${r.value}`).join(', ')}. Open Activity Center`}
        >
            <VoiceLinkView rows={rows} level={listening ? inputLevel : null} />
        </button>
    );
}
