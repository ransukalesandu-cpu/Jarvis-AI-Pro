import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { Flow } from '../bridge/contract';
import { VoiceLinkView, voiceLinkRows, type VoiceLinkInput } from './Widgets';

const flow = (title: string, state: Flow['state']): Flow => ({ id: title, title, source: 'command', state, startedAt: 1, finishedAt: null, steps: [] });
const rows = (o: Partial<VoiceLinkInput> = {}) =>
    Object.fromEntries(voiceLinkRows({ link: 'connected', muted: false, assistant: 'idle', flows: [], ...o }).map((r) => [r.key, r.value]));

describe('voiceLinkRows', () => {
    it('reports nothing it does not know while the backend is offline', () => {
        expect(rows({ link: 'detached', assistant: 'speaking' })).toEqual({ mic: 'unknown', output: 'unknown', backend: 'offline', task: 'none' });
    });
    it('never says listening while the mic is muted', () => {
        expect(rows({ muted: true, assistant: 'listening' }).mic).toBe('muted');
        expect(rows({ assistant: 'listening' }).mic).toBe('listening');
        expect(rows().mic).toBe('on');
    });
    it('shows speaking only while JARVIS speaks, and the latest running task', () => {
        expect(rows({ assistant: 'speaking' }).output).toBe('speaking');
        expect(rows().output).toBe('quiet');
        expect(rows({ flows: [flow('old', 'done'), flow('Open VS Code', 'running')] }).task).toBe('Open VS Code');
        expect(rows({ flows: [flow('old', 'done')] }).task).toBe('none');
        expect(rows({ link: 'connecting' }).backend).toBe('connecting');
    });
    it('labels every state in text, not by colour alone', () => {
        const html = renderToStaticMarkup(
            <VoiceLinkView rows={voiceLinkRows({ link: 'connected', muted: true, assistant: 'idle', flows: [] })} level={null} />,
        );
        for (const t of ['Mic', 'muted', 'Voice', 'quiet', 'Backend', 'connected', 'Task', 'none']) expect(html).toContain(t);
    });
});
