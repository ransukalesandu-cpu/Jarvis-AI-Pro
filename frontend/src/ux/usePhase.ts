import { useEffect, useState } from 'react';
import { durations, usePending, type Op } from './pending';
import { estimate, phaseFor, type Estimate, type Phase } from './phase';

export function useNow(active: boolean, everyMs = 250): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(id);
  }, [active, everyMs]);
  return now;
}

export interface PhaseInfo { phase: Phase; elapsedMs: number; est: Estimate | null }

/** Phase of one operation (or none). Ticks only while the operation is pending. */
export function usePhaseOf(op: Op | undefined): PhaseInfo {
  const now = useNow(!!op);
  if (!op) return { phase: 'none', elapsedMs: 0, est: null };
  const elapsedMs = Math.max(0, now - op.startedAt);
  const phase = phaseFor(elapsedMs);
  return { phase, elapsedMs, est: phase === 'progress' ? estimate(elapsedMs, durations.expected(op.kind)) : null };
}

export const usePhase = (id: string): PhaseInfo => usePhaseOf(usePending((s) => s.ops[id]));
