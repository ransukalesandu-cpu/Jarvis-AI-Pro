import { useEffect } from 'react';
import { usePending, type Op } from '../ux/pending';
import { formatRemaining, type Estimate, type Phase } from '../ux/phase';
import { usePhase, usePhaseOf, useNow } from '../ux/usePhase';

/** Placeholder shape of content that is on its way. Purely visual; hidden from assistive tech. */
export function Skeleton({ lines = 3, className = '' }: { lines?: number; className?: string }) {
  return (
    <div className={`skeleton ${className}`} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => <span key={i} className="sk-line" style={{ width: `${88 - ((i * 23) % 40)}%` }} />)}
    </div>
  );
}

/** Skeleton of the whole home page: the two widget columns. */
export function PageSkeleton() {
  return (
    <div className="page-skeleton" aria-hidden="true">
      {[0, 1].map((c) => <div key={c} className={`widgets ${c ? 'right' : 'left'}`}>{[0, 1, 2].map((i) => <div key={i} className="glass sk-card"><Skeleton lines={3} /></div>)}</div>)}
    </div>
  );
}

export function ProgressBar({ est, label }: { est: Estimate; label: string }) {
  return (
    <div className="progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(est.fraction * 100)}>
      <div className="progress-fill" style={{ width: `${Math.round(est.fraction * 100)}%` }} />
    </div>
  );
}

/** Pure view of the three rules: nothing under 1 s, a quiet label to 10 s, then progress and (estimated) time left. */
export function SyncStatusView({ phase, label, est }: { phase: Phase; label: string; est: Estimate | null }) {
  if (phase === 'none') return null;
  return (
    <div className="syncstatus glass" role="status" aria-live="polite" data-phase={phase}>
      <span>{label}…</span>
      {phase === 'progress' && est && <><ProgressBar est={est} label={label} /><span className="eta">{formatRemaining(est.remainingMs)} (estimate)</span></>}
    </div>
  );
}

function oldest(ops: Record<string, Op>): Op | undefined {
  return Object.values(ops).sort((a, b) => a.startedAt - b.startedAt)[0];
}

export function SyncStatus() {
  const op = usePending((s) => oldest(s.ops));
  const { phase, est } = usePhaseOf(op);
  return <SyncStatusView phase={phase} label={op?.label ?? ''} est={est} />;
}

/** Skeleton of the page while the first data is loading (1 s to 10 s; later the SyncStatus shows progress). */
export function useStartupLoading(): boolean {
  const a = usePhase('startup'); const b = usePhase('metrics');
  return a.phase !== 'none' || b.phase !== 'none';
}

export function StartupSkeleton() {
  return useStartupLoading() ? <PageSkeleton /> : null;
}

export function Toast() {
  const notice = usePending((s) => s.notice);
  useEffect(() => { if (!notice) return; const id = setTimeout(() => usePending.getState().dismiss(), 4000); return () => clearTimeout(id); }, [notice]);
  return <div className="toast-region" role="status" aria-live="polite">{notice && <div className="toast glass">{notice.text}</div>}</div>;
}

/** Drops operations that never answer; ticks only while something is pending. */
export function PendingWatch() {
  const any = usePending((s) => Object.keys(s.ops).length > 0);
  const now = useNow(any, 1000);
  useEffect(() => { if (any) usePending.getState().expireStale(now); }, [any, now]);
  return null;
}
