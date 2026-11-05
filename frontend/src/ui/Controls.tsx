import { Maximize, Mic, MicOff, Square } from 'lucide-react';
import { sendRequest } from '../bridge/bridge';
import type { ControlAction, CommandReason } from '../bridge/contract';
import { useUi } from '../store';
import { RESULT } from './CommandBar';

export interface ControlsProps { muted: boolean; busy: boolean; linked: boolean; result: CommandReason | null; onDo: (a: ControlAction) => void }

/** Interrupt / mic / fullscreen. Python decides; the buttons only ask. Unmuting is refused while locked or in guest mode. */
export function ControlsView({ muted, busy, linked, result, onDo }: ControlsProps) {
  const off = !linked;
  return (
    <div className="controls glass" role="toolbar" aria-label="Assistant controls">
      <button disabled={off || !busy} onClick={() => onDo('interrupt')} aria-label="Interrupt JARVIS" title="Interrupt"><Square size={15} /></button>
      <button disabled={off} onClick={() => onDo(muted ? 'unmute' : 'mute')} aria-pressed={muted}
        aria-label={muted ? 'Unmute microphone' : 'Mute microphone'} title={muted ? 'Unmute' : 'Mute'}>{muted ? <MicOff size={15} /> : <Mic size={15} />}</button>
      <button disabled={off} onClick={() => onDo('fullscreen')} aria-label="Toggle fullscreen" title="Fullscreen"><Maximize size={15} /></button>
      <span className="controls-note" role="status" aria-live="polite">{result && result !== 'done' ? RESULT[result] : ''}</span>
    </div>
  );
}

export function Controls() {
  const muted = useUi((s) => s.muted);
  const assistant = useUi((s) => s.assistant);
  const linked = useUi((s) => s.link) === 'connected';
  const result = useUi((s) => s.control);
  const busy = assistant === 'speaking' || assistant === 'thinking' || assistant === 'searching' || assistant === 'executing';
  return <ControlsView muted={muted} busy={busy} linked={linked} result={result} onDo={(action) => sendRequest({ kind: 'control.do', action })} />;
}
