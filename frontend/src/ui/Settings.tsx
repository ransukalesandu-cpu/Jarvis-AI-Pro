import { useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
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

function Toggle({ on, onClick, disabled }: { on: boolean; onClick: () => void; disabled?: boolean }) {
    return (
        <button className="toggle" aria-pressed={on} onClick={onClick} disabled={disabled}>
            {on ? 'On' : 'Off'}
        </button>
    );
}

/** Tabs with arrow-key, Home and End movement (WAI-ARIA tabs pattern). */
function SectionTabs({ value, onChange }: { value: Section; onChange: (s: Section) => void }) {
    const refs = useRef<Partial<Record<Section, HTMLButtonElement | null>>>({});
    const move = (e: KeyboardEvent, i: number) => {
        const last = SECTIONS.length - 1;
        const to =
            e.key === 'ArrowRight'
                ? i === last
                    ? 0
                    : i + 1
                : e.key === 'ArrowLeft'
                  ? i === 0
                      ? last
                      : i - 1
                  : e.key === 'Home'
                    ? 0
                    : e.key === 'End'
                      ? last
                      : -1;
        if (to < 0) return;
        e.preventDefault();
        onChange(SECTIONS[to]);
        refs.current[SECTIONS[to]]?.focus();
    };
    return (
        <div className="settings-tabs" role="tablist" aria-label="Settings sections">
            {SECTIONS.map((s, i) => (
                <button
                    key={s}
                    ref={(el) => {
                        refs.current[s] = el;
                    }}
                    id={`settings-tab-${s}`}
                    role="tab"
                    aria-selected={value === s}
                    aria-controls="settings-section"
                    tabIndex={value === s ? 0 : -1}
                    className="settings-tab"
                    onClick={() => onChange(s)}
                    onKeyDown={(e) => move(e, i)}
                >
                    {SECTION_LABEL[s]}
                </button>
            ))}
        </div>
    );
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
                    <Toggle on={reducedMotion} onClick={() => setReducedMotion(!reducedMotion)} />
                </Row>
                <Row label="24-hour clock">
                    <Toggle on={clock24} onClick={() => setClock24(!clock24)} />
                </Row>
                <Row label="Show Task Flow on new tasks">
                    <Toggle on={autoShow} onClick={() => useFlows.getState().setAutoShow(!autoShow)} />
                </Row>
                <Row label="Centre">
                    <span className="seg" role="group" aria-label="Centre">
                        {(['brain', 'hologram'] as const).map((c) => (
                            <button key={c} className="toggle" aria-pressed={centerStyle === c} onClick={() => setCenterStyle(c)}>
                                {c === 'brain' ? 'Neural brain' : 'Hologram head'}
                            </button>
                        ))}
                    </span>
                </Row>
                {centerStyle === 'hologram' && (
                    <Row label="Face style">
                        <span className="seg" role="group" aria-label="Face style">
                            {(['circuit', 'mechanical'] as const).map((f) => (
                                <button key={f} className="toggle" aria-pressed={faceStyle === f} onClick={() => setFaceStyle(f)}>
                                    {f === 'circuit' ? 'Circuit' : 'Mechanical'}
                                </button>
                            ))}
                        </span>
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
                    <button
                        className="toggle"
                        onClick={() => {
                            useWindows.getState().open('features');
                            toggleSettings(false);
                        }}
                    >
                        Features Hub
                    </button>
                </Row>
                <p className="settings-note">Keys stay in Python and are never sent to this page.</p>
            </>
        ),
        voice: (
            <>
                <Row label="Microphone">
                    <button className="toggle" aria-pressed={up && !muted} disabled={!up} onClick={() => ask(muted ? 'unmute' : 'mute')}>
                        {!up ? 'Unknown' : muted ? 'Muted' : 'On'}
                    </button>
                </Row>
                <Row label="Voice state">
                    <span>{vs}</span>
                </Row>
                <Row label="Persona and voice">
                    <span className="seg" role="group" aria-label="Persona">
                        {PERSONA_OPTS.map((o) => (
                            <button key={o.action} className="toggle" aria-pressed={persona === o.id} disabled={!up} onClick={() => ask(o.action)}>
                                {o.label}
                            </button>
                        ))}
                    </span>
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
                    <span className="seg" role="group" aria-label="Rendering quality">
                        {PERF_OPTS.map((o) => (
                            <button
                                key={o.action}
                                className="toggle"
                                aria-pressed={o.label.toLowerCase() === perfTier}
                                disabled={!up}
                                onClick={() => ask(o.action)}
                            >
                                {o.label}
                            </button>
                        ))}
                    </span>
                </Row>
                <Row
                    label={
                        <>
                            Performance overlay <small>(measured FPS, frame time, draw calls, memory)</small>
                        </>
                    }
                >
                    <Toggle on={perfOverlay} onClick={() => setPerfOverlay(!perfOverlay)} />
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
                    transition={{ duration: reducedMotion ? 0 : 0.22 }}
                >
                    <h2>SYSTEM CONTROL CENTER</h2>
                    <SectionTabs value={section} onChange={setSection} />
                    <div id="settings-section" role="tabpanel" aria-labelledby={`settings-tab-${section}`}>
                        {body[section]}
                    </div>
                    <p className="settings-note" role="status" aria-live="polite">
                        {control && control !== 'done' ? RESULT[control] : ''}
                    </p>
                </motion.aside>
            )}
        </AnimatePresence>
    );
}
