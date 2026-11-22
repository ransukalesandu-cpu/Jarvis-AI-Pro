import { useUi } from '../../store';
import { usePerf } from './perf';

/** Small readout of measured numbers. Shows "--" for anything not measured; nothing is estimated. */
export function PerfOverlay() {
  const on = useUi((s) => s.perfOverlay);
  const page = usePerf((s) => s.page);
  const host = usePerf((s) => s.host);
  if (!on) return null;
  const v = (x: number | null | undefined, unit = '') => (x === null || x === undefined ? '--' : `${x}${unit}`);
  return (
    <div className="perf-overlay" role="status" aria-label="Hologram performance">
      <div><b>FPS</b> {v(page?.fps)}</div>
      <div><b>Frame</b> {v(page?.frameMs, ' ms')}</div>
      <div><b>Draws</b> {v(page?.drawCalls)}</div>
      <div><b>Tris</b> {page ? (page.triangles / 1000).toFixed(1) + 'k' : '--'}</div>
      <div><b>DPR</b> {v(page?.dpr)}</div>
      <div><b>JS heap</b> {v(page?.heapMb, ' MB')}</div>
      <div><b>Web CPU</b> {host ? `${host.cpu.toFixed(1)}%` : '--'}</div>
      <div><b>Web RAM</b> {v(host?.ramMb, ' MB')}</div>
    </div>
  );
}
