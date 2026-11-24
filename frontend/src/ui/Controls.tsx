import { Maximize, Mic, MicOff, Square } from 'lucide-react';
import { sendRequest } from '../bridge/bridge';
import type { ControlAction, CommandReason } from '../bridge/contract';
import { useUi } from '../store';
import { useResultText } from './CommandBar';
import { useT } from '../i18n';
import { useFresh } from '../ux/useFresh';

export interface ControlsProps {
    muted: boolean;
    busy: boolean;
    linked: boolean;
    result: CommandReason | null;
    onDo: (a: ControlAction) => void;
}

/** Interrupt / mic / fullscreen. Python decides; the buttons only ask. Unmuting is refused while locked or in guest mode. */
export function ControlsView({ muted, busy, linked, result, onDo }: ControlsProps) {
    const off = !linked;
    const T = useT();
    const text = useResultText();
    return (
        <section className="region-wrap" aria-label={T('dock.panel')}>
            <div className="controls glass" role="toolbar" aria-label={T('dock.toolbar')}>
                <button disabled={off || !busy} onClick={() => onDo('interrupt')} aria-label={T('dock.interrupt')} title={T('dock.interrupt')}>
                    <Square size={15} />
                </button>
                <button
                    disabled={off}
                    onClick={() => onDo(muted ? 'unmute' : 'mute')}
                    aria-pressed={muted}
                    aria-label={muted ? T('dock.unmute') : T('dock.mute')}
                    title={muted ? T('dock.unmute') : T('dock.mute')}
                >
                    {muted ? <MicOff size={15} /> : <Mic size={15} />}
                </button>
                <button disabled={off} onClick={() => onDo('fullscreen')} aria-label={T('dock.fullscreen')} title={T('dock.fullscreen')}>
                    <Maximize size={15} />
                </button>
                <span className="controls-note" role="status" aria-live="polite">
                    {result && result !== 'done' ? text(result) : ''}
                </span>
            </div>
        </section>
    );
}

export function Controls() {
    const muted = useUi((s) => s.muted);
    const assistant = useUi((s) => s.assistant);
    const linked = useUi((s) => s.link) === 'connected';
    const result = useFresh(
        useUi((s) => s.control),
        useUi((s) => s.resultSeq),
    );
    const busy = assistant === 'speaking' || assistant === 'thinking' || assistant === 'searching' || assistant === 'executing';
    return <ControlsView muted={muted} busy={busy} linked={linked} result={result} onDo={(action) => sendRequest({ kind: 'control.do', action })} />;
}
