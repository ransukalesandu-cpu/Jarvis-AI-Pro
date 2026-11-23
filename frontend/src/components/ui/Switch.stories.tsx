import type { Meta, StoryObj } from '@storybook/react-vite';
import { useState } from 'react';
import { Segmented, Switch } from './Switch';

const meta: Meta<typeof Switch> = { title: 'Primitives/Switch & Segmented', component: Switch };
export default meta;
type S = StoryObj<typeof Switch>;

function Live(props: { initial: boolean; disabled?: boolean }) {
    const [on, setOn] = useState(props.initial);
    return <Switch label="Reduced motion" checked={on} onCheckedChange={setOn} disabled={props.disabled} />;
}
export const Default: S = { render: () => <Live initial={false} /> };
export const Checked: S = { render: () => <Live initial /> };
export const Disabled: S = { render: () => <Live initial disabled /> };

function Seg(props: { disabled?: boolean }) {
    const [v, setV] = useState('brain');
    return (
        <Segmented
            label="Centre"
            value={v}
            onValueChange={setV}
            disabled={props.disabled}
            options={[
                { value: 'brain', label: 'Neural brain' },
                { value: 'head', label: 'Hologram head' },
            ]}
        />
    );
}
export const SegmentedDefault: S = { render: () => <Seg /> };
export const SegmentedDisabled: S = { render: () => <Seg disabled /> };
