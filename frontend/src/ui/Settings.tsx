import { useState, type ReactNode } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { sendRequest } from '../bridge/bridge';
import type { CommandState, ControlAction, MemoryStatus, Net } from '../bridge/contract';
import { visualState } from '../hologram/visualState';
import { useShallow } from 'zustand/react/shallow';
import { useUi } from '../store';
import { useFlows } from '../taskflow/flows';
import { useFresh } from '../ux/useFresh';
import { useWindows } from '../workspace/windows';
import { RESULT } from './CommandBar';
import { DURATIONS } from '../styles/tokens';
import { Button, Segmented, Switch, Tabs } from '../components/ui';

const ask = (action: ControlAction) => sendRequest({ kind: 'control.do', action });
export const PERSONA_OPTS = [
    { id: 'jarvis', label: 'JARVIS', action: 'mode_jarvis' },
    { id: 'bihansa', label: 'BIHANSA', action: 'mode_bihansa' },
] as const;
export const PERF_OPTS = [
    { label: 'Auto', action: 'perf_auto' },
    { label: 'Full', action: 'perf_full' },
    { label: 'Balanced', action: 'perf_balanced' },
    { label: 'Lite', action: 'perf_lite' },
] as const;

/** System Control Center sections, in the order of the upgrade spec. */
export const SECTIONS = ['general', 'ai', 'voice', 'security', 'memory', 'performance', 'devices'] as const;
export type Section = (typeof SECTIONS)[number];
export const SECTION_LABEL: Record<Section, string> = {
    general: 'General',
    ai: 'AI',
    voice: 'Voice',
    security: 'Security',
    memory: 'Memory',
    performance: 'Performance',
    devices: 'Devices',
};

/** What the backend's access state means to the owner. Display only: Python stays the security authority. */
export const ACCESS_LABEL: Record<CommandState, string> = {
    ok: 'Commands allowed',
    locked: 'Privacy Lock on',
    auth_required: 'Verification needed (PIN or Voice ID)',
    silent: 'Silent mode',
    guest: 'Guest mode (limited)',
    unavailable: 'Not reported yet',
};

export function memoryRows(m: MemoryStatus | null): [string, string][] {
    if (!m) return [['Memory status', 'not reported yet']];
    return [
        ['Supabase cloud', m.cloud === 'configured' ? 'configured' : 'not configured'],
        ['Personal cloud memory', m.personal ? 'on (opt-in)' : 'off'],
        ['Local memory encryption', m.encrypted ? 'on' : 'off'],
    ];
}

export function netText(net: Net | null | undefined): string {
    return net ? `↓ ${Math.round(net.downKBps)} KB/s · ↑ ${Math.round(net.upKBps)} KB/s` : 'no data';
}

function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
    return (
        <div className="row">
            <span>{label}</span>
            {children}
        </div>
    );
}

function Toggle({ label, on, onClick, disabled }: { label: string; on: boolean; onClick: () => void; disabled?: boolean }) {
    return <Switch label={label} checked={on} onCheckedChange={onClick} disabled={disabled} />;
}

/** System Control Center. Only settings that really do something are interactive; status rows show real backend values. */
export function SettingsPanel() {
    // Pick fields: subscribing to the whole store would re-render on every audio level frame.
    const {
        settingsOpen,
        reducedMotion,
        setReducedMotion,
        clock24,
        setClock24,
        persona,
        perfTier,
        link,
        control: rawControl,
        resultSeq,
        toggleSettings,
        perfOverlay,
        setPerfOverlay,
        faceStyle,
        setFaceStyle,
        centerStyle,
        setCenterStyle,
        provider,
        memory,
        muted,
        metrics,
        command,
        assistant,
    } = useUi(
        useShallow((s) => ({
            settingsOpen: s.settingsOpen,
            reducedMotion: s.reducedMotion,
            setReducedMotion: s.setReducedMotion,
            clock24: s.clock24,
            setClock24: s.setClock24,
            persona: s.persona,
            perfTier: s.perfTier,
            link: s.link,
            control: s.control,
            resultSeq: s.resultSeq,
            toggleSettings: s.toggleSettings,
            perfOverlay: s.perfOverlay,
            setPerfOverlay: s.setPerfOverlay,
            faceStyle: s.faceStyle,
            setFaceStyle: s.setFaceStyle,
            centerStyle: s.centerStyle,
            setCenterStyle: s.setCenterStyle,
            provider: s.provider,
            memory: s.memory,
            muted: s.muted,
            metrics: s.metrics,
            command: s.command,
            assistant: s.assistant,
        })),
    );
    const [section, setSection] = useState<Section>('general');
    const control = useFresh(rawControl, resultSeq);
    const autoShow = useFlows((s) => s.autoShow);
    const up = link === 'connected';
    const saved = up ? 'Saved on this PC' : 'Not saved: backend not connected';
    const vs = visualState({ assistant, link, muted });

    const body: Record<Section, ReactNode> = {
        general: (
            <>
                <Row label="Reduced motion">
                    <Toggle label="Reduced motion" on={reducedMotion} onClick={() => setReducedMotion(!reducedMotion)} />
                </Row>
                <Row label="24-hour clock">
                    <Toggle label="24-hour clock" on={clock24} onClick={() => setClock24(!clock24)} />
                </Row>
                <Row label="Show Task Flow on new tasks">
                    <Toggle label="Show Task Flow on new tasks" on={autoShow} onClick={() => useFlows.getState().setAutoShow(!autoShow)} />
                </Row>
                <Row label="Centre">
                    <Segmented
                        label="Centre"
                        value={centerStyle}
                        onValueChange={(v) => setCenterStyle(v as typeof centerStyle)}
                        options={[
                            { value: 'brain', label: 'Neural brain' },
                            { value: 'hologram', label: 'Hologram head' },
                        ]}
                    />
                </Row>
                {centerStyle === 'hologram' && (
                    <Row label="Face style">
                        <Segmented
                            label="Face style"
                            value={faceStyle}
                            onValueChange={(v) => setFaceStyle(v as typeof faceStyle)}
                            options={[
                                { value: 'circuit', label: 'Circuit' },
                                { value: 'mechanical', label: 'Mechanical' },
                            ]}
                        />
                    </Row>
                )}
                <p className="settings-note">{saved}</p>
            </>
        ),
        ai: (
            <>
                <Row label="Provider">
                    <span>{provider?.provider ?? 'not reported'}</span>
                </Row>
                <Row label="Model">
                    <span title={provider?.model}>{provider?.model ?? '—'}</span>
                </Row>
                <Row label="Status">
                    <span>{!provider ? '—' : !provider.connected ? 'offline' : provider.fallback ? 'connected (fallback)' : 'connected'}</span>
                </Row>
                <Row label="API keys, providers, compare">
                    <Button
                        variant="outline"
                        tone="neutral"
                        size="sm"
                        onClick={() => {
                            useWindows.getState().open('features');
                            toggleSettings(false);
                        }}
                    >
                        Features Hub
                    </Button>
                </Row>
                <p className="settings-note">Keys stay in Python and are never sent to this page.</p>
            </>
        ),
        voice: (
            <>
                <Row label="Microphone">
                    <Button
                        variant="outline"
                        tone={up && muted ? 'warn' : 'neutral'}
                        size="sm"
                        aria-pressed={up && !muted}
                        disabled={!up}
                        onClick={() => ask(muted ? 'unmute' : 'mute')}
                    >
                        {!up ? 'Unknown' : muted ? 'Muted' : 'On'}
                    </Button>
                </Row>
                <Row label="Voice state">
                    <span>{vs}</span>
                </Row>
                <Row label="Persona and voice">
                    <Segmented
                        label="Persona"
                        value={persona ?? ''}
                        disabled={!up}
                        onValueChange={(v) => {
                            const o = PERSONA_OPTS.find((p) => p.id === v);
                            if (o) ask(o.action);
                        }}
                        options={PERSONA_OPTS.map((o) => ({ value: o.id, label: o.label }))}
                    />
                </Row>
                <p className="settings-note">Unmuting and switching persona go through the same checks as the voice commands.</p>
            </>
        ),
        security: (
            <>
                <Row label="Access">
                    <span>{up ? ACCESS_LABEL[command.state] : 'unknown (backend offline)'}</span>
                </Row>
                <p className="settings-note">
                    Owner, Guest, PIN, Voice ID and Privacy Lock are decided by JARVIS itself. This page only shows the result and cannot change access.
                </p>
            </>
        ),
        memory: (
            <>
                {memoryRows(up ? memory : null).map(([k, v]) => (
                    <Row key={k} label={k}>
                        <span>{v}</span>
                    </Row>
                ))}
                <p className="settings-note">Read-only here. Stored memories are never sent to this page.</p>
            </>
        ),
        performance: (
            <>
                <Row
                    label={
                        <>
                            Rendering quality <small>({perfTier ?? 'not reported'})</small>
                        </>
                    }
                >
                    <Segmented
                        label="Rendering quality"
                        value={perfTier ?? ''}
                        disabled={!up}
                        onValueChange={(v) => {
                            const o = PERF_OPTS.find((p) => p.label.toLowerCase() === v);
                            if (o) ask(o.action);
                        }}
                        options={PERF_OPTS.map((o) => ({ value: o.label.toLowerCase(), label: o.label }))}
                    />
                </Row>
                <Row
                    label={
                        <>
                            Performance overlay <small>(measured FPS, frame time, draw calls, memory)</small>
                        </>
                    }
                >
                    <Toggle label="Performance overlay" on={perfOverlay} onClick={() => setPerfOverlay(!perfOverlay)} />
                </Row>
                <p className="settings-note">Auto picks a tier from this PC; the renderer also lowers its resolution when frames run slow.</p>
            </>
        ),
        devices: (
            <>
                <Row label="Backend link">
                    <span>{link}</span>
                </Row>
                <Row label="Network">
                    <span>{netText(metrics?.net)}</span>
                </Row>
                <Row label="Other devices">
                    <span>none connected</span>
                </Row>
            </>
        ),
    };

    return (
        <AnimatePresence>
            {settingsOpen && (
                <motion.aside
                    id="settings-panel"
                    className="panel right glass settings"
                    aria-label="System Control Center"
                    initial={{ opacity: 0, x: reducedMotion ? 0 : 24 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: reducedMotion ? 0 : 24 }}
                    transition={{ duration: reducedMotion ? 0 : DURATIONS.dur / 1000 }}
                >
                    <h2>SYSTEM CONTROL CENTER</h2>
                    <Tabs
                        label="Settings sections"
                        value={section}
                        onValueChange={(v) => setSection(v as Section)}
                        items={SECTIONS.map((sec) => ({ value: sec, label: SECTION_LABEL[sec], content: body[sec] }))}
                    />
                    <p className="settings-note" role="status" aria-live="polite">
                        {control && control !== 'done' ? RESULT[control] : ''}
                    </p>
                </motion.aside>
            )}
        </AnimatePresence>
    );
}
