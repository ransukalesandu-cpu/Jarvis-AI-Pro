import test from 'node:test';
import assert from 'node:assert/strict';
import { parseHostMessage, makeReport, MAX_MESSAGE_CHARS } from '../bridge/protocol.js';
import { HologramStateMachine, STATES, STATE_TARGETS, TIMING } from '../animation/state_machine.js';
import { AudioSync } from '../animation/audio_sync.js';
import { pickInitialTier, FrameMonitor, QUALITY, isSoftwareRenderer, stepDown, stepUp } from '../core/capabilities.js';
import { ProfileBlend } from '../profiles/index.js';
import { damp } from '../animation/transitions.js';

const run = (sm, secs, from, dt = 1 / 60) => { let t = from; for (let i = 0; i < secs / dt; i++) { t += dt; sm.update(dt, t, false); } return t; };

test('protocol accepts valid messages and rejects everything else', () => {
  assert.ok(parseHostMessage('{"t":"state","v":"SPEAKING"}'));
  assert.ok(parseHostMessage('{"t":"output","v":0.4,"open":0.5,"width":-0.2}'));
  assert.ok(parseHostMessage('{"t":"profile","v":"bihansa"}'));
  for (const bad of ['', 'x', '[]', 'null', '{"t":"eval","v":"alert(1)"}', '{"t":"state","v":"HACK"}',
    '{"t":"output","v":2}', '{"t":"output","v":"0.5"}', '{"t":"output","v":NaN}', '{"t":"profile","v":"other"}',
    '{"t":"budget","frame_ms":1,"particles":1,"glow":1}', '{"t":"ping","n":-1}', '{"t":"visible","v":"yes"}',
    '{"__proto__":{"t":"state"},"t":"constructor"}', '{"t":"toString"}']) {
    assert.equal(parseHostMessage(bad), null, bad);
  }
  assert.equal(parseHostMessage('{"t":"input","v":0.1,"pad":"' + 'x'.repeat(MAX_MESSAGE_CHARS) + '"}'), null);
  assert.equal(parseHostMessage(123), null);
});

test('reports only allow known kinds and primitive payloads', () => {
  assert.equal(makeReport('fps', { v: 59.987 }), '{"t":"fps","v":59.99}');
  assert.throws(() => makeReport('exec'));
  const r = JSON.parse(makeReport('error', { code: 'x'.repeat(500), obj: { a: 1 }, fn: () => 1 }));
  assert.equal(r.code.length, 80); assert.equal(r.obj, undefined); assert.equal(r.fn, undefined);
});

test('every state has a complete target set', () => {
  const keys = Object.keys(STATE_TARGETS.idle).sort();
  for (const s of STATES) assert.deepEqual(Object.keys(STATE_TARGETS[s]).sort(), keys, s);
});

test('app states map onto visual states and glide, never snap', () => {
  const sm = new HologramStateMachine(0);
  assert.equal(sm.setAppState('LISTENING', 0), true);
  assert.equal(sm.state, 'listening');
  assert.ok(sm.params.listen < 0.2);               // has not jumped yet
  run(sm, 2, 0); assert.ok(sm.params.listen > 0.9); // arrives smoothly
  assert.equal(sm.setAppState('NOPE', 0), false);
  assert.equal(sm.state, 'listening');
});

test('privacy lock and sleeping are represented', () => {
  const sm = new HologramStateMachine(0);
  sm.setAppState('PRIVACY_LOCK', 0); assert.equal(sm.state, 'locked');
  sm.setAppState('SLEEPING', 1); assert.equal(sm.state, 'sleeping');
});

test('thinking becomes processing only after a real delay', () => {
  const sm = new HologramStateMachine(0);
  sm.setAppState('THINKING', 0);
  run(sm, TIMING.thinkingToProcessing - 0.5, 0); assert.equal(sm.state, 'thinking');
  run(sm, 1.5, TIMING.thinkingToProcessing - 0.5); assert.equal(sm.state, 'processing');
});

test('speaking ends through responding and then the requested state', () => {
  const sm = new HologramStateMachine(0);
  sm.setAppState('SPEAKING', 0); sm.noteOutput(0.5, 0.1);
  assert.equal(sm.state, 'speaking');
  sm.setAppState('LISTENING', 1);
  assert.equal(sm.state, 'responding');
  run(sm, TIMING.respondingSettle + 0.3, 1); assert.equal(sm.state, 'listening');
});

test('speaking without output audio does not get stuck', () => {
  const sm = new HologramStateMachine(0);
  sm.setAppState('SPEAKING', 0); sm.noteOutput(0.5, 0.1);
  run(sm, TIMING.speakingSilence + TIMING.respondingSettle + 1, 0.1);
  assert.notEqual(sm.state, 'speaking'); assert.notEqual(sm.state, 'responding');
});

test('output audio starts speaking before the app state arrives, and thinking can be interrupted', () => {
  const sm = new HologramStateMachine(0);
  sm.setAppState('THINKING', 0); sm.noteOutput(0.3, 0.5);
  assert.equal(sm.state, 'speaking');
  sm.setAppState('ERROR', 1); assert.equal(sm.state, 'error');
});

test('lost heartbeat shows disconnected, then recovery, then the last requested state', () => {
  const sm = new HologramStateMachine(0);
  sm.setAppState('LISTENING', 0);
  let t = 0; for (let i = 0; i < 60 * 8; i++) { t += 1 / 60; sm.update(1 / 60, t, true); }
  assert.equal(sm.state, 'disconnected');
  sm.setAppState('SPEAKING', t); assert.equal(sm.state, 'disconnected'); // remembered, not shown
  sm.ping(t); assert.equal(sm.state, 'recovery');
  t = run(sm, TIMING.recoveryHold + 0.2, t);
  assert.equal(sm.state, 'speaking');
});

test('audio sync: attack, release, mouth cap and silence handling', () => {
  const a = new AudioSync();
  let t = 0;
  a.pushOutput(1, t);
  for (let i = 0; i < 30; i++) { t += 1 / 60; a.update(1 / 60, t, true); a.pushOutput(1, t); }
  assert.ok(a.outEnv > 0.9); assert.ok(a.mouth <= 0.9 + 1e-9 && a.mouth > 0.7);
  a.endOutput();
  for (let i = 0; i < 90; i++) { t += 1 / 60; a.update(1 / 60, t, true); }
  assert.ok(a.mouth < 0.02);
  a.pushOutput(0.8, t); for (let i = 0; i < 20; i++) { t += 1 / 60; a.update(1 / 60, t, false); }
  assert.ok(a.mouth < 0.02, 'no jaw movement when not speaking');
  const b = new AudioSync(); b.pushOutput(0.7, 0, 0.2, 0.3);
  for (let i = 0; i < 30; i++) { b.pushOutput(0.7, i / 60, 0.2, 0.3); b.update(1 / 60, i / 60, true); }
  assert.ok(b.mouth < 0.4 && b.width > 0.2);
});

test('capabilities choose a sensible tier and never assume a strong GPU', () => {
  assert.equal(pickInitialTier({ webgl2: false }), 'low');
  assert.equal(pickInitialTier({ webgl2: true, rendererName: 'ANGLE (Google, Vulkan, SwiftShader)' }), 'low');
  assert.equal(pickInitialTier({ webgl2: true, rendererName: 'NVIDIA GeForce RTX 3060', maxTextureSize: 16384 }), 'high');
  assert.equal(pickInitialTier({ webgl2: true, rendererName: 'Intel(R) UHD Graphics 620', maxTextureSize: 16384 }), 'balanced');
  assert.equal(pickInitialTier({ webgl2: true, rendererName: 'GPU', maxTextureSize: 4096 }), 'low');
  assert.ok(isSoftwareRenderer('llvmpipe'));
  assert.equal(stepDown('high'), 'balanced'); assert.equal(stepDown('low'), 'low'); assert.equal(stepUp('low'), 'balanced');
  assert.ok(QUALITY.low.grid[0] < QUALITY.high.grid[0]);
});

test('frame monitor steps down on slow frames and up on fast ones, with hysteresis', () => {
  const m = new FrameMonitor(30);
  for (let i = 0; i < 29; i++) m.push(50); assert.equal(m.suggest('high'), null);
  m.push(50); assert.equal(m.suggest('high'), 'down');
  m.reset(); for (let i = 0; i < 30; i++) m.push(10); assert.equal(m.suggest('balanced'), 'up');
  m.reset(); for (let i = 0; i < 30; i++) m.push(10); assert.equal(m.suggest('high'), null);
  m.reset(); for (let i = 0; i < 30; i++) m.push(100); assert.equal(m.suggest('low'), null);
});

test('profile blend crosses over smoothly and converges', () => {
  const p = new ProfileBlend('jarvis');
  p.set('bihansa'); p.update(0.016);
  assert.ok(p.cur.face[0] < 0.2, 'first frame is still mostly cyan');
  for (let i = 0; i < 400; i++) p.update(0.016);
  assert.ok(p.settled()); assert.ok(p.cur.face[0] > 0.99);
  p.set('nonsense'); assert.equal(p.id, 'bihansa');
});

test('damp is stable for bad input and large time steps', () => {
  assert.equal(damp(NaN, 1, 5, 0.1), 1); assert.equal(damp(0.5, NaN, 5, 0.1), 0.5);
  assert.ok(damp(0, 1, 5, 100) <= 1);
});
