import type { Meta, StoryObj } from '@storybook/react-vite';
import { Button } from './Button';
import { Dialog, Sheet } from './Dialog';
import { Input } from './Input';

const meta: Meta<typeof Dialog> = {
    title: 'Primitives/Dialog',
    component: Dialog,
    args: { title: 'Rename routine', description: 'Routines start with their trigger phrase.', defaultOpen: true },
};
export default meta;
type S = StoryObj<typeof Dialog>;

const footer = (
    <>
        <Button variant="ghost" tone="neutral">
            Cancel
        </Button>
        <Button>Save</Button>
    </>
);
export const Default: S = { args: { trigger: <Button>Open</Button>, children: <Input label="Name" defaultValue="morning" />, footer } };
export const Error: S = { args: { children: <Input label="Name" defaultValue="" error="A routine needs a name." />, footer } };
export const Loading: S = {
    args: {
        children: <Input label="Name" defaultValue="morning" disabled />,
        footer: (
            <>
                <Button variant="ghost" tone="neutral" disabled>
                    Cancel
                </Button>
                <Button loading>Saving</Button>
            </>
        ),
    },
};
export const SheetRight: S = {
    render: (a) => (
        <Sheet {...a} title="Phone" description="Live screen and controls.">
            <p>Phone is online over Tailscale.</p>
        </Sheet>
    ),
};
export const SheetBottom: S = {
    render: (a) => (
        <Sheet {...a} side="bottom" title="Windows">
            <p>Bottom sheet on small screens.</p>
        </Sheet>
    ),
};
