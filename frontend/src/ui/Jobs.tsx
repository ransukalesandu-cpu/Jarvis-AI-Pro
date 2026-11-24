import { X } from 'lucide-react';
import { sendRequest } from '../bridge/bridge';
import type { CommandReason, JobRow } from '../bridge/contract';
import { useUi } from '../store';
import { format } from '../timer/timer';
import { useNow } from '../ux/usePhase';
import { ResultNote } from './CommandBar';
import { Button, StateView } from '../components/ui';

const LABEL = { running: 'Running', done: 'Done', failed: 'Failed', cancelled: 'Cancelled' } as const;

export interface JobsProps {
    jobs: JobRow[] | null;
    now: number;
    linked: boolean;
    result: CommandReason | null;
    onCancel: (id: string) => void;
}

/** Background jobs reported by Python (no results or descriptions are sent). Cancel asks Python to stop a job it lists as running. */
export function JobsView({ jobs, now, linked, result, onCancel }: JobsProps) {
    return (
        <>
            <h1 className="ui-sr-only">Background Jobs</h1>
            <p>Long tasks JARVIS runs in the background. Finished jobs show a notice here.</p>
            {jobs === null ? (
                linked ? (
                    <StateView kind="loading" title="Loading background jobs" />
                ) : (
                    <StateView kind="offline" title="JARVIS is not connected" message="Background jobs appear when JARVIS is running." />
                )
            ) : jobs.length === 0 ? (
                <StateView kind="empty" title="No background jobs" message="Long tasks you give JARVIS show up here." />
            ) : (
                <ul className="news-list">
                    {jobs.map((j) => {
                        const secs = Math.max(0, Math.round(((j.finishedAt ?? now) - j.startedAt) / 1000));
                        return (
                            <li key={j.id} className="news-item">
                                <span className="news-title">{j.name}</span>
                                <span className="news-source">
                                    {LABEL[j.status]} · {format(secs)}
                                </span>
                                {j.status === 'running' && (
                                    <Button
                                        variant="outline"
                                        tone="danger"
                                        size="sm"
                                        disabled={!linked}
                                        onClick={() => onCancel(j.id)}
                                        aria-label={`Cancel job ${j.name}`}
                                        icon={<X size={12} aria-hidden />}
                                    >
                                        Cancel
                                    </Button>
                                )}
                            </li>
                        );
                    })}
                </ul>
            )}
            <ResultNote result={result} />
        </>
    );
}

export function JobsContent() {
    const jobs = useUi((s) => s.jobs);
    const linked = useUi((s) => s.link) === 'connected';
    const result = useUi((s) => s.control);
    const now = useNow(!!jobs?.some((j) => j.status === 'running'), 1000);
    return <JobsView jobs={jobs} now={now} linked={linked} result={result} onCancel={(id) => sendRequest({ kind: 'job.cancel', id })} />;
}
