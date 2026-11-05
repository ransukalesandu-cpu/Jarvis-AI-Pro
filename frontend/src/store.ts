import { create } from 'zustand';
import type { AssistantState, Battery, CommandReason, CommandState, HostEvent, LogTag, Net, Persona } from './bridge/contract';

export type Page = 'home' | 'chat' | 'activity' | 'models' | 'research' | 'reminders' | 'apps' | 'files' | 'memory' | 'automation' | 'monitor' | 'security';

export const SERIES_MAX = 120;   // ~2 minutes at the host's 1 Hz telemetry
export interface Series { cpu: number[]; ram: number[]; down: number[]; up: number[] }
const EMPTY: Series = { cpu: [], ram: [], down: [], up: [] };
const push = (a: number[], v: number) => (a.length >= SERIES_MAX ? [...a.slice(a.length - SERIES_MAX + 1), v] : [...a, v]);

export const LOG_MAX = 200;
export interface LogLine { id: number; at: number; tag: LogTag; text: string }
let logId = 0;

export interface Provider { provider: string; model: string; connected: boolean; fallback: boolean }

export interface UiState {
  link: 'connecting' | 'connected' | 'detached';
  assistant: AssistantState;
  persona: Persona;
  outputLevel: number;
  inputLevel: number;
  series: Series;
  metrics: { cpu: number; ram: number; disk: number | null; battery: Battery | null; net: Net | null } | null;
  provider: Provider | null;
  page: Page;
  navOpen: boolean;
  settingsOpen: boolean;
  reducedMotion: boolean;
  clock24: boolean;
  workspaceNames: string[];
  paletteOpen: boolean;
  muted: boolean;
  command: { state: CommandState; last: CommandReason | null };
  control: CommandReason | null;
  log: LogLine[];
  clearLog: () => void;
  history: { at: number; state: AssistantState }[];
  setLink: (l: UiState['link']) => void;
  apply: (e: HostEvent) => void;
  go: (p: Page) => void;
  toggleNav: (open?: boolean) => void;
  toggleSettings: (open?: boolean) => void;
  setReducedMotion: (v: boolean) => void;
  setClock24: (v: boolean) => void;
  setPalette: (open?: boolean) => void;
}

const prefersReduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

export const useUi = create<UiState>((set) => ({
  link: 'connecting', assistant: 'idle', persona: 'jarvis', outputLevel: 0, inputLevel: 0,
  series: EMPTY, metrics: null, provider: null, page: 'home', navOpen: false, settingsOpen: false, reducedMotion: prefersReduced, clock24: true, history: [], workspaceNames: [], paletteOpen: false, muted: false, command: { state: 'unavailable', last: null }, control: null, log: [],
  setLink: (link) => set({ link }),
  apply: (e) => set((s) => {
    switch (e.type) {
      case 'assistant.state_changed': return s.assistant === e.state ? s : { assistant: e.state, history: [...s.history.slice(-49), { at: Date.now(), state: e.state }] };
      case 'assistant.audio_level': return e.source === 'output' ? { outputLevel: e.level } : { inputLevel: e.level };
      case 'system.metrics_updated': return { series: { cpu: push(s.series.cpu, e.cpu), ram: push(s.series.ram, e.ram), down: e.net ? push(s.series.down, e.net.downKBps) : s.series.down, up: e.net ? push(s.series.up, e.net.upKBps) : s.series.up }, metrics: { cpu: e.cpu, ram: e.ram, disk: e.disk, battery: e.battery, net: e.net } };
      case 'provider.changed': return { provider: { provider: e.provider, model: e.model, connected: e.connected, fallback: e.fallback } };
      case 'command.availability': return { command: { ...s.command, state: e.state } };
      case 'command.result': return { command: { ...s.command, last: e.reason } };
      case 'log.line': return { log: [...s.log.slice(-(LOG_MAX - 1)), { id: ++logId, at: Date.now(), tag: e.tag, text: e.text }] };
      case 'control.result': return { control: e.reason };
      case 'assistant.muted': return { muted: e.muted };
      case 'ui.persona': return { persona: e.persona };
      case 'workspace.list': return { workspaceNames: e.names };
      case 'workspace.loaded': return e.layout ? { page: e.layout.page } : s;
      case 'host.hello': return { link: 'connected' as const };
      default: return s;
    }
  }),
  clearLog: () => set({ log: [] }),
  go: (page) => set({ page, navOpen: false }),
  toggleNav: (open) => set((s) => ({ navOpen: open ?? !s.navOpen, settingsOpen: false })),
  toggleSettings: (open) => set((s) => ({ settingsOpen: open ?? !s.settingsOpen, navOpen: false })),
  setReducedMotion: (reducedMotion) => set({ reducedMotion }),
  setClock24: (clock24) => set({ clock24 }),
  setPalette: (open) => set((s) => ({ paletteOpen: open ?? !s.paletteOpen })),
}));
