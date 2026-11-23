import { SHAPES, type ShapeName, validText } from '../hologram/brain/shapes';
// Typed message contract between the Python host (jarvis/webui/contract.py) and the page.
// Both sides validate: anything outside this closed set, or out of range, is dropped, never coerced.

import { validateLayout, type Layout } from '../workspace/layout';

export const ASSISTANT_STATES = ['idle', 'sleeping', 'listening', 'thinking', 'searching', 'executing', 'speaking', 'warning', 'error'] as const;
export type AssistantState = (typeof ASSISTANT_STATES)[number];
export const PERSONAS = ['jarvis', 'bihansa'] as const;
export type Persona = (typeof PERSONAS)[number];
export const PERF_TIERS = ['full', 'balanced', 'lite'] as const;
export type PerfTier = (typeof PERF_TIERS)[number];

export interface Battery { percent: number; charging: boolean }
export const JOB_STATES = ['running', 'done', 'failed', 'cancelled'] as const;
export type JobState = (typeof JOB_STATES)[number];
export interface JobRow { id: string; name: string; status: JobState; startedAt: number; finishedAt: number | null }
export interface NewsItem { title: string; source: string; link: boolean }
export interface Net { upKBps: number; downKBps: number }

export const FLOW_STATES = ['running', 'done', 'failed', 'cancelled'] as const;
export type FlowState = (typeof FLOW_STATES)[number];
export const FLOW_SOURCES = ['command', 'agent'] as const;
export type FlowSource = (typeof FLOW_SOURCES)[number];
export const STEP_STATES = ['pending', 'running', 'done', 'error', 'skipped'] as const;
export type StepStatus = (typeof STEP_STATES)[number];
export const FLOW_VIEWS = ['window', 'page', 'hide'] as const;
export type FlowView = (typeof FLOW_VIEWS)[number];
export const FLOW_MAX_STEPS = 24;
export interface FlowStep { id: string; tool: string; label: string; status: StepStatus; detail: string; startedAt: number | null; finishedAt: number | null }
/** One thing the owner asked for (jarvis/core/task_flow.py): a brain node and one node per step. */
export interface Flow { id: string; title: string; source: FlowSource; state: FlowState; startedAt: number; finishedAt: number | null; steps: FlowStep[] }

/** Features Hub (jarvis/webui/features_feed.py): read-only, bounded snapshots. Actions go through command.submit. */
export const FEATURES = ['knowledge', 'notes', 'telegram', 'providers', 'compare', 'backup', 'profiles', 'files', 'apps'] as const;
export type Feature = (typeof FEATURES)[number];
export const FEATURE_MAX_ITEMS = 30;
export interface FeatureItem { title: string; detail: string }
export interface FeatureSnapshot { summary: string; items: FeatureItem[] }

/** Web UI preferences, saved by Python (jarvis/webui/workspace_store.validate_prefs): exactly these keys. */
export const CENTER_STYLES = ['brain', 'hologram'] as const;
export const FACE_STYLES = ['circuit', 'mechanical'] as const;
export interface Prefs {
  reducedMotion: boolean; clock24: boolean; taskflowAutoShow: boolean;
  centerStyle: (typeof CENTER_STYLES)[number]; faceStyle: (typeof FACE_STYLES)[number];
}
const PREF_KEYS = ['reducedMotion', 'clock24', 'taskflowAutoShow', 'centerStyle', 'faceStyle'] as const;
export function validatePrefs(p: unknown): Prefs | null {
  if (p === null || typeof p !== 'object' || Array.isArray(p)) return null;
  const o = p as Record<string, unknown>;
  if (Object.keys(o).length !== PREF_KEYS.length || !PREF_KEYS.every((k) => k in o)) return null;
  if (typeof o.reducedMotion !== 'boolean' || typeof o.clock24 !== 'boolean' || typeof o.taskflowAutoShow !== 'boolean') return null;
  if (!(CENTER_STYLES as readonly unknown[]).includes(o.centerStyle) || !(FACE_STYLES as readonly unknown[]).includes(o.faceStyle)) return null;
  return { reducedMotion: o.reducedMotion, clock24: o.clock24, taskflowAutoShow: o.taskflowAutoShow, centerStyle: o.centerStyle as Prefs['centerStyle'], faceStyle: o.faceStyle as Prefs['faceStyle'] };
}

export type HostEvent =
  | { type: 'assistant.state_changed'; state: AssistantState }
  | { type: 'assistant.audio_level'; level: number; source: 'input' | 'output' }
  | { type: 'system.metrics_updated'; cpu: number; ram: number; disk: number | null; battery: Battery | null; net: Net | null }
  | { type: 'provider.changed'; provider: string; model: string; connected: boolean; fallback: boolean }
  | { type: 'assistant.muted'; muted: boolean }
  | { type: 'ui.persona'; persona: Persona }
  | { type: 'ui.perf'; tier: PerfTier }
  | { type: 'jobs.updated'; jobs: JobRow[] }
  | { type: 'news.items'; heading: string; items: NewsItem[] }
  | { type: 'workspace.list'; names: string[] }
  | { type: 'workspace.loaded'; name: string; layout: Layout | null }
  | { type: 'command.availability'; state: CommandState }
  | { type: 'command.result'; reason: CommandReason }
  | { type: 'control.result'; reason: CommandReason }
  | { type: 'log.line'; tag: LogTag; text: string }
  | { type: 'task.flow'; flow: Flow }
  | { type: 'ui.task_flow'; view: FlowView }
  | { type: 'hologram.shape'; shape: ShapeName; text: string }
  | { type: 'hologram.perf_report'; cpu: number; ramMb: number; processes: number }
  | { type: 'host.hello'; version: number }
  | { type: 'ui.prefs'; prefs: Prefs | null }
  | { type: 'feature.snapshot'; feature: Feature; summary: string; items: FeatureItem[] };

/** UI -> Python requests. Authorization always happens in Python; this list is only the shape. */
export type UiRequest =
  | { kind: 'ready' } | { kind: 'ping'; n: number }
  | { kind: 'workspace.list' } | { kind: 'workspace.load'; name: string } | { kind: 'workspace.delete'; name: string }
  | { kind: 'workspace.save'; name: string; layout: Layout }
  | { kind: 'command.submit'; text: string }
  | { kind: 'news.open'; index: number }
  | { kind: 'job.cancel'; id: string }
  | { kind: 'control.do'; action: ControlAction }
  | { kind: 'hologram.capability'; webgl2: boolean }
  | { kind: 'hologram.perf'; fps: number; frameMs: number; drawCalls: number; triangles: number; heapMb: number | null; dpr: number }
  | { kind: 'feature.refresh'; feature: Feature }
  | { kind: 'prefs.load' } | { kind: 'prefs.save'; prefs: Prefs };

export const COMMAND_MAX = 500;
export const COMMAND_REASONS = ['sent', 'empty', 'too_long', 'locked', 'auth_required', 'silent', 'guest', 'credential', 'rate_limited', 'unavailable', 'done', 'noop'] as const;
export const CONTROL_ACTIONS = ['interrupt', 'mute', 'unmute', 'fullscreen', 'mode_jarvis', 'mode_bihansa', 'perf_auto', 'perf_full', 'perf_balanced', 'perf_lite'] as const;
export type ControlAction = (typeof CONTROL_ACTIONS)[number];
export type CommandReason = (typeof COMMAND_REASONS)[number];
export const COMMAND_STATES = ['ok', 'locked', 'auth_required', 'silent', 'guest', 'unavailable'] as const;
export type CommandState = (typeof COMMAND_STATES)[number];

export const LOG_TAGS = ['you', 'ai', 'sys', 'err', 'file'] as const;
export type LogTag = (typeof LOG_TAGS)[number];
export const LOG_MAX_LINE = 400;

export const MAX_EVENT_CHARS = 16384;
const num = (v: unknown, lo: number, hi: number): v is number => typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi;
const str = (v: unknown, max = 80): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
const isObj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);

const time = (v: unknown, nullable = true): v is number | null => (nullable && v === null) || num(v, 0, 4e12);
const exactKeys = (o: Record<string, unknown>, keys: string[]) => Object.keys(o).length === keys.length && keys.every((k) => k in o);
const FLOW_KEYS = ['id', 'title', 'source', 'state', 'startedAt', 'finishedAt', 'steps'];
const STEP_KEYS = ['id', 'tool', 'label', 'status', 'detail', 'startedAt', 'finishedAt'];

/** Mirror of contract.flow_ok in Python: closed state sets, bounded text, nothing else accepted. */
export function parseFlow(f: unknown): Flow | null {
  if (!isObj(f) || !exactKeys(f, FLOW_KEYS)) return null;
  if (!str(f.id, 40) || !str(f.title, 120) || !(FLOW_SOURCES as readonly unknown[]).includes(f.source) || !(FLOW_STATES as readonly unknown[]).includes(f.state)) return null;
  if (!time(f.startedAt, false) || !time(f.finishedAt) || !Array.isArray(f.steps) || f.steps.length > FLOW_MAX_STEPS) return null;
  const steps: FlowStep[] = [];
  for (const s of f.steps as unknown[]) {
    if (!isObj(s) || !exactKeys(s, STEP_KEYS) || !str(s.id, 8) || !str(s.tool, 48) || !str(s.label, 80)) return null;
    if (!(STEP_STATES as readonly unknown[]).includes(s.status) || typeof s.detail !== 'string' || s.detail.length > 100) return null;
    if (!time(s.startedAt) || !time(s.finishedAt)) return null;
    steps.push({ id: s.id, tool: s.tool, label: s.label, status: s.status as StepStatus, detail: s.detail, startedAt: s.startedAt as number | null, finishedAt: s.finishedAt as number | null });
  }
  return { id: f.id, title: f.title, source: f.source as FlowSource, state: f.state as FlowState, startedAt: f.startedAt as number, finishedAt: f.finishedAt as number | null, steps };
}

export function parseHostEvent(raw: unknown): HostEvent | null {
  if (typeof raw !== 'string' || raw.length === 0 || raw.length > MAX_EVENT_CHARS) return null;
  let m: unknown;
  try { m = JSON.parse(raw); } catch { return null; }
  if (!isObj(m)) return null;
  switch (m.type) {
    case 'assistant.state_changed':
      return (ASSISTANT_STATES as readonly unknown[]).includes(m.state) ? { type: m.type, state: m.state as AssistantState } : null;
    case 'assistant.audio_level':
      return num(m.level, 0, 1) && (m.source === 'input' || m.source === 'output') ? { type: m.type, level: m.level, source: m.source } : null;
    case 'system.metrics_updated': {
      if (!num(m.cpu, 0, 100) || !num(m.ram, 0, 100)) return null;
      const disk = m.disk === null || m.disk === undefined ? null : num(m.disk, 0, 100) ? m.disk : undefined;
      if (disk === undefined) return null;
      let battery: Battery | null = null;
      if (m.battery !== null && m.battery !== undefined) {
        if (!isObj(m.battery) || !num(m.battery.percent, 0, 100) || typeof m.battery.charging !== 'boolean') return null;
        battery = { percent: m.battery.percent, charging: m.battery.charging };
      }
      let net: Net | null = null;
      if (m.net !== null && m.net !== undefined) {
        if (!isObj(m.net) || !num(m.net.upKBps, 0, 1e7) || !num(m.net.downKBps, 0, 1e7)) return null;
        net = { upKBps: m.net.upKBps, downKBps: m.net.downKBps };
      }
      return { type: m.type, cpu: m.cpu, ram: m.ram, disk, battery, net };
    }
    case 'provider.changed':
      return str(m.provider) && str(m.model, 120) && typeof m.connected === 'boolean' && typeof m.fallback === 'boolean'
        ? { type: m.type, provider: m.provider, model: m.model, connected: m.connected, fallback: m.fallback } : null;
    case 'assistant.muted':
      return typeof m.muted === 'boolean' ? { type: m.type, muted: m.muted } : null;
    case 'ui.perf':
      return (PERF_TIERS as readonly unknown[]).includes(m.tier) ? { type: m.type, tier: m.tier as PerfTier } : null;
    case 'ui.persona':
      return (PERSONAS as readonly unknown[]).includes(m.persona) ? { type: m.type, persona: m.persona as Persona } : null;
    case 'jobs.updated': {
      if (!Array.isArray(m.jobs) || m.jobs.length > 20) return null;
      const jobs: JobRow[] = [];
      for (const j of m.jobs as Record<string, unknown>[]) {
        if (!j || typeof j !== 'object' || !str(j.id, 24) || !str(j.name, 80) || !(JOB_STATES as readonly unknown[]).includes(j.status)) return null;
        if (!num(j.startedAt, 0, 4e12) || !(j.finishedAt === null || num(j.finishedAt, 0, 4e12))) return null;
        jobs.push({ id: j.id, name: j.name, status: j.status as JobState, startedAt: j.startedAt as number, finishedAt: j.finishedAt as number | null });
      }
      return { type: m.type, jobs };
    }
    case 'news.items': {
      if (!str(m.heading, 80) && m.heading !== '') return null;
      if (!Array.isArray(m.items) || m.items.length > 20) return null;
      const items: NewsItem[] = [];
      for (const i of m.items as Record<string, unknown>[]) {
        if (!i || typeof i !== 'object' || !str(i.title, 200) || typeof i.source !== 'string' || i.source.length > 80 || typeof i.link !== 'boolean') return null;
        items.push({ title: i.title as string, source: i.source, link: i.link });
      }
      return { type: m.type, heading: m.heading as string, items };
    }
    case 'workspace.list':
      return Array.isArray(m.names) && m.names.length <= 24 && m.names.every((n) => str(n, 32)) ? { type: m.type, names: m.names as string[] } : null;
    case 'workspace.loaded': {
      if (!str(m.name, 32)) return null;
      if (m.layout === null) return { type: m.type, name: m.name, layout: null };
      const layout = validateLayout(m.layout);
      return layout ? { type: m.type, name: m.name, layout } : null;
    }
    case 'command.availability':
      return (COMMAND_STATES as readonly unknown[]).includes(m.state) ? { type: m.type, state: m.state as CommandState } : null;
    case 'command.result':
      return (COMMAND_REASONS as readonly unknown[]).includes(m.reason) ? { type: m.type, reason: m.reason as CommandReason } : null;
    case 'log.line':
      return (LOG_TAGS as readonly unknown[]).includes(m.tag) && str(m.text, LOG_MAX_LINE) ? { type: m.type, tag: m.tag as LogTag, text: m.text } : null;
    case 'control.result':
      return (COMMAND_REASONS as readonly unknown[]).includes(m.reason) ? { type: m.type, reason: m.reason as CommandReason } : null;
    case 'task.flow': {
      const flow = parseFlow(m.flow);
      return flow ? { type: m.type, flow } : null;
    }
    case 'hologram.shape':
      return typeof m.shape === 'string' && (SHAPES as readonly string[]).includes(m.shape) && typeof m.text === 'string'
        && validText(m.text) && (m.text !== '') === (m.shape === 'text')
        ? { type: m.type, shape: m.shape as ShapeName, text: m.text } : null;
    case 'ui.task_flow':
      return (FLOW_VIEWS as readonly unknown[]).includes(m.view) ? { type: m.type, view: m.view as FlowView } : null;
    case 'ui.prefs': {
      if (m.prefs === null) return { type: m.type, prefs: null };
      const prefs = validatePrefs(m.prefs);
      return prefs ? { type: m.type, prefs } : null;
    }
    case 'hologram.perf_report':
      return num(m.cpu, 0, 100) && num(m.ramMb, 0, 1e6) && Number.isInteger(m.processes) && num(m.processes, 0, 64)
        ? { type: m.type, cpu: m.cpu, ramMb: m.ramMb, processes: m.processes as number } : null;
    case 'host.hello':
      return num(m.version, 0, 1000) ? { type: m.type, version: m.version } : null;
    case 'feature.snapshot': {
      if (!(FEATURES as readonly unknown[]).includes(m.feature) || !str(m.summary, 200)) return null;
      if (!Array.isArray(m.items) || m.items.length > FEATURE_MAX_ITEMS) return null;
      const items: FeatureItem[] = [];
      for (const i of m.items as unknown[]) {
        if (!isObj(i) || !exactKeys(i, ['title', 'detail']) || !str(i.title, 120) || typeof i.detail !== 'string' || i.detail.length > 200) return null;
        items.push({ title: i.title, detail: i.detail });
      }
      return { type: m.type, feature: m.feature as Feature, summary: m.summary, items };
    }
    default:
      return null;
  }
}

export function encodeRequest(r: UiRequest): string {
  return JSON.stringify(r);
}
