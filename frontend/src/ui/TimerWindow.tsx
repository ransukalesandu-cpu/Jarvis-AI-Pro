import { useEffect } from 'react';
import { Pause, Play, RotateCcw } from 'lucide-react';
import { format, PRESETS_S, shown, useTimer, type TimerState, type TimerMode } from '../timer/timer';
import { useNow } from '../ux/usePhase';

export interface TimerViewProps extends TimerState {
  now: number;
  onStart: () => void; onPause: () => void; onReset: () => void; onMode: (m: TimerMode) => void; onPreset: (s: number) => void;
}

export function TimerView(p: TimerViewProps) {
  const secs = shown(p, p.now);
  return (
    <div className="timer">
      <div className="timer-modes" role="group" aria-label="Timer mode">
        {(['countdown', 'stopwatch'] as const).map((m) => <button key={m} className="toggle" aria-pressed={p.mode === m} onClick={() => p.onMode(m)}>{m === 'countdown' ? 'Countdown' : 'Stopwatch'}</button>)}
      </div>
      <div className="timer-face" data-finished={p.finished} role="timer" aria-label={p.mode === 'countdown' ? 'Time remaining' : 'Time elapsed'}>{format(secs)}</div>
      <p className="timer-status" role="status" aria-live="polite">{p.finished ? 'Time is up' : p.running ? 'Running' : secs === 0 || p.accumulated === 0 ? 'Ready' : 'Paused'}</p>
      {p.mode === 'countdown' && (
        <div className="timer-presets" role="group" aria-label="Countdown length">
          {PRESETS_S.map((s) => <button key={s} className="toggle" aria-pressed={p.target === s} disabled={p.running} onClick={() => p.onPreset(s)}>{s / 60} min</button>)}
        </div>
      )}
      <div className="timer-actions">
        {p.running
          ? <button className="toggle" onClick={p.onPause} aria-label="Pause timer"><Pause size={14} /> Pause</button>
          : <button className="toggle" onClick={p.onStart} aria-label="Start timer"><Play size={14} /> {p.accumulated > 0 && !p.finished ? 'Resume' : 'Start'}</button>}
        <button className="toggle" onClick={p.onReset} aria-label="Reset timer"><RotateCcw size={14} /> Reset</button>
      </div>
    </div>
  );
}

/** A real, local timer. No backend: it counts from timestamps, so minimising the window never loses time. */
export function TimerContent() {
  const s = useTimer();
  const now = useNow(s.running, 250);
  useEffect(() => { s.tick(now); }, [now]);   // eslint-disable-line react-hooks/exhaustive-deps
  return <TimerView {...s} now={s.running ? now : Date.now()} onStart={() => s.start()} onPause={() => s.pause()} onReset={s.reset} onMode={s.setMode} onPreset={s.setTarget} />;
}
