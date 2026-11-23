import type { Meta, StoryObj } from '@storybook/react-vite';
import { Tabs } from './Tabs';

const items = [
    { value: 'general', label: 'General', content: <p>Clock, Task Flow, centre.</p> },
    { value: 'voice', label: 'Voice', content: <p>Voice, wake word, offline voice.</p> },
    { value: 'devices', label: 'Devices', content: <p>Tablet and phone.</p> },
    { value: 'beta', label: 'Beta', content: <p>Not ready.</p>, disabled: true },
];
const meta: Meta<typeof Tabs> = { title: 'Primitives/Tabs', component: Tabs, args: { label: 'Settings sections', items } };
export default meta;
type S = StoryObj<typeof Tabs>;

export const Default: S = {};
export const Selected: S = { args: { defaultValue: 'voice' } };
export const Disabled: S = { args: { items: items.map((i) => ({ ...i, disabled: i.value !== 'general' })) } };
