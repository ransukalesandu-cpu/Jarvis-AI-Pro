import type { Meta, StoryObj } from '@storybook/react-vite';
import { StateView } from './StateView';

const meta: Meta<typeof StateView> = { title: 'Primitives/StateView', component: StateView, args: { title: 'Background jobs' } };
export default meta;
type S = StoryObj<typeof StateView>;

export const Loading: S = { args: { kind: 'loading' } };
export const Empty: S = { args: { kind: 'empty', title: 'No background jobs', message: 'Long tasks you give JARVIS show up here.' } };
export const Error: S = { args: { kind: 'error', title: 'Could not read the job list', message: 'The backend did not answer.', onRetry: () => {} } };
export const Offline: S = { args: { kind: 'offline', title: 'JARVIS is not connected', message: 'Start JARVIS to see live data.' } };
export const Success: S = { args: { kind: 'success', title: 'Job cancelled' } };
