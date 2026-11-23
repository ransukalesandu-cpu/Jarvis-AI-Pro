import type { Meta, StoryObj } from '@storybook/react-vite';
import { Mic, Trash2 } from 'lucide-react';
import { Button } from './Button';

const meta: Meta<typeof Button> = {
    title: 'Primitives/Button',
    component: Button,
    args: { children: 'Start', variant: 'solid', tone: 'primary', size: 'md' },
    argTypes: {
        variant: { control: 'inline-radio', options: ['solid', 'outline', 'ghost'] },
        size: { control: 'inline-radio', options: ['sm', 'md', 'lg'] },
        tone: { control: 'inline-radio', options: ['neutral', 'primary', 'ok', 'warn', 'danger'] },
    },
};
export default meta;
type S = StoryObj<typeof Button>;

export const Default: S = {};
export const Variants: S = {
    render: (a) => (
        <>
            <Button {...a} variant="solid">
                Solid
            </Button>
            <Button {...a} variant="outline">
                Outline
            </Button>
            <Button {...a} variant="ghost">
                Ghost
            </Button>
        </>
    ),
};
export const Sizes: S = {
    render: (a) => (
        <>
            <Button {...a} size="sm">
                Small
            </Button>
            <Button {...a} size="md">
                Medium
            </Button>
            <Button {...a} size="lg">
                Large
            </Button>
        </>
    ),
};
export const Tones: S = {
    render: (a) => (
        <>
            {(['neutral', 'primary', 'ok', 'warn', 'danger'] as const).map((t) => (
                <Button key={t} {...a} tone={t} variant="outline">
                    {t}
                </Button>
            ))}
        </>
    ),
};
/** Tab to it: focus-visible ring. */
export const Focus: S = { args: { autoFocus: true } };
export const Disabled: S = { args: { disabled: true } };
export const Loading: S = { args: { loading: true, children: 'Saving' } };
export const WithIcon: S = { args: { icon: <Mic size={14} aria-hidden />, children: 'Listen' } };
export const Danger: S = { args: { tone: 'danger', icon: <Trash2 size={14} aria-hidden />, children: 'Delete' } };
