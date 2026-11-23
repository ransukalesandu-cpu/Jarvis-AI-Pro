import type { Preview } from '@storybook/react-vite';
import { useEffect } from 'react';
import '../src/styles/app.css';
import '../src/styles/holo-theme.css';
import '../src/styles/components.css';
import { TooltipProvider } from '../src/components/ui';

const preview: Preview = {
    globalTypes: {
        theme: {
            description: 'Token theme',
            toolbar: { title: 'Theme', icon: 'contrast', items: ['dark', 'light', 'hc'], dynamicTitle: true },
        },
    },
    initialGlobals: { theme: 'dark' },
    parameters: { layout: 'padded', controls: { expanded: true } },
    decorators: [
        (Story, ctx) => {
            const theme = ctx.globals.theme as string;
            useEffect(() => {
                if (theme === 'dark') document.documentElement.removeAttribute('data-theme');
                else document.documentElement.setAttribute('data-theme', theme);
            }, [theme]);
            return (
                <TooltipProvider delayDuration={200}>
                    <div className="sb-canvas">
                        <Story />
                    </div>
                </TooltipProvider>
            );
        },
    ],
};
export default preview;
