import type { Meta, StoryObj } from '@storybook/react-vite';
import { Info } from 'lucide-react';
import { Button } from './Button';
import { Popover, Tooltip } from './Popover';

const meta: Meta<typeof Popover> = { title: 'Primitives/Popover & Tooltip', component: Popover };
export default meta;
type S = StoryObj<typeof Popover>;

export const PopoverDefault: S = {
    render: () => (
        <Popover
            label="Brain route"
            trigger={
                <Button variant="outline" tone="neutral">
                    Brain
                </Button>
            }
            open
        >
            <p className="ui-hint">Voice: Gemini Live. Text: Claude. Offline: Ollama.</p>
        </Popover>
    ),
};
export const TooltipDefault: S = {
    render: () => (
        <Tooltip content="Interrupt JARVIS (Esc)">
            <button type="button" className="ui-icon-btn" aria-label="Interrupt JARVIS">
                <Info size={16} aria-hidden />
            </button>
        </Tooltip>
    ),
};
