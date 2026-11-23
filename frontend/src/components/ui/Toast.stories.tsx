import type { Meta, StoryObj } from '@storybook/react-vite';
import { Button } from './Button';
import { Toaster, toast } from './Toast';

const meta: Meta<typeof Toaster> = { title: 'Primitives/Toast', component: Toaster };
export default meta;
type S = StoryObj<typeof Toaster>;

export const Default: S = {
    render: () => (
        <>
            <Button onClick={() => toast({ title: 'Saved', description: 'Layout saved on this PC.', tone: 'ok' })}>Success</Button>
            <Button tone="warn" onClick={() => toast({ title: 'Slow network', description: 'Retrying in 5 s.', tone: 'warn' })}>
                Warning
            </Button>
            <Button tone="danger" onClick={() => toast({ title: 'Could not reach the phone', tone: 'danger', action: { label: 'Retry', onClick: () => {} } })}>
                Error
            </Button>
            <Toaster />
        </>
    ),
};
