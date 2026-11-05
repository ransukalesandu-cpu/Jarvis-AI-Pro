// Quantum heart reactor: procedural point cloud on an implicit heart surface, a neural mesh
// between nearby points, and orbiting quantum particles. Beats with a lub-dub profile.
import * as THREE from '../vendor/three.module.min.js';
import { points, mesh, orbit } from '../shaders/heart.glsl.js';
import { LAYOUT } from '../core/scene.js';

function mulberry(seed) { let a = seed >>> 0; return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

// (x^2 + 9/4 y^2 + z^2 - 1)^3 - x^2 z^3 - 9/80 y^2 z^3 = 0   (z is the vertical axis)
const f = (x, y, z) => Math.pow(x * x + 2.25 * y * y + z * z - 1, 3) - x * x * z * z * z - 0.1125 * y * y * z * z * z;

export class QuantumHeart {
  constructor(q, uniforms) {
    this.group = new THREE.Group();
    this.disposables = [];
    const rnd = mulberry(77), N = q.heartPts;
    const pts = [];
    let guard = 0;
    while (pts.length < N * 3 && guard++ < 400000) {
      const x = (rnd() - 0.5) * 2.7, y = (rnd() - 0.5) * 1.8, z = (rnd() - 0.5) * 2.6;
      if (Math.abs(f(x, y, z)) < 0.045) pts.push(x, z + 0.05, y * 1.15);     // map: z -> up, y -> depth
    }
    const count = pts.length / 3;
    const pos = new Float32Array(pts), seed = new Float32Array(count), size = new Float32Array(count);
    for (let i = 0; i < count; i++) { seed[i] = rnd(); size[i] = 0.03 + rnd() * 0.035; }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1)); g.setAttribute('aSize', new THREE.BufferAttribute(size, 1));
    const mk = (s, extra = {}) => new THREE.ShaderMaterial({ uniforms, vertexShader: s.vert, fragmentShader: s.frag,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, ...extra });
    this.body = new THREE.Points(g, mk(points));

    // neural mesh: connect each of a sample of points to its two nearest neighbours
    const lines = [], sampleStep = Math.max(1, Math.floor(count / 420));
    for (let i = 0; i < count; i += sampleStep) {
      let b1 = -1, b2 = -1, d1 = 1e9, d2 = 1e9;
      for (let j = 0; j < count; j += 2) {
        if (j === i) continue;
        const dx = pos[i * 3] - pos[j * 3], dy = pos[i * 3 + 1] - pos[j * 3 + 1], dz = pos[i * 3 + 2] - pos[j * 3 + 2];
        const d = dx * dx + dy * dy + dz * dz;
        if (d < d1) { d2 = d1; b2 = b1; d1 = d; b1 = j; } else if (d < d2) { d2 = d; b2 = j; }
      }
      for (const j of [b1, b2]) if (j >= 0) lines.push(i, j);
    }
    const lg = new THREE.BufferGeometry();
    lg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    lg.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1)); lg.setIndex(lines);
    this.mesh = new THREE.LineSegments(lg, mk(mesh));

    // orbiting quantum particles
    const rings = 3, per = Math.max(10, Math.floor(N / 60));
    const oPhase = [], oAxis = [], oRad = [], oSeed = [], oPos = [];
    for (let r = 0; r < rings; r++) {
      const ax = new THREE.Vector3(rnd() - 0.5, rnd() * 0.6 + 0.2, rnd() - 0.5).normalize();
      for (let k = 0; k < per; k++) {
        oPhase.push(k / per); oAxis.push(ax.x, ax.y, ax.z); oRad.push(1.45 + r * 0.22); oSeed.push(r % 2 ? 0.9 : 0.1); oPos.push(0, 0, 0);
      }
    }
    const og = new THREE.BufferGeometry();
    og.setAttribute('position', new THREE.Float32BufferAttribute(oPos, 3));
    og.setAttribute('aPhase', new THREE.Float32BufferAttribute(oPhase, 1)); og.setAttribute('aAxis', new THREE.Float32BufferAttribute(oAxis, 3));
    og.setAttribute('aRad', new THREE.Float32BufferAttribute(oRad, 1)); og.setAttribute('aSeed', new THREE.Float32BufferAttribute(oSeed, 1));
    this.orbit = new THREE.Points(og, mk(orbit));
    this.orbit.frustumCulled = false;

    for (const o of [this.body, this.mesh, this.orbit]) { this.group.add(o); this.disposables.push(o.geometry, o.material); }
    const s = LAYOUT.heart.radius;
    this.group.scale.setScalar(s);
    this.group.position.set(LAYOUT.heart.x, LAYOUT.heart.y, 0);
  }
  update(dt, now) { this.group.rotation.y = Math.sin(now * 0.5) * 0.5; }
  dispose() { for (const d of this.disposables) d.dispose(); this.disposables.length = 0; this.group.clear(); }
}
