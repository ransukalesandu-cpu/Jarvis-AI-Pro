// Typed message contract between the Python host (jarvis/webui/contract.py) and the page.
// Both sides validate: anything outside this closed set, or out of range, is dropped, never coerced.

import { validateLayout, type Layout } from '../workspace/layout';

export const ASSISTANT_STATES = ['idle', 'sleeping', 'listening', 'thinking', 'searching', 'executing', 'speaking', 'error'] as const;
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
  | { type: 'host.hello'; version: number };

/** UI -> Python requests. Authorization always happens in Python; this list is only the shape. */
export type UiRequest =
  | { kind: 'ready' } | { kind: 'ping'; n: number }
  | { kind: 'workspace.list' } | { kind: 'workspace.load'; name: string } | { kind: 'workspace.delete'; name: string }
  | { kind: 'workspace.save'; name: string; layout: Layout }
  | { kind: 'command.submit'; text: string }
  | { kind: 'news.open'; index: number }
  | { kind: 'job.cancel'; id: string }
  | { kind: 'control.do'; action: ControlAction };

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
    case 'host.hello':
      return num(m.version, 0, 1000) ? { type: m.type, version: m.version } : null;
    default:
      return null;
  }
}

export function encodeRequest(r: UiRequest): string {
  return JSON.stringify(r);
}
