// Bootstrap: capabilities -> renderer -> entities -> one loop. Real events arrive through
// window.__holo.receive(); reports leave as "HOLO:{json}" console lines (no exposed objects).

import * as THREE from './vendor/three.module.min.js';
import { detect, pickInitialTier, QUALITY, FrameMonitor, stepDown, stepUp } from './core/capabilities.js';
import { createRenderer } from './core/renderer.js';
import { createScene, createCamera, fitCamera, pointScale, LAYOUT } from './core/scene.js';
import { Lifecycle } from './core/lifecycle.js';
import { HologramStateMachine } from './animation/state_machine.js';
import { AudioSync } from './animation/audio_sync.js';
import { ProfileBlend } from './profiles/index.js';
import { parseHostMessage, makeReport } from './bridge/protocol.js';
import { NeuralFace } from './entities/neural_face.js';
import { createExtras } from './entities/extras.js';

const params = new URLSearchParams(location.search);
const DEBUG = params.get('debug') === '1';
const canvas = document.getElementById('holo');
const fallback = document.getElementById('fallback');

function report(kind, data) { try { console.log('HOLO:' + makeReport(kind, data)); } catch { /* never throw from reporting */ } }
function showFallback(text) { fallback.textContent = text; fallback.hidden = false; canvas.style.display = 'none'; }

const caps = detect(canvas);
if (!caps.webgl2) { showFallback('Hologram unavailable: WebGL 2 is not supported on this system.'); report('error', { code: 'no_webgl2' }); throw new Error('no webgl2'); }

const U = (v) => ({ value: v });
const uniforms = {
  uTime: U(0), uEnergy: U(0.55), uDim: U(0), uWarn: U(0), uLock: U(0), uScan: U(0.25), uFlow: U(0.25), uHeart: U(0.45),
  uOrb: U(0.35), uHair: U(0.25), uRing: U(0.3), uListen: U(0), uSpeak: U(0), uMouth: U(0), uWidth: U(0), uShape: U(0),
  uGlow: U(1), uPointScale: U(600), uBlink: U(0), uLook: U(new THREE.Vector2()), uPulseRate: U(1),
  uFace: U(new THREE.Vector3()), uFaceDeep: U(new THREE.Vector3()), uHairC: U(new THREE.Vector3()), uWireC: U(new THREE.Vector3()),
  uSpark: U(new THREE.Vector3()), uHeartC: U(new THREE.Vector3()), uHeartHot: U(new THREE.Vector3()), uHeartSoft: U(new THREE.Vector3()),
  uOrbC: U(new THREE.Vector3()), uOrbCore: U(new THREE.Vector3()), uRingC: U(new THREE.Vector3()),
};

const renderer = createRenderer(canvas, caps.gl);
const scene = createScene();
const camera = createCamera();
const sm = new HologramStateMachine(performance.now() / 1000);
const audio = new AudioSync();
const profile = new ProfileBlend('jarvis');
const monitor = new FrameMonitor(90);

let tierName = params.get('quality') && QUALITY[params.get('quality')] ? params.get('quality') : pickInitialTier(caps);
let qualityMode = params.get('quality') || 'auto';
let q = QUALITY[tierName];
let face = null, extras = null;
let size = { w: 1, h: 1 };
let budget = { frame_ms: 16, particles: 1, glow: 1 };
let reducedMotion = false, effects = true, hostGlow = 1, heartbeatSeen = false;
let blink = { next: 2.5, phase: -1 };

function build() {
  destroyEntities();
  face = new NeuralFace(q, uniforms);
  extras = createExtras(q, uniforms);
  scene.add(face.group, extras.group);
  applySize();
}
function destroyEntities() {
  for (const e of [face, extras]) if (e) { scene.remove(e.group); e.dispose(); }
  face = extras = null;
}
function applySize() {
  const dpr = Math.min(window.devicePixelRatio || 1, q.pixelRatio);
  renderer.setPixelRatio(dpr);
  renderer.setSize(size.w, size.h, false);
  fitCamera(camera, size.w / size.h);
  uniforms.uPointScale.value = pointScale(size.h * dpr) / dpr * dpr;
}
function setTier(name, why) {
  if (!QUALITY[name] || name === tierName) return;
  tierName = name; q = QUALITY[name]; monitor.reset(); build();
  report('quality', { v: name, why });
}

const life = new Lifecycle({
  canvas,
  onResize: (w, h) => { size = { w: Math.max(1, Math.floor(w)), h: Math.max(1, Math.floor(h)) }; applySize(); },
  onFrame: frame,
  onContextLost: () => { report('contextlost'); },
  onContextRestored: () => { build(); report('contextrestored'); },
});

let fpsClock = 0, fpsFrames = 0;
function frame(dt, now, frameMs) {
  const speaking = sm.state === 'speaking';
  const p = sm.update(dt, now, heartbeatSeen);
  audio.update(dt, now, speaking);
  const prof = profile.update(dt);
  const U_ = uniforms;
  const rm = reducedMotion ? 0.35 : 1;
  U_.uTime.value = now * (reducedMotion ? 0.5 : 1);
  U_.uEnergy.value = p.energy * (effects ? 1 : 0.8);
  U_.uDim.value = p.dim; U_.uWarn.value = p.warn; U_.uLock.value = p.lock;
  U_.uScan.value = p.scan * rm; U_.uFlow.value = p.flow * rm; U_.uHeart.value = p.heart; U_.uOrb.value = p.orb;
  U_.uHair.value = p.hair * rm * prof.hairSwirl; U_.uRing.value = p.ring * rm;
  U_.uListen.value = audio.inEnv * p.listen; U_.uSpeak.value = audio.outEnv * p.speak;
  U_.uMouth.value = audio.mouth * p.speak; U_.uWidth.value = audio.width * p.speak;
  U_.uShape.value = prof.shape; U_.uGlow.value = prof.glow * hostGlow * budget.glow; U_.uPulseRate.value = prof.pulseRate;
  // blink and look (restrained)
  if (blink.phase < 0 && now > blink.next) { blink.phase = 0; }
  if (blink.phase >= 0) { blink.phase += dt / 0.16; U_.uBlink.value = Math.sin(Math.min(1, blink.phase) * Math.PI); if (blink.phase >= 1) { blink.phase = -1; blink.next = now + 2.5 + Math.random() * 4; U_.uBlink.value = 0; } }
  U_.uLook.value.set(Math.sin(now * 0.37) * 0.5 * rm, Math.sin(now * 0.23 + 1) * 0.25 * rm);
  for (const [k, u] of [['face', 'uFace'], ['faceDeep', 'uFaceDeep'], ['hair', 'uHairC'], ['wire', 'uWireC'], ['spark', 'uSpark'],
    ['heart', 'uHeartC'], ['heartHot', 'uHeartHot'], ['heartSoft', 'uHeartSoft'], ['orb', 'uOrbC'], ['orbCore', 'uOrbCore'], ['ring', 'uRingC']]) U_[u].value.set(prof[k][0], prof[k][1], prof[k][2]);
  if (face) { face.group.rotation.y = Math.sin(now * 0.3) * 0.1 * rm + U_.uLook.value.x * 0.04; face.group.rotation.x = Math.sin(now * 0.21) * 0.025 * rm; }
  extras?.update(dt, now, p, prof);
  renderer.render(scene, camera);

  monitor.push(frameMs);
  fpsClock += dt; fpsFrames++;
  if (fpsClock >= 2) { report('fps', { v: fpsFrames / fpsClock, tier: tierName }); fpsClock = 0; fpsFrames = 0; }
  if (qualityMode === 'auto') {
    const s = monitor.suggest(tierName);
    if (s === 'down') setTier(stepDown(tierName), 'slow'); else if (s === 'up') setTier(stepUp(tierName), 'fast');
  }
}

function receive(raw) {
  const m = parseHostMessage(raw);
  if (!m) return false;
  const now = performance.now() / 1000;
  switch (m.t) {
    case 'state': sm.setAppState(m.v, now); break;
    case 'input': audio.pushInput(m.v); break;
    case 'output': audio.pushOutput(m.v, now, m.open, m.width); sm.noteOutput(m.v, now); break;
    case 'output_end': audio.endOutput(); break;
    case 'profile': profile.set(m.v); break;
    case 'quality': qualityMode = m.v; if (m.v !== 'auto') setTier(m.v, 'host'); break;
    case 'budget': budget = m; life.setFrameInterval(m.frame_ms >= 24 ? m.frame_ms : 0); break;
    case 'motion': reducedMotion = m.reduced; break;
    case 'glow': hostGlow = m.v; break;
    case 'visible': life.setHostVisible(m.v); break;
    case 'effects': effects = m.v; break;
    case 'voice_reactive': break;
    case 'ping': heartbeatSeen = true; sm.ping(now); report('pong', { n: m.n }); break;
    default: return false;
  }
  return true;
}

window.__holo = Object.freeze({ receive });
if (DEBUG) {
  window.__holoDebug = {
    state: () => ({ state: sm.state, params: { ...sm.params }, tier: tierName, profile: profile.id, mouth: audio.mouth, log: sm.log.slice(-8) }),
    counts: () => ({ geometries: renderer.info.memory.geometries, textures: renderer.info.memory.textures, programs: renderer.info.programs?.length ?? 0, calls: renderer.info.render.calls, triangles: renderer.info.render.triangles }),
    layout: () => {
      const pr = (x, y, z = 0) => { const v = new THREE.Vector3(x, y, z).project(camera); return [(v.x * 0.5 + 0.5) * size.w, (1 - (v.y * 0.5 + 0.5)) * size.h]; };
      const L = LAYOUT, rad = (c) => { const a = pr(c.x, c.y), b = pr(c.x + c.radius, c.y); return { cx: a[0], cy: a[1], r: Math.abs(b[0] - a[0]) }; };
      const top = pr(0, L.face.y + L.face.height / 2), bot = pr(0, L.face.y - L.face.height / 2);
      return { size, face: { cx: pr(0, L.face.y)[0], top: top[1], bottom: bot[1], height: bot[1] - top[1] }, heart: rad(L.heart), orb: rad(L.orb) };
    },
    caps: () => ({ renderer: caps.rendererName, maxTexture: caps.maxTextureSize, tier: tierName }),
    loseContext: () => { const e = caps.gl.getExtension('WEBGL_lose_context'); e?.loseContext(); return !!e; },
    restoreContext: () => { const e = caps.gl.getExtension('WEBGL_lose_context'); e?.restoreContext(); return !!e; },
    setTier: (n) => setTier(n, 'debug'),
    dispose: () => { life.dispose(); destroyEntities(); renderer.dispose(); },
    frames: () => renderer.info.render.frame,
  };
}

addEventListener('pagehide', () => { life.dispose(); destroyEntities(); renderer.dispose(); });

try {
  build();
  life._resize();
  life.start();
  report('ready', { renderer: caps.rendererName, tier: tierName, webgl2: true });
} catch (err) {
  showFallback('Hologram could not start.');
  report('error', { code: String(err && err.message || err) });
}
