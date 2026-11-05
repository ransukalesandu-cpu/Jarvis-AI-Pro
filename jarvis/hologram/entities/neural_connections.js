// Neural energy connections: heart <-> face, face <-> orb, heart <-> orb.
// Each wire is a cubic curve; the line is sampled once, and the flowing particles are placed
// on the same curve by the GPU. State changes flow speed and intensity through uniforms only.
import * as THREE from '../vendor/three.module.min.js';
import { wireLine, wireParticles } from '../shaders/fx.glsl.js';
import { LAYOUT } from '../core/scene.js';

function mulberry(seed) { let a = seed >>> 0; return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const V = (x, y, z = 0) => new THREE.Vector3(x, y, z);

export function wireDefinitions() {
  const { heart, orb } = LAYOUT;
  const hR = heart.radius, oR = orb.radius;
  const defs = [];
  // heart -> face (kind 0): from the heart's right side to the chest / neck
  const chest = [V(-0.50, -0.86, 0.1), V(-0.32, -0.98, 0.12), V(-0.18, -1.08, 0.12), V(-0.62, -0.74, 0.08)];
  chest.forEach((end, i) => {
    const start = V(heart.x + hR * 0.95, heart.y + (i - 1.5) * hR * 0.35, 0);
    defs.push({ kind: 0, p: [start, start.clone().add(V(0.38, 0.30 + i * 0.06)), end.clone().add(V(-0.30, -0.22 - i * 0.03)), end] });
  });
  // face -> orb (kind 1): from the base of the neck/bust to the top of the orb
  [-0.30, -0.10, 0.10, 0.30].forEach((dx, i) => {
    const start = V(dx * 0.6, -1.14, 0.1), end = V(dx * oR * 1.4, orb.y + oR * 0.98, 0);
    defs.push({ kind: 1, p: [start, start.clone().add(V(dx * 0.9, -0.28)), end.clone().add(V(dx * 0.7, 0.30)), end] });
  });
  // heart -> orb (kind 2)
  [0, 1, 2].forEach((i) => {
    const start = V(heart.x + (i - 1) * hR * 0.3, heart.y - hR * 0.95, 0), end = V(-oR * (0.95 - i * 0.12), orb.y + oR * (0.2 - i * 0.28), 0);
    defs.push({ kind: 2, p: [start, start.clone().add(V(0.02, -0.55)), end.clone().add(V(-0.75, 0.05)), end] });
  });
  return defs;
}

export class NeuralConnections {
  constructor(q, uniforms) {
    this.group = new THREE.Group();
    this.defs = wireDefinitions();
    const rnd = mulberry(909), S = q.wire;
    const lp = [], lt = [], ls = [], lk = [];
    const pp = [], p0 = [], p1 = [], p2 = [], p3 = [], ph = [], ps = [], pk = [];
    const perWire = Math.max(8, Math.floor(q.wire / 5));
    this.defs.forEach((w, wi) => {
      const seed = rnd();
      const curve = new THREE.CubicBezierCurve3(w.p[0], w.p[1], w.p[2], w.p[3]);
      for (let i = 0; i < S; i++) {
        const a = curve.getPoint(i / S), b = curve.getPoint((i + 1) / S);
        lp.push(a.x, a.y, a.z, b.x, b.y, b.z); lt.push(i / S, (i + 1) / S); ls.push(seed, seed); lk.push(w.kind, w.kind);
      }
      for (let k = 0; k < perWire; k++) {
        pp.push(0, 0, 0);
        for (const [arr, v] of [[p0, w.p[0]], [p1, w.p[1]], [p2, w.p[2]], [p3, w.p[3]]]) arr.push(v.x, v.y, v.z);
        ph.push(k / perWire + rnd() * 0.05); ps.push(rnd()); pk.push(w.kind);
      }
    });
    const mk = (s) => new THREE.ShaderMaterial({ uniforms, vertexShader: s.vert, fragmentShader: s.frag, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const lg = new THREE.BufferGeometry();
    lg.setAttribute('position', new THREE.Float32BufferAttribute(lp, 3)); lg.setAttribute('aT', new THREE.Float32BufferAttribute(lt, 1));
    lg.setAttribute('aSeed', new THREE.Float32BufferAttribute(ls, 1)); lg.setAttribute('aKind', new THREE.Float32BufferAttribute(lk, 1));
    this.lines = new THREE.LineSegments(lg, mk(wireLine));
    const pg = new THREE.BufferGeometry();
    pg.setAttribute('position', new THREE.Float32BufferAttribute(pp, 3));
    pg.setAttribute('aP0', new THREE.Float32BufferAttribute(p0, 3)); pg.setAttribute('aP1', new THREE.Float32BufferAttribute(p1, 3));
    pg.setAttribute('aP2', new THREE.Float32BufferAttribute(p2, 3)); pg.setAttribute('aP3', new THREE.Float32BufferAttribute(p3, 3));
    pg.setAttribute('aPhase', new THREE.Float32BufferAttribute(ph, 1)); pg.setAttribute('aSeed', new THREE.Float32BufferAttribute(ps, 1));
    pg.setAttribute('aKind', new THREE.Float32BufferAttribute(pk, 1));
    this.particles = new THREE.Points(pg, mk(wireParticles));
    this.particles.frustumCulled = false; this.lines.frustumCulled = false;
    this.group.add(this.lines, this.particles);
    this.disposables = [lg, pg, this.lines.material, this.particles.material];
  }
  update() {}
  dispose() { for (const d of this.disposables) d.dispose(); this.disposables.length = 0; this.group.clear(); }
}
