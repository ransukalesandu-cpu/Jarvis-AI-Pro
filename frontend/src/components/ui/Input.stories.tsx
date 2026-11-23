import type { Meta, StoryObj } from '@storybook/react-vite';
import { Input, Textarea } from './Input';

const meta: Meta<typeof Input> = {
    title: 'Primitives/Input',
    component: Input,
    args: { label: 'Task name', placeholder: 'e.g. Weekly report' },
};
export default meta;
type S = StoryObj<typeof Input>;

export const Default: S = {};
export const Filled: S = { args: { defaultValue: 'Weekly report' } };
export const Focus: S = { args: { autoFocus: true } };
export const WithHint: S = { args: { hint: 'Shown in the Task Progress window.' } };
export const Invalid: S = { args: { defaultValue: '', error: 'Give the task a name.' } };
export const Disabled: S = { args: { disabled: true, defaultValue: 'Locked while JARVIS is busy' } };
export const Loading: S = { args: { loading: true, defaultValue: 'Checking…' } };
export const Sizes: S = {
    render: (a) => (
        <>
            <Input {...a} size="sm" label="Small" />
            <Input {...a} size="md" label="Medium" />
            <Input {...a} size="lg" label="Large" />
        </>
    ),
};
export const TextareaDefault: S = { render: () => <Textarea label="Notes" placeholder="Anything JARVIS should know" /> };
export const TextareaInvalid: S = { render: () => <Textarea label="Notes" error="Keep it under 400 characters." defaultValue="…" /> };
