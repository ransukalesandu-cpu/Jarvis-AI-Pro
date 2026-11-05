// Message protocol between the Python host and the page.
// Strict allowlist: unknown types, wrong types, out-of-range values and oversized
// messages are rejected, never coerced into something that could be acted on.

export const MAX_MESSAGE_CHARS = 2048;

export const APP_STATES = Object.freeze({
  IDLE: 'idle', SLEEPING: 'sleeping', LISTENING: 'listening', THINKING: 'thinking',
  PROCESSING: 'processing', SPEAKING: 'speaking', RESPONDING: 'responding',
  ERROR: 'error', DISCONNECTED: 'disconnected', RECOVERY: 'recovery',
  LOCKED: 'locked', PRIVACY_LOCK: 'locked',
});

const isNum = (v, lo, hi) => typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi;
const isBool = (v) => typeof v === 'boolean';

const SCHEMAS = {
  state: (m) => typeof m.v === 'string' && Object.prototype.hasOwnProperty.call(APP_STATES, m.v.toUpperCase()),
  input: (m) => isNum(m.v, 0, 1),
  output: (m) => isNum(m.v, 0, 1) && (m.open === undefined || isNum(m.open, 0, 1)) && (m.width === undefined || isNum(m.width, -1, 1)),
  output_end: () => true,
  profile: (m) => m.v === 'jarvis' || m.v === 'bihansa',
  quality: (m) => ['auto', 'high', 'balanced', 'low'].includes(m.v),
  budget: (m) => isNum(m.frame_ms, 8, 100) && isNum(m.particles, 0.2, 1) && isNum(m.glow, 0, 1.5),
  motion: (m) => isBool(m.reduced),
  glow: (m) => isNum(m.v, 0, 1.5),
  visible: (m) => isBool(m.v),
  effects: (m) => isBool(m.v),
  voice_reactive: (m) => isBool(m.v),
  ping: (m) => Number.isInteger(m.n) && m.n >= 0 && m.n < 2 ** 31,
};

/** Parse and validate a host message. Returns the message object or null. */
export function parseHostMessage(raw) {
  if (typeof raw !== 'string' || raw.length === 0 || raw.length > MAX_MESSAGE_CHARS) return null;
  let m;
  try { m = JSON.parse(raw); } catch { return null; }
  if (m === null || typeof m !== 'object' || Array.isArray(m)) return null;
  const check = Object.prototype.hasOwnProperty.call(SCHEMAS, m.t) ? SCHEMAS[m.t] : null;
  if (!check || !check(m)) return null;
  return m;
}

// Page -> host reports. Names and payload shapes are fixed here and checked again in Python.
export const REPORTS = Object.freeze(['ready', 'fps', 'quality', 'error', 'contextlost', 'contextrestored', 'pong']);

export function makeReport(kind, data = {}) {
  if (!REPORTS.includes(kind)) throw new Error('unknown report: ' + kind);
  const safe = {};
  for (const [k, v] of Object.entries(data)) {
    if (typeof v === 'number' && Number.isFinite(v)) safe[k] = Math.round(v * 100) / 100;
    else if (typeof v === 'boolean') safe[k] = v;
    else if (typeof v === 'string') safe[k] = v.slice(0, 80);
  }
  return JSON.stringify({ t: kind, ...safe });
}
