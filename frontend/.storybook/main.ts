import type { StorybookConfig } from '@storybook/react-vite';

const config: StorybookConfig = {
    stories: ['../src/**/*.stories.tsx'],
    framework: { name: '@storybook/react-vite', options: {} },
    core: { disableTelemetry: true },
    // The app build writes into jarvis/webui/dist; Storybook keeps its own output.
    viteFinal: async (cfg) => ({ ...cfg, build: { ...cfg.build, outDir: 'storybook-static' } }),
};
export default config;
