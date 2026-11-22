import { AppWindow, Brain, Check, FileText, Globe, LayoutGrid, Mic, MousePointer2, Scan, Search, Send, Sparkles, Terminal, Wrench, X, ZoomIn, ZoomOut } from 'lucide-react';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { Flow, FlowStep } from '../bridge/contract';
import { counts, elapsed, type FlowLogLine } from './flows';
import { BRAIN_H, BRAIN_W, STEP_H, STEP_W, WIRE, autoLayout, bounds, fitView, wire, type Pos, type View } from './layout';

/** Picks an icon from the tool name. Only a hint for the eye; the chip shows the real name. */
function StepIcon({ tool }: { tool: string }) {
  const t = tool.toLowerCase();
  const p = { size: 17, strokeWidth: 1.8 };
  if (/search|find|lookup|recall/.test(t)) return <Search {...p} />;
  if (/web|browser|url|news|youtube/.test(t)) return <Globe {...p} />;
  if (/file|read|write|doc|pdf/.test(t)) return <FileText {...p} />;
  if (/app|open|launch|window/.test(t)) return <AppWindow {...p} />;
  if (/send|message|mail|phone|whatsapp/.test(t)) return <Send {...p} />;
  if (/speak|voice|tts|music|audio/.test(t)) return <Mic {...p} />;
  if (/claude|ask|reason|plan|catalog|registry/.test(t)) return <Sparkles {...p} />;
  if (/^cc\.|click|type|screen|ui_|desktop|computer/.test(t)) return <MousePointer2 {...p} />;
  if (/command|shell|run|terminal|code/.test(t)) return <Terminal {...p} />;
  return <Wrench {...p} />;
}

export function useNow(active: boolean, ms = 200): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) { setNow(Date.now()); return; }
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [active, ms]);
  return now;
}

const WIRE_STATE: Record<FlowStep['status'], string> = { pending: 'pending', running: 'running', done: 'done', error: 'err', skipped: 'skip' };

interface Props { flow: Flow; log: FlowLogLine[]; whole: boolean; reduced: boolean }

/** The node canvas: brain + one card per step, joined by coloured wires. Pan by dragging the grid, wheel to zoom, drag cards. */
export function FlowCanvas({ flow, log, whole, reduced }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [moved, setMoved] = useState<Record<string, Pos>>({});
  const [view, setView] = useState<View>({ x: 0, y: 0, s: 1 });
  const [userView, setUserView] = useState(false);
  const [smooth, setSmooth] = useState(true);
  const running = flow.state === 'running';
  const now = useNow(running);
  const n = flow.steps.length;
  const auto = useMemo(() => autoLayout(n), [n]);
  const brain = moved.brain ?? auto.brain;
  const steps = flow.steps.map((s, i) => moved[s.id] ?? auto.steps[i]);
  const c = counts(flow);
  const current = flow.steps.find((s) => s.status === 'running');
  const focusIdx = current ? flow.steps.indexOf(current) : n - 1;

  useEffect(() => { setMoved({}); setUserView(false); }, [flow.id]);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    if (userView) return;
    const fy = focusIdx >= 0 && steps[focusIdx] ? steps[focusIdx].y + STEP_H / 2 : null;
    setSmooth(true);
    setView(fitView(bounds(brain, steps), size.w, size.h - 40, whole, fy));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size.w, size.h, whole, n, focusIdx, userView, flow.id]);

  const zoom = (f: number, cx = size.w / 2, cy = size.h / 2) => {
    setUserView(true);
    setView((v) => { const s = Math.max(0.3, Math.min(2, v.s * f)); return { s, x: cx - (cx - v.x) * (s / v.s), y: cy - (cy - v.y) * (s / v.s) }; });
  };
  const onWheel = (e: React.WheelEvent) => { const r = box.current!.getBoundingClientRect(); setSmooth(false); zoom(e.deltaY < 0 ? 1.1 : 1 / 1.1, e.clientX - r.left, e.clientY - r.top); };
  const drag = (e: React.PointerEvent, onMove: (dx: number, dy: number) => void) => {
    const sx = e.clientX, sy = e.clientY;
    setSmooth(false);
    const mv = (ev: PointerEvent) => onMove(ev.clientX - sx, ev.clientY - sy);
    const up = () => { removeEventListener('pointermove', mv); removeEventListener('pointerup', up); };
    addEventListener('pointermove', mv); addEventListener('pointerup', up);
  };
  const panStart = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest('.tf-node, .tf-tools')) return;
    const o = view;
    drag(e, (dx, dy) => { setUserView(true); setView({ ...o, x: o.x + dx, y: o.y + dy }); });
  };
  const nodeStart = (id: string, from: Pos) => (e: React.PointerEvent) => {
    e.stopPropagation();
    drag(e, (dx, dy) => { setUserView(true); setMoved((m) => ({ ...m, [id]: { x: from.x + dx / view.s, y: from.y + dy / view.s } })); });
  };

  return (
    <div className={`tf-canvas${reduced ? ' calm' : ''}`} ref={box} onWheel={onWheel} onPointerDown={panStart}>
      <div className={`tf-world${smooth && !reduced ? ' smooth' : ''}`} style={{ transform: `translate(${view.x}px,${view.y}px) scale(${view.s})` }}>
        <svg className="tf-wires" aria-hidden>
          {flow.steps.map((s, i) => { const w = wire(brain, steps[i], i, n); const col = s.status === 'error' ? 'var(--danger)' : WIRE[i % WIRE.length];
            return <path key={`g${s.id}`} className={`tf-glow ${WIRE_STATE[s.status]}`} d={w.d} stroke={col} />; })}
          {flow.steps.map((s, i) => { const w = wire(brain, steps[i], i, n); const col = s.status === 'error' ? 'var(--danger)' : WIRE[i % WIRE.length];
            const dim = s.status === 'pending' || s.status === 'skipped';
            return (
              <g key={s.id}>
                <path id={`tfw-${flow.id}-${s.id}`} className={`tf-wire ${WIRE_STATE[s.status]}`} d={w.d} stroke={col} />
                <circle cx={w.x1} cy={w.y1} r={2.6} fill={col} opacity={dim ? 0.25 : 1} />
                <circle cx={w.x2} cy={w.y2} r={4} fill="#0a0e18" stroke={col} strokeWidth={2} opacity={dim ? 0.25 : 1} />
                {s.status === 'running' && !reduced && (
                  <circle r={3.2} fill="#fff" style={{ filter: `drop-shadow(0 0 5px ${col})` }}>
                    <animateMotion dur="1.1s" repeatCount="indefinite"><mpath href={`#tfw-${flow.id}-${s.id}`} /></animateMotion>
                  </circle>
                )}
              </g>
            );
          })}
        </svg>

        <div className={`tf-node tf-brain${running ? ' running' : ''}`} style={{ left: brain.x, top: brain.y, width: BRAIN_W, height: BRAIN_H }} onPointerDown={nodeStart('brain', brain)}>
          <div className="tf-bhd">
            <span className="tf-logo"><Brain size={16} /></span>
            <span><b>JARVIS</b><small>{flow.source === 'agent' ? 'AUTONOMOUS TASK' : 'NEURAL CORE'}</small></span>
            <span className="tf-sig" aria-hidden><i /><i /><i /><i /></span>
          </div>
          <div className="tf-stats">
            <div><b>{c.total}</b><span>STEPS</span></div><div><b>{c.done}</b><span>DONE</span></div><div><b>{c.errors}</b><span>ERRORS</span></div>
          </div>
          <div className="tf-now">
            <p><span className="tf-dot" data-state={flow.state} /><span>{current ? current.label : flow.state === 'running' ? (n ? 'Working…' : 'Planning…') : flow.state === 'done' ? 'Task complete' : flow.state === 'failed' ? 'Task failed' : 'Stopped'}</span></p>
            <div className="tf-pb"><i style={{ width: `${flow.state === 'done' ? 100 : c.total ? (c.done / c.total) * 100 : 4}%` }} /></div>
          </div>
          <div className="tf-log" aria-label="Activity">
            <h6>ACTIVITY</h6>
            {log.slice(-5).map((l, i) => <p key={i} className={l.level}><em>{elapsed(flow.startedAt, l.at, now)}</em>{l.text}</p>)}
          </div>
        </div>

        {flow.steps.map((s, i) => (
          <div key={s.id} className={`tf-node tf-step ${s.status}`} style={{ left: steps[i].x, top: steps[i].y, width: STEP_W, height: STEP_H, ['--c' as string]: WIRE[i % WIRE.length] }}
            onPointerDown={nodeStart(s.id, steps[i])}>
            <div className="tf-top">
              <div className="tf-thumb"><StepIcon tool={s.tool} /></div>
              <div className="tf-txt"><b title={s.label}>{s.label}</b><span className="tf-chip">{s.tool}</span></div>
            </div>
            <div className="tf-ft">
              <span className={`tf-badge ${s.status}`}>{s.status === 'done' ? <Check size={9} strokeWidth={3} /> : s.status === 'error' ? <X size={9} strokeWidth={3} /> : null}</span>
              <span className="tf-detail" title={s.detail}>{s.detail}</span>
              <span className="tf-time">{s.startedAt ? elapsed(s.startedAt, s.finishedAt, now) : ''}</span>
            </div>
          </div>
        ))}
      </div>
      {n === 0 && flow.state === 'running' && <div className="tf-empty">Planning the steps…</div>}

      <div className="tf-tools" role="toolbar" aria-label="Canvas">
        <button onClick={() => { setUserView(false); }} aria-label="Fit to view" title="Fit"><Scan size={13} /></button>
        <button onClick={() => { setSmooth(true); zoom(1 / 1.2); }} aria-label="Zoom out"><ZoomOut size={13} /></button>
        <span className="tf-zoom">{Math.round(view.s * 100)}%</span>
        <button onClick={() => { setSmooth(true); zoom(1.2); }} aria-label="Zoom in"><ZoomIn size={13} /></button>
        <span className="tf-sep" />
        <button onClick={() => { setMoved({}); setUserView(false); }} aria-label="Auto layout"><LayoutGrid size={13} /><span className="tf-lbl">Auto layout</span></button>
      </div>
    </div>
  );
}

