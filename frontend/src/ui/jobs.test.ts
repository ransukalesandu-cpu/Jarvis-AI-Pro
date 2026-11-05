import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { parseHostEvent, type JobRow } from '../bridge/contract';
import { finishedNow } from '../store';
import { JobsView } from './Jobs';

const j = (o: unknown) => JSON.stringify(o);
const row = (id: string, status: JobRow['status'], extra: Partial<JobRow> = {}): JobRow => ({ id, name: `n-${id}`, status, startedAt: 1000, finishedAt: status === 'running' ? null : 5000, ...extra });
const noop = () => {};

describe('jobs.updated', () => {
  it('accepts valid rows and rejects extras, bad states and oversize lists', () => {
    expect(parseHostEvent(j({ type: 'jobs.updated', jobs: [row('job1', 'running')] }))?.type).toBe('jobs.updated');
    expect(parseHostEvent(j({ type: 'jobs.updated', jobs: [{ ...row('job1', 'running'), status: 'paused' }] }))).toBeNull();
    expect(parseHostEvent(j({ type: 'jobs.updated', jobs: [{ ...row('job1', 'running'), name: '' }] }))).toBeNull();
    expect(parseHostEvent(j({ type: 'jobs.updated', jobs: Array(21).fill(row('a', 'done')) }))).toBeNull();
  });
});

describe('finishedNow', () => {
  it('never notifies on the first snapshot, only for jobs that were running', () => {
    expect(finishedNow(null, [row('a', 'done')])).toEqual([]);
    const out = finishedNow([row('a', 'running'), row('b', 'done'), row('c', 'running')], [row('a', 'done'), row('b', 'done'), row('c', 'failed'), row('d', 'running')]);
    expect(out).toEqual(['Job “n-a” finished', 'Job “n-c” failed']);
    expect(finishedNow([row('a', 'running')], [row('a', 'cancelled')])).toEqual(['Job “n-a” was cancelled']);
  });
});

describe('JobsView', () => {
  it('distinguishes not reported, none, and a list with Cancel only for running jobs', () => {
    const v = (jobs: JobRow[] | null, result: JobsViewResult = null) => renderToStaticMarkup(createElement(JobsView, { jobs, now: 61_000, linked: true, result, onCancel: noop }));
    expect(v(null)).toContain('Not reported yet');
    expect(v([])).toContain('No background jobs');
    const h = v([row('a', 'running'), row('b', 'done')]);
    expect(h.match(/Cancel job/g)).toHaveLength(1); expect(h).toContain('Running · 01:00'); expect(h).toContain('Done · 00:04');
    expect(v([row('a', 'running')], 'rate_limited')).toContain('Too fast');
  });
});
type JobsViewResult = Parameters<typeof JobsView>[0]['result'];
