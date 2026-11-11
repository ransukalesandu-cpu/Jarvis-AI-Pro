import { X } from 'lucide-react';
import { sendRequest } from '../bridge/bridge';
import { isActiveJob, type CommandReason, type JobRow } from '../bridge/contract';
import { useUi } from '../store';
import { format } from '../timer/timer';
import { useNow } from '../ux/usePhase';
import { RESULT } from './CommandBar';

const LABEL = { running: 'Running', done: 'Done', failed: 'Failed', cancelled: 'Cancelled', waiting: 'Waiting', paused: 'Paused' } as const;

export interface JobsProps { jobs: JobRow[] | null; now: number; linked: boolean; result: CommandReason | null; onCancel: (id: string) => void }

/** Background jobs and autonomous tasks reported by Python (no results or descriptions are sent). Cancel asks Python to stop a job it lists as active. */
export function JobsView({ jobs, now, linked, result, onCancel }: JobsProps) {
  return (
    <>
      <h1>Background Jobs</h1>
      <p>Long tasks JARVIS runs in the background, including autonomous tasks. Finished jobs show a notice here.</p>
      {jobs === null ? <p>Not reported yet.</p> : jobs.length === 0 ? <p>No background jobs.</p> : (
        <ul className="news-list">
          {jobs.map((j) => {
            const secs = Math.max(0, Math.round(((j.finishedAt ?? now) - j.startedAt) / 1000));
            return (
              <li key={j.id} className="news-item">
                <span className="news-title">{j.name}</span>
                <span className="news-source">{LABEL[j.status]} · {format(secs)}</span>
                {isActiveJob(j.status) && <button className="toggle" disabled={!linked} onClick={() => onCancel(j.id)} aria-label={`Cancel job ${j.name}`}><X size={12} /> Cancel</button>}
              </li>
            );
          })}
        </ul>
      )}
      <p className="settings-note" role="status" aria-live="polite">{result && result !== 'done' ? RESULT[result] : ''}</p>
    </>
  );
}

export function JobsContent() {
  const jobs = useUi((s) => s.jobs);
  const linked = useUi((s) => s.link) === 'connected';
  const result = useUi((s) => s.control);
  const now = useNow(!!jobs?.some((j) => isActiveJob(j.status)), 1000);
  return <JobsView jobs={jobs} now={now} linked={linked} result={result} onCancel={(id) => sendRequest({ kind: 'job.cancel', id })} />;
}
