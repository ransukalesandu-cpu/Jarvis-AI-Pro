import type { Meta, StoryObj } from '@storybook/react-vite';
import { Select } from './Select';

const options = [
    { value: 'gemini', label: 'Gemini Live' },
    { value: 'claude', label: 'Claude' },
    { value: 'ollama', label: 'Local (Ollama)' },
    { value: 'off', label: 'Off', disabled: true },
];
const meta: Meta<typeof Select> = {
    title: 'Primitives/Select',
    component: Select,
    args: { label: 'Text brain', options },
};
export default meta;
type S = StoryObj<typeof Select>;

export const Default: S = {};
export const Selected: S = { args: { defaultValue: 'claude' } };
export const Invalid: S = { args: { error: 'Choose a provider.' } };
export const Disabled: S = { args: { disabled: true, defaultValue: 'gemini' } };
export const Empty: S = { args: { options: [], emptyText: 'No providers configured' } };
export const WithHint: S = { args: { hint: 'Used when Gemini Live is down.' } };
