import { sendRequest } from '../bridge/bridge';
import { RESULT } from './CommandBar';
import type { ControlAction } from '../bridge/contract';
import { useUi } from '../store';
import { motion, AnimatePresence } from 'motion/react';
import { useFresh } from '../ux/useFresh';
import { useFlows } from '../taskflow/flows';
import { useWindows } from '../workspace/windows';

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

/** Only settings that actually do something are interactive; the rest are listed as not yet connected. */
export function SettingsPanel() {
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
    } = useUi();
    const control = useFresh(rawControl, resultSeq);
    const autoShow = useFlows((s) => s.autoShow);
    const saved = link === 'connected' ? 'Saved on this PC' : 'Not saved: backend not connected';
    return (
        <AnimatePresence>
            {settingsOpen && (
                <motion.aside
                    id="settings-panel"
                    className="panel right glass"
                    aria-label="Settings"
                    initial={{ opacity: 0, x: reducedMotion ? 0 : 24 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: reducedMotion ? 0 : 24 }}
                    transition={{ duration: reducedMotion ? 0 : 0.22 }}
                >
                    <h2>APPEARANCE &amp; GLASS UI</h2>
                    <div className="row">
                        <span>Reduced motion</span>
                        <button className="toggle" aria-pressed={reducedMotion} onClick={() => setReducedMotion(!reducedMotion)}>
                            {reducedMotion ? 'On' : 'Off'}
                        </button>
                    </div>
                    <div className="row">
                        <span>24-hour clock</span>
                        <button className="toggle" aria-pressed={clock24} onClick={() => setClock24(!clock24)}>
                            {clock24 ? 'On' : 'Off'}
                        </button>
                    </div>
                    <div className="row">
                        <span>Show Task Flow on new tasks</span>
                        <button className="toggle" aria-pressed={autoShow} onClick={() => useFlows.getState().setAutoShow(!autoShow)}>
                            {autoShow ? 'On' : 'Off'}
                        </button>
                    </div>
                    <p className="settings-note">{saved}</p>
                    <h2>HOLOGRAM</h2>
                    <div className="row">
                        <span>Persona</span>
                        <span className="seg" role="group" aria-label="Persona">
                            {PERSONA_OPTS.map((o) => (
                                <button
                                    key={o.action}
                                    className="toggle"
                                    aria-pressed={persona === o.id}
                                    disabled={link !== 'connected'}
                                    onClick={() => ask(o.action)}
                                >
                                    {o.label}
                                </button>
                            ))}
                        </span>
                    </div>
                    <div className="row">
                        <span>
                            Performance tier <small>({perfTier ?? 'not reported'})</small>
                        </span>
                        <span className="seg" role="group" aria-label="Performance tier">
                            {PERF_OPTS.map((o) => (
                                <button
                                    key={o.action}
                                    className="toggle"
                                    aria-pressed={o.label.toLowerCase() === perfTier}
                                    disabled={link !== 'connected'}
                                    onClick={() => ask(o.action)}
                                >
                                    {o.label}
                                </button>
                            ))}
                        </span>
                    </div>
                    <div className="row">
                        <span>Centre</span>
                        <span className="seg" role="group" aria-label="Centre">
                            {(['brain', 'hologram'] as const).map((c) => (
                                <button key={c} className="toggle" aria-pressed={centerStyle === c} onClick={() => setCenterStyle(c)}>
                                    {c === 'brain' ? 'Neural brain' : 'Hologram head'}
                                </button>
                            ))}
                        </span>
                    </div>
                    {centerStyle === 'hologram' && (
                        <div className="row">
                            <span>Face style</span>
                            <span className="seg" role="group" aria-label="Face style">
                                {(['circuit', 'mechanical'] as const).map((f) => (
                                    <button key={f} className="toggle" aria-pressed={faceStyle === f} onClick={() => setFaceStyle(f)}>
                                        {f === 'circuit' ? 'Circuit' : 'Mechanical'}
                                    </button>
                                ))}
                            </span>
                        </div>
                    )}
                    <div className="row">
                        <span>
                            Performance overlay <small>(measured FPS, frame time, draw calls, memory)</small>
                        </span>
                        <button className="toggle" aria-pressed={perfOverlay} onClick={() => setPerfOverlay(!perfOverlay)}>
                            {perfOverlay ? 'On' : 'Off'}
                        </button>
                    </div>
                    <p className="settings-note" role="status" aria-live="polite">
                        {control && control !== 'done' ? RESULT[control] : ''}
                    </p>
                    <h2>CONNECTION</h2>
                    <div className="row">
                        <span>Backend link</span>
                        <span>{link}</span>
                    </div>
                    <h2>MORE</h2>
                    <div className="row">
                        <span>Knowledge, notes, Telegram, providers, backup…</span>
                        <button
                            className="toggle"
                            onClick={() => {
                                useWindows.getState().open('features');
                                toggleSettings(false);
                            }}
                        >
                            Features Hub
                        </button>
                    </div>
                </motion.aside>
            )}
        </AnimatePresence>
    );
}
