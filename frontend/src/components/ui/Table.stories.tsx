import type { Meta, StoryObj } from '@storybook/react-vite';
import { Table, type Column } from './Table';

interface Job {
    id: string;
    name: string;
    state: string;
    secs: number;
}
const columns: Column<Job>[] = [
    { key: 'name', header: 'Job', cell: (r) => r.name },
    { key: 'state', header: 'State', cell: (r) => r.state },
    { key: 'secs', header: 'Time', cell: (r) => `${r.secs} s`, align: 'end' },
];
const rows: Job[] = [
    { id: '1', name: 'Backup notes', state: 'done', secs: 12 },
    { id: '2', name: 'Index Downloads', state: 'running', secs: 48 },
];
const meta: Meta<typeof Table<Job>> = {
    title: 'Primitives/Table',
    component: Table<Job>,
    args: { caption: 'Background jobs', columns, rows, rowKey: (r: Job) => r.id },
};
export default meta;
type S = StoryObj<typeof Table<Job>>;

export const Default: S = {};
export const Loading: S = { args: { loading: true } };
export const Empty: S = { args: { rows: [], emptyText: 'No background jobs this session.' } };
export const Error: S = { args: { error: 'Could not read the job list.', onRetry: () => {} } };
