import { Maximize2, Minimize2, Minus, X } from 'lucide-react';
import { Rnd } from 'react-rnd';
import { MARGIN, MIN_H, MIN_W, TOP, TITLES, type WinKind } from '../workspace/layout';
import { titleOf, useWindows } from '../workspace/windows';
import { useUi } from '../store';
import { ActivityContent, ModelsContent, MonitorContent } from './Pages';

const CONTENT: Record<WinKind, () => React.ReactElement> = { monitor: MonitorContent, models: ModelsContent, activity: ActivityContent };

/** Floating glass windows. Closing a window only closes the view: backend tasks are never stopped by it. */
export function Windows() {
  const { windows, viewport, focus, move, resize, close, minimize, toggleMaximize } = useWindows();
  const reduced = useUi((s) => s.reducedMotion);
  const top = windows.reduce((m, w) => Math.max(m, w.z), 0);
  return (
    <>
      {windows.filter((w) => w.state !== 'minimized').map((w) => {
        const max = w.state === 'maximized';
        const Body = CONTENT[w.kind];
        return (
          <Rnd key={w.id} className={`win glass${w.z === top ? ' focused' : ''}`} style={{ zIndex: 20 + w.z, transition: reduced ? 'none' : undefined }}
            position={max ? { x: MARGIN, y: TOP } : { x: w.x, y: w.y }}
            size={max ? { width: viewport.w - 2 * MARGIN, height: viewport.h - TOP - MARGIN } : { width: w.w, height: w.h }}
            minWidth={MIN_W} minHeight={MIN_H} bounds="parent" dragHandleClassName="win-title" disableDragging={max} enableResizing={!max}
            onMouseDown={() => focus(w.id)} onDragStart={() => focus(w.id)}
            onDragStop={(_e, d) => move(w.id, d.x, d.y)}
            onResizeStop={(_e, _dir, el, _delta, pos) => resize(w.id, pos.x, pos.y, el.offsetWidth, el.offsetHeight)}>
            <section role="dialog" aria-label={TITLES[w.kind]} className="win-inner">
              <header className="win-title">
                <span>{titleOf(w)}</span>
                <span className="win-actions">
                  <button aria-label={`Minimize ${titleOf(w)}`} onClick={() => minimize(w.id)}><Minus size={14} /></button>
                  <button aria-label={max ? `Restore ${titleOf(w)}` : `Maximize ${titleOf(w)}`} onClick={() => toggleMaximize(w.id)}>{max ? <Minimize2 size={14} /> : <Maximize2 size={14} />}</button>
                  <button aria-label={`Close ${titleOf(w)}`} onClick={() => close(w.id)}><X size={14} /></button>
                </span>
              </header>
              <div className="win-body"><Body /></div>
            </section>
          </Rnd>
        );
      })}
    </>
  );
}

/** Minimised windows live in a small tray so nothing is lost and the hologram stays clear. */
export function Tray() {
  const { windows, restore } = useWindows();
  const min = windows.filter((w) => w.state === 'minimized');
  if (min.length === 0) return null;
  return (
    <div className="tray glass" role="toolbar" aria-label="Minimised windows">
      {min.map((w) => <button key={w.id} onClick={() => restore(w.id)} aria-label={`Restore ${titleOf(w)}`}>{titleOf(w)}</button>)}
    </div>
  );
}
