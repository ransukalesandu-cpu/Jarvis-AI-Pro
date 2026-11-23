import type { ShapeName } from './hologram/brain/shapes';
import { create } from 'zustand';
import { usePending } from './ux/pending';
import { PAGE_WINDOWS } from './workspace/layout';
import { useWindows } from './workspace/windows';
import type {
    AssistantState,
    Battery,
    CommandReason,
    CommandState,
    Feature,
    FeatureSnapshot,
    HostEvent,
    JobRow,
    LogTag,
    NewsItem,
    Net,
    Persona,
    PerfTier,
} from './bridge/contract';

export type Page =
    'home' | 'chat' | 'activity' | 'models' | 'research' | 'reminders' | 'apps' | 'files' | 'memory' | 'automation' | 'monitor' | 'security' | 'tasks';

export const SERIES_MAX = 120; // ~2 minutes at the host's 1 Hz telemetry
export interface Series {
    cpu: number[];
    ram: number[];
    down: number[];
    up: number[];
}
const EMPTY: Series = { cpu: [], ram: [], down: [], up: [] };
const push = (a: number[], v: number) => (a.length >= SERIES_MAX ? [...a.slice(a.length - SERIES_MAX + 1), v] : [...a, v]);

export const LOG_MAX = 200;
export interface LogLine {
    id: number;
    at: number;
    tag: LogTag;
    text: string;
}
let logId = 0;

export interface Provider {
    provider: string;
    model: string;
    connected: boolean;
    fallback: boolean;
}

export interface UiState {
    link: 'connecting' | 'connected' | 'detached';
    assistant: AssistantState;
    persona: Persona;
    perfTier: PerfTier | null;
    news: { heading: string; items: NewsItem[] } | null;
    jobs: JobRow[] | null;
    features: Partial<Record<Feature, FeatureSnapshot & { at: number }>>;
    outputLevel: number;
    inputLevel: number;
    series: Series;
    metrics: { cpu: number; ram: number; disk: number | null; battery: Battery | null; net: Net | null } | null;
    provider: Provider | null;
    page: Page;
    navOpen: boolean;
    settingsOpen: boolean;
    reducedMotion: boolean;
    perfOverlay: boolean;
    faceStyle: FaceStyle;
    centerStyle: CenterStyle;
    brainShape: BrainShapeRequest | null;
    clock24: boolean;
    prefsLoaded: boolean; // true once Python answered prefs.load (until then nothing is saved over them)
    workspaceNames: string[];
    paletteOpen: boolean;
    muted: boolean;
    command: { state: CommandState; last: CommandReason | null };
    control: CommandReason | null;
    resultSeq: number; // bumped on every command/control result so a repeated reason still shows
    log: LogLine[];
    clearLog: () => void;
    history: { at: number; state: AssistantState }[];
    setLink: (l: UiState['link']) => void;
    apply: (e: HostEvent) => void;
    go: (p: Page) => void;
    toggleNav: (open?: boolean) => void;
    toggleSettings: (open?: boolean) => void;
    setReducedMotion: (v: boolean) => void;
    setPerfOverlay: (v: boolean) => void;
    setFaceStyle: (v: FaceStyle) => void;
    setCenterStyle: (v: CenterStyle) => void;
    formShape: (shape: ShapeName, text?: string) => void;
    setClock24: (v: boolean) => void;
    setPalette: (open?: boolean) => void;
}

/** circuit = the current glass circuit-board head; mechanical = Engine V2 plated head (phase 2, opt-in until approved). */
export type FaceStyle = 'circuit' | 'mechanical';
/** What stands at the centre of the stage: the neural brain (default) or the hologram head. */
export type CenterStyle = 'brain' | 'hologram';
/** A request (from JARVIS's form_shape tool) for the brain to flow into a shape; seq re-triggers repeats. */
export interface BrainShapeRequest {
    shape: ShapeName;
    text: string;
    seq: number;
}

const prefersReduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

export const useUi = create<UiState>((set) => ({
    link: 'connecting',
    assistant: 'idle',
    persona: 'jarvis',
    perfTier: null,
    news: null,
    jobs: null,
    features: {},
    outputLevel: 0,
    inputLevel: 0,
    series: EMPTY,
    metrics: null,
    provider: null,
    page: 'home',
    navOpen: false,
    settingsOpen: false,
    reducedMotion: prefersReduced,
    perfOverlay: false,
    faceStyle: 'circuit',
    centerStyle: 'brain',
    brainShape: null,
    clock24: true,
    prefsLoaded: false,
    history: [],
    workspaceNames: [],
    paletteOpen: false,
    muted: false,
    command: { state: 'unavailable', last: null },
    control: null,
    resultSeq: 0,
    log: [],
    setLink: (link) => set({ link }),
    apply: (e) =>
        set((s) => {
            switch (e.type) {
                case 'assistant.state_changed':
                    return s.assistant === e.state ? s : { assistant: e.state, history: [...s.history.slice(-49), { at: Date.now(), state: e.state }] };
                case 'assistant.audio_level':
                    return e.source === 'output' ? { outputLevel: e.level } : { inputLevel: e.level };
                case 'system.metrics_updated':
                    return {
                        series: {
                            cpu: push(s.series.cpu, e.cpu),
                            ram: push(s.series.ram, e.ram),
                            down: e.net ? push(s.series.down, e.net.downKBps) : s.series.down,
                            up: e.net ? push(s.series.up, e.net.upKBps) : s.series.up,
                        },
                        metrics: { cpu: e.cpu, ram: e.ram, disk: e.disk, battery: e.battery, net: e.net },
                    };
                case 'provider.changed':
                    return { provider: { provider: e.provider, model: e.model, connected: e.connected, fallback: e.fallback } };
                case 'command.availability':
                    return { command: { ...s.command, state: e.state } };
                case 'command.result':
                    return { command: { ...s.command, last: e.reason }, resultSeq: s.resultSeq + 1 };
                case 'log.line':
                    return { log: [...s.log.slice(-(LOG_MAX - 1)), { id: ++logId, at: Date.now(), tag: e.tag, text: e.text }] };
                case 'control.result':
                    return { control: e.reason, resultSeq: s.resultSeq + 1 };
                case 'assistant.muted':
                    return { muted: e.muted };
                case 'ui.persona':
                    return { persona: e.persona };
                case 'ui.perf':
                    return { perfTier: e.tier };
                case 'jobs.updated': {
                    const finished = finishedNow(s.jobs, e.jobs);
                    if (finished.length)
                        queueMicrotask(() => {
                            for (const t of finished.slice(0, 3)) usePending.getState().notify(t);
                        });
                    return { jobs: e.jobs };
                }
                case 'news.items':
                    return { news: { heading: e.heading, items: e.items } };
                case 'feature.snapshot':
                    return { features: { ...s.features, [e.feature]: { summary: e.summary, items: e.items, at: Date.now() } } };
                case 'workspace.list':
                    return { workspaceNames: e.names };
                case 'workspace.loaded':
                    return e.layout ? { page: PAGE_WINDOWS[e.layout.page] ? ('home' as const) : e.layout.page } : s;
                case 'host.hello':
                    return { link: 'connected' as const };
                case 'ui.prefs':
                    return e.prefs
                        ? {
                              prefsLoaded: true,
                              reducedMotion: e.prefs.reducedMotion,
                              clock24: e.prefs.clock24,
                              centerStyle: e.prefs.centerStyle,
                              faceStyle: e.prefs.faceStyle,
                          }
                        : { prefsLoaded: true };
                default:
                    return s;
            }
        }),
    clearLog: () => set({ log: [] }),
    go: (page) => {
        const kind = PAGE_WINDOWS[page];
        if (kind) {
            useWindows.getState().open(kind);
            set({ page: 'home', navOpen: false });
        } // a floating window, not the side panel
        else set({ page, navOpen: false });
    },
    toggleNav: (open) => set((s) => ({ navOpen: open ?? !s.navOpen, settingsOpen: false })),
    toggleSettings: (open) => set((s) => ({ settingsOpen: open ?? !s.settingsOpen, navOpen: false })),
    setReducedMotion: (reducedMotion) => set({ reducedMotion }),
    setPerfOverlay: (perfOverlay) => set({ perfOverlay }),
    setFaceStyle: (faceStyle) => set({ faceStyle }),
    setCenterStyle: (centerStyle) => set({ centerStyle }),
    formShape: (shape, text = '') => set((s) => ({ brainShape: { shape, text, seq: (s.brainShape?.seq ?? 0) + 1 } })),
    setClock24: (clock24) => set({ clock24 }),
    setPalette: (open) => set((s) => ({ paletteOpen: open ?? !s.paletteOpen })),
}));

/** Notices for jobs that were running in the previous snapshot and have now ended. The first snapshot never notifies. */
export function finishedNow(prev: JobRow[] | null, next: JobRow[]): string[] {
    if (!prev) return [];
    const was = new Map(prev.map((j) => [j.id, j.status]));
    const words = { done: 'finished', failed: 'failed', cancelled: 'was cancelled' } as const;
    return next.filter((j) => was.get(j.id) === 'running' && j.status !== 'running').map((j) => `Job “${j.name}” ${words[j.status as keyof typeof words]}`);
}

// Dev preview only (npm run dev has no backend): lets a test script set telemetry. Stripped from builds.
if (import.meta.env.DEV) (globalThis as Record<string, unknown>).__jarvisUi = useUi;
