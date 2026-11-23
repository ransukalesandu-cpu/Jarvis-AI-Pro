import type { Meta, StoryObj } from '@storybook/react-vite';
import { Checkbox } from './Checkbox';

const meta: Meta<typeof Checkbox> = { title: 'Primitives/Checkbox', component: Checkbox, args: { label: 'Show Task Flow on new tasks' } };
export default meta;
type S = StoryObj<typeof Checkbox>;

export const Default: S = {};
export const Checked: S = { args: { defaultChecked: true } };
export const Indeterminate: S = { args: { checked: 'indeterminate' } };
export const Disabled: S = { args: { disabled: true, defaultChecked: true } };
export const Invalid: S = { args: { error: 'Required for Full Access.' } };
export const WithHint: S = { args: { hint: 'The window hides after 5 s.' } };
