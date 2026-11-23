import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { sendRequest } from '../../bridge/bridge';
import { useUi } from '../../store';
import { heapMb, usePerf } from './perf';
import type { Quality } from './quality';
import { dprRange, FrameBudget } from './scheduler';

const REPORT_MS = 2000;

/**
 * Lives inside the Canvas. Measures every frame, adapts DPR to the frame budget, publishes the
 * numbers for the overlay and, only while the overlay is open, reports them to the host (which
 * answers with the web engine process's CPU and RAM).
 */
export function PerfGovernor({ quality }: { quality: Quality }) {
  const gl = useThree((s) => s.gl);
  const setDpr = useThree((s) => s.setDpr);
  const range = dprRange(quality.dpr);
  const budget = useMemo(() => new FrameBudget(range, quality.fpsCap ?? 60), [range[0], range[1], quality.fpsCap]);   // eslint-disable-line react-hooks/exhaustive-deps
  const publishedAt = useRef(0);
  const reportedAt = useRef(0);

  useEffect(() => { setDpr(budget.current); }, [budget, setDpr]);

  useFrame((_s, delta) => {
    const changed = budget.frame(delta * 1000);
    if (changed !== null) setDpr(changed);
    const now = performance.now();
    const st = budget.stats;
    if (st.fps === 0 || now - publishedAt.current < 1000) return;     // publish once a second
    publishedAt.current = now;
    const info = gl.info.render;
    const page = { fps: st.fps, frameMs: st.frameMs, drawCalls: info.calls, triangles: info.triangles, heapMb: heapMb(), dpr: budget.current };
    usePerf.getState().setPage(page);
    if (useUi.getState().perfOverlay && now - reportedAt.current >= REPORT_MS) {
      reportedAt.current = now;
      sendRequest({ kind: 'hologram.perf', ...page });
    }
  });
  return null;
}
