// Central hologram state machine.
//
// Real events in (app state, output audio, host heartbeat), smoothed visual
// parameters out. Any state can be requested at any time (transitions are
// interruptible); the parameters glide, so nothing snaps or conflicts. Two
// watchdogs keep it from getting stuck: speaking without output audio, and a
// silent host (heartbeat lost -> disconnected, returns via recovery).

import { dampParams } from './transitions.js';
import { APP_STATES } from '../bridge/protocol.js';

export const STATES = Object.freeze([
  'idle', 'sleeping', 'listening', 'thinking', 'processing', 'speaking',
  'responding', 'error', 'disconnected', 'recovery', 'locked',
]);

// Visual targets per state. All values 0..~1.5 so they compose safely in shaders.
//  energy   overall brightness      scan      scanline speed       flow    energy-wire flow speed
//  heart    heartbeat intensity     orb       orb activity         hair    strand motion
//  listen   mic response gain       speak     output response gain
//  warn     error tint              dim       global dimming       lock    privacy-lock tint
const T = (o) => Object.freeze({ energy: 0.55, scan: 0.25, flow: 0.25, heart: 0.45, orb: 0.35, hair: 0.25,
  listen: 0, speak: 0, warn: 0, dim: 0, lock: 0, ring: 0.3, ...o });

export const STATE_TARGETS = Object.freeze({
  idle:         T({}),
  sleeping:     T({ energy: 0.32, scan: 0.1, flow: 0.1, heart: 0.3, orb: 0.2, hair: 0.12, ring: 0.15, dim: 0.35 }),
  listening:    T({ energy: 0.75, scan: 0.35, flow: 0.45, heart: 0.6, orb: 0.55, hair: 0.4, listen: 1, ring: 0.5 }),
  thinking:     T({ energy: 0.85, scan: 0.9, flow: 1.0, heart: 0.7, orb: 0.85, hair: 0.55, ring: 0.8 }),
  processing:   T({ energy: 1.0, scan: 1.2, flow: 1.35, heart: 0.8, orb: 1.0, hair: 0.65, ring: 1.0 }),
  speaking:     T({ energy: 0.95, scan: 0.45, flow: 0.8, heart: 0.75, orb: 0.8, hair: 0.5, speak: 1, ring: 0.7 }),
  responding:   T({ energy: 0.8, scan: 0.35, flow: 0.55, heart: 0.6, orb: 0.6, hair: 0.4, ring: 0.5 }),
  error:        T({ energy: 0.6, scan: 0.15, flow: 0.15, heart: 0.9, orb: 0.3, hair: 0.2, warn: 1, ring: 0.2 }),
  disconnected: T({ energy: 0.25, scan: 0.05, flow: 0.04, heart: 0.2, orb: 0.12, hair: 0.08, ring: 0.1, dim: 0.55 }),
  recovery:     T({ energy: 0.7, scan: 0.7, flow: 0.9, heart: 0.6, orb: 0.7, hair: 0.35, ring: 0.6, dim: 0.15 }),
  locked:       T({ energy: 0.4, scan: 0.05, flow: 0.05, heart: 0.5, orb: 0.15, hair: 0.05, ring: 0.1, lock: 1, dim: 0.2 }),
});

// Per-parameter response speeds (1/seconds). Heart and error respond a little faster.
const RATES = { warn: 6, lock: 6, listen: 8, speak: 8, heart: 3 };
const DEFAULT_RATE = 2.6;

export const TIMING = Object.freeze({
  thinkingToProcessing: 4.0,   // still THINKING after this long -> PROCESSING (derived, not a backend event)
  respondingSettle: 0.9,       // SPEAKING ended -> short settle before the target state
  speakingSilence: 1.6,        // SPEAKING but no output audio for this long -> stop speaking
  heartbeatLost: 6.0,          // no host ping for this long -> DISCONNECTED
  recoveryHold: 1.4,
});

export class HologramStateMachine {
  constructor(now = 0) {
    this.requested = 'idle';       // what the app last asked for
    this.state = 'idle';           // what is shown
    this.enteredAt = now;
    this.lastOutputAt = -Infinity;
    this.lastPingAt = now;
    this.hostLost = false;
    this.recoveryUntil = 0;
    this.settleUntil = 0;
    this.pendingAfterSettle = null;
    this.params = { ...STATE_TARGETS.idle };
    this.log = [];                 // recent transitions, for tests and diagnostics
  }

  _enter(state, now) {
    if (state === this.state) return;
    this.log.push([this.state, state]);
    if (this.log.length > 32) this.log.shift();
    this.state = state;
    this.enteredAt = now;
  }

  /** App state from the backend (any case, e.g. "SPEAKING"). Unknown names are ignored. */
  setAppState(name, now) {
    const key = String(name || '').toUpperCase();
    if (!Object.prototype.hasOwnProperty.call(APP_STATES, key)) return false;
    const next = APP_STATES[key];
    const prevRequested = this.requested;
    this.requested = next;
    if (this.hostLost) return true;                       // remembered, shown after recovery
    if (this.state === 'speaking' && next !== 'speaking' && next !== 'locked' && next !== 'error'
        && next !== 'disconnected' && next !== 'recovery') {
      this.settleUntil = now + TIMING.respondingSettle;   // speech ended: settle through "responding"
      this.pendingAfterSettle = next;
      this._enter('responding', now);
    } else if (next === 'responding') {
      this.settleUntil = now + TIMING.respondingSettle;
      this.pendingAfterSettle = prevRequested === 'responding' ? 'listening' : prevRequested;
      this._enter('responding', now);
    } else {
      this.pendingAfterSettle = null;
      this._enter(next, now);
    }
    return true;
  }

  /** Output audio activity (generated speech). Starts speaking if the app has not said so yet. */
  noteOutput(level, now) {
    if (level > 0.02) {
      this.lastOutputAt = now;
      if (!this.hostLost && (this.state === 'idle' || this.state === 'listening' || this.state === 'thinking'
          || this.state === 'processing' || this.state === 'responding')) {
        this._enter('speaking', now);
      }
    }
  }

  ping(now) {
    this.lastPingAt = now;
    if (this.hostLost) {
      this.hostLost = false;
      this.recoveryUntil = now + TIMING.recoveryHold;
      this._enter('recovery', now);
    }
  }

  /** Advance watchdogs and smooth parameters. Call once per frame. */
  update(dt, now, heartbeatEnabled = true) {
    if (heartbeatEnabled && !this.hostLost && now - this.lastPingAt > TIMING.heartbeatLost) {
      this.hostLost = true;
      this._enter('disconnected', now);
    }
    if (this.state === 'recovery' && now >= this.recoveryUntil) {
      this._enter(this.requested === 'recovery' || this.requested === 'disconnected' ? 'idle' : this.requested, now);
    }
    if (this.state === 'responding' && now >= this.settleUntil) {
      const next = this.pendingAfterSettle || 'listening';
      this.pendingAfterSettle = null;
      this._enter(next === 'speaking' ? 'listening' : next, now);
    }
    if (this.state === 'thinking' && now - this.enteredAt > TIMING.thinkingToProcessing) {
      this._enter('processing', now);
    }
    if (this.state === 'speaking' && now - this.lastOutputAt > TIMING.speakingSilence
        && now - this.enteredAt > TIMING.speakingSilence) {
      this.settleUntil = now + TIMING.respondingSettle;
      this.pendingAfterSettle = this.requested === 'speaking' ? 'listening' : this.requested;
      this._enter('responding', now);
    }
    dampParams(this.params, STATE_TARGETS[this.state], RATES, DEFAULT_RATE, dt);
    return this.params;
  }
}
