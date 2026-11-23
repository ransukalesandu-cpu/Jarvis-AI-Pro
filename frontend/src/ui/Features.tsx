import { RefreshCw, Send } from 'lucide-react';
import { useEffect, useState } from 'react';
import { sendRequest } from '../bridge/bridge';
import { COMMAND_MAX, FEATURES, type CommandReason, type Feature, type FeatureSnapshot } from '../bridge/contract';
import { useUi } from '../store';
import { RESULT } from './CommandBar';
import { Button, Input, Tabs } from '../components/ui';

/** One tab of the Features Hub. Buttons and the input only ever submit a typed command (same gate as the command bar). */
export interface FeatureSpec {
    label: string;
    blurb: string;
    actions: { label: string; text: string }[];
    ask?: { placeholder: string; template: string };
}

export const SPECS: Record<Feature, FeatureSpec> = {
    knowledge: {
        label: 'Knowledge',
        blurb: 'Your documents, folders and web pages, searchable with cited answers.',
        actions: [
            { label: 'List bases', text: 'list my knowledge bases' },
            { label: 'Refresh active base', text: 'refresh my knowledge base' },
        ],
        ask: { placeholder: 'Ask your documents…', template: 'Using my knowledge base, answer: {q}' },
    },
    notes: {
        label: 'Notes',
        blurb: 'Markdown notes (works with an Obsidian vault).',
        actions: [
            { label: 'List notes', text: 'list my notes' },
            { label: 'Notes folder', text: 'where are my notes saved' },
        ],
        ask: { placeholder: 'Quick note…', template: 'Add this to my Inbox note: {q}' },
    },
    telegram: {
        label: 'Telegram',
        blurb: 'Control JARVIS from your phone. Pairing needs your confirmation.',
        actions: [
            { label: 'Pair phone', text: 'pair Telegram' },
            { label: 'Status', text: 'telegram status' },
        ],
        ask: { placeholder: 'Message to your phone…', template: 'Send this to my Telegram: {q}' },
    },
    providers: {
        label: 'AI Providers',
        blurb: 'Which models are set up, usage today and the daily budget.',
        actions: [
            { label: 'Status', text: 'show my AI provider status' },
            { label: 'Usage this month', text: 'how much AI did I use this month' },
        ],
    },
    compare: {
        label: 'Compare',
        blurb: 'Ask several AI models the same question side by side.',
        actions: [
            { label: 'Show last comparison', text: 'show the full model comparison' },
            { label: 'Winners', text: 'which AI model wins most' },
        ],
        ask: { placeholder: 'Question for every model…', template: 'Ask Claude, Gemini and GPT and compare: {q}' },
    },
    backup: {
        label: 'Backup',
        blurb: 'Encrypted backups of memory, knowledge, notes and settings. Restore asks first.',
        actions: [
            { label: 'Back up now', text: 'back up JARVIS now' },
            { label: 'Daily backups', text: 'back up every day and keep 7' },
            { label: 'Status', text: 'backup status' },
        ],
    },
    profiles: {
        label: 'Profiles',
        blurb: 'Focused assistant roles. Identity and security never change.',
        actions: [
            { label: 'Coding', text: 'switch to the coding assistant profile' },
            { label: 'Designer', text: 'switch to the designer assistant profile' },
            { label: 'Default', text: 'switch back to the default assistant profile' },
        ],
    },
    files: {
        label: 'Files',
        blurb: 'Files JARVIS made or received: translations, backups, images, transcripts.',
        actions: [{ label: 'Recent files', text: 'show my recent files from the file library' }],
        ask: { placeholder: 'Find a file…', template: 'Search my file library for {q}' },
    },
    apps: {
        label: 'Mini Apps',
        blurb: 'Web tools in their own window with separate logins.',
        actions: [
            { label: 'Open Figma', text: 'open the figma mini app' },
            { label: 'Open Fiverr', text: 'open the fiverr mini app' },
        ],
        ask: { placeholder: 'Open which mini app?', template: 'Open the {q} mini app' },
    },
};

/** Build the command text for an "ask" box; empty when there is nothing to send. */
export function askText(spec: FeatureSpec, q: string): string {
    const t = q.trim();
    if (!t || !spec.ask) return '';
    return spec.ask.template.replace('{q}', t).slice(0, COMMAND_MAX);
}

export interface FeaturesViewProps {
    tab: Feature;
    onTab: (f: Feature) => void;
    snap: (FeatureSnapshot & { at: number }) | undefined;
    canAsk: boolean;
    result: CommandReason | null;
    onSubmit: (text: string) => void;
    onRefresh: () => void;
}

export function FeaturesView({ tab, onTab, snap, canAsk, result, onSubmit, onRefresh }: FeaturesViewProps) {
    const spec = SPECS[tab];
    const [q, setQ] = useState('');
    const send = (text: string) => {
        if (text) onSubmit(text);
    };
    const body = (
        <>
            <h1 className="feature-title">
                {spec.label}
                <Button
                    variant="ghost"
                    tone="neutral"
                    size="sm"
                    onClick={onRefresh}
                    aria-label={`Refresh ${spec.label}`}
                    icon={<RefreshCw size={12} aria-hidden />}
                />
            </h1>
            <p>{spec.blurb}</p>
            <p className="news-source" role="status">
                {snap ? snap.summary : 'Loading…'}
            </p>
            <div className="seg feature-actions">
                {spec.actions.map((a) => (
                    <Button key={a.label} variant="outline" tone="neutral" size="sm" disabled={!canAsk} onClick={() => send(a.text)}>
                        {a.label}
                    </Button>
                ))}
            </div>
            {spec.ask && (
                <form
                    className="feature-ask"
                    onSubmit={(e) => {
                        e.preventDefault();
                        send(askText(spec, q));
                        setQ('');
                    }}
                >
                    <Input
                        label={spec.ask.placeholder}
                        hideLabel
                        size="sm"
                        placeholder={spec.ask.placeholder}
                        value={q}
                        maxLength={400}
                        disabled={!canAsk}
                        onChange={(e) => setQ(e.target.value)}
                    />
                    <Button type="submit" size="sm" disabled={!canAsk || !q.trim()} aria-label="Send" icon={<Send size={12} aria-hidden />} />
                </form>
            )}
            {snap && snap.items.length > 0 ? (
                <ul className="news-list">
                    {snap.items.map((i, n) => (
                        <li key={`${i.title}-${n}`} className="news-item">
                            <span className="news-title">{i.title}</span>
                            {i.detail && <span className="news-source">{i.detail}</span>}
                        </li>
                    ))}
                </ul>
            ) : snap ? (
                <p>Nothing here yet.</p>
            ) : null}
            <p className="settings-note" role="status" aria-live="polite">
                {result && result !== 'done' ? RESULT[result] : ''}
            </p>
        </>
    );
    return (
        <Tabs
            label="Features"
            value={tab}
            onValueChange={(v) => onTab(v as Feature)}
            items={FEATURES.map((f) => ({ value: f, label: SPECS[f].label, content: f === tab ? body : null }))}
        />
    );
}

export function FeaturesContent() {
    const [tab, setTab] = useState<Feature>('knowledge');
    const snap = useUi((s) => s.features[tab]);
    const canAsk = useUi((s) => s.command.state) === 'ok';
    const result = useUi((s) => s.command.last);
    const refresh = () => sendRequest({ kind: 'feature.refresh', feature: tab });
    useEffect(() => {
        sendRequest({ kind: 'feature.refresh', feature: tab });
    }, [tab]);
    return (
        <FeaturesView
            tab={tab}
            onTab={setTab}
            snap={snap}
            canAsk={canAsk}
            result={result}
            onRefresh={refresh}
            onSubmit={(text) => {
                sendRequest({ kind: 'command.submit', text });
                setTimeout(refresh, 4000);
            }}
        />
    );
}
