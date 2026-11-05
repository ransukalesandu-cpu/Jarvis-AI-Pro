// Typed message contract between the Python host (jarvis/webui/contract.py) and the page.
// Both sides validate: anything outside this closed set, or out of range, is dropped, never coerced.

import { validateLayout, type Layout } from '../workspace/layout';

export const ASSISTANT_STATES = ['idle', 'sleeping', 'listening', 'thinking', 'searching', 'executing', 'speaking', 'error'] as const;
export type AssistantState = (typeof ASSISTANT_STATES)[number];
export const PERSONAS = ['jarvis', 'bihansa'] as const;
export type Persona = (typeof PERSONAS)[number];

export interface Battery { percent: number; charging: boolean }
export interface Net { upKBps: number; downKBps: number }

export type HostEvent =
  | { type: 'assistant.state_changed'; state: AssistantState }
  | { type: 'assistant.audio_level'; level: number; source: 'input' | 'output' }
  | { type: 'system.metrics_updated'; cpu: number; ram: number; disk: number | null; battery: Battery | null; net: Net | null }
  | { type: 'provider.changed'; provider: string; model: string; connected: boolean; fallback: boolean }
  | { type: 'ui.persona'; persona: Persona }
  | { type: 'workspace.list'; names: string[] }
  | { type: 'workspace.loaded'; name: string; layout: Layout | null }
  | { type: 'host.hello'; version: number };

/** UI -> Python requests. Authorization always happens in Python; this list is only the shape. */
export type UiRequest =
  | { kind: 'ready' } | { kind: 'ping'; n: number }
  | { kind: 'workspace.list' } | { kind: 'workspace.load'; name: string } | { kind: 'workspace.delete'; name: string }
  | { kind: 'workspace.save'; name: string; layout: Layout };

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
    case 'ui.persona':
      return (PERSONAS as readonly unknown[]).includes(m.persona) ? { type: m.type, persona: m.persona as Persona } : null;
    case 'workspace.list':
      return Array.isArray(m.names) && m.names.length <= 24 && m.names.every((n) => str(n, 32)) ? { type: m.type, names: m.names as string[] } : null;
    case 'workspace.loaded': {
      if (!str(m.name, 32)) return null;
      if (m.layout === null) return { type: m.type, name: m.name, layout: null };
      const layout = validateLayout(m.layout);
      return layout ? { type: m.type, name: m.name, layout } : null;
    }
    case 'host.hello':
      return num(m.version, 0, 1000) ? { type: m.type, version: m.version } : null;
    default:
      return null;
  }
}

export function encodeRequest(r: UiRequest): string {
  return JSON.stringify(r);
}
