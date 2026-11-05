// Energy orb: a sphere of energy points, two counter-rotating neural lattices, a luminous core
// and orbital rings with traveling highlights. Larger than the heart, smaller than the face.
import * as THREE from '../vendor/three.module.min.js';
import { points, lattice, core, ring } from '../shaders/orb.glsl.js';
import { LAYOUT } from '../core/scene.js';

function mulberry(seed) { let a = seed >>> 0; return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

export class EnergyOrb {
  constructor(q, uniforms) {
    this.group = new THREE.Group();
    this.disposables = [];
    const rnd = mulberry(4242), N = q.orbPts;
    const mk = (s, extra = {}) => new THREE.ShaderMaterial({ uniforms: { ...uniforms, ...(extra.local || {}) }, vertexShader: s.vert, fragmentShader: s.frag,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: extra.side });

    // Fibonacci sphere of energy points
    const pos = new Float32Array(N * 3), seed = new Float32Array(N), size = new Float32Array(N);
    const ga = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = ga * i;
      pos.set([Math.cos(th) * r, y, Math.sin(th) * r], i * 3); seed[i] = rnd(); size[i] = 0.018 + rnd() * 0.02;
    }
    const pg = new THREE.BufferGeometry();
    pg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    pg.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1)); pg.setAttribute('aSize', new THREE.BufferAttribute(size, 1));
    this.shell = new THREE.Points(pg, mk(points));

    // two lattices, counter-rotating
    const wf = (detail) => new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(1, detail));
    this.outer = new THREE.LineSegments(wf(q.name === 'low' ? 2 : 3), mk(lattice, { local: { uRadius: { value: 1.0 } } }));
    this.inner = new THREE.LineSegments(wf(2), mk(lattice, { local: { uRadius: { value: 0.62 } } }));

    // core
    this.core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.46, 3), mk(core));

    // orbital rings
    this.rings = [];
    for (let k = 0; k < 3; k++) {
      const seg = 96, p = new Float32Array((seg + 1) * 3), t = new Float32Array(seg + 1);
      for (let i = 0; i <= seg; i++) { const a = (i / seg) * Math.PI * 2; p.set([Math.cos(a) * 1.28, 0, Math.sin(a) * 1.28], i * 3); t[i] = i / seg; }
      const rg = new THREE.BufferGeometry();
      rg.setAttribute('position', new THREE.BufferAttribute(p, 3)); rg.setAttribute('aT', new THREE.BufferAttribute(t, 1));
      const line = new THREE.Line(rg, mk(ring));
      line.rotation.set(0.6 + k * 0.9, k * 1.1, k * 0.5);
      this.rings.push(line);
    }
    const parts = [this.shell, this.outer, this.inner, this.core, ...this.rings];
    for (const o of parts) { this.group.add(o); this.disposables.push(o.geometry, o.material); }
    this.group.scale.setScalar(LAYOUT.orb.radius);
    this.group.position.set(LAYOUT.orb.x, LAYOUT.orb.y, 0);
  }
  update(dt, now, p) {
    const spin = 0.15 + p.orb * 0.9;
    this.outer.rotation.y += dt * spin; this.outer.rotation.x += dt * spin * 0.3;
    this.inner.rotation.y -= dt * spin * 1.4; this.inner.rotation.z += dt * spin * 0.5;
    this.shell.rotation.y += dt * spin * 0.35;
    this.rings.forEach((r, i) => { r.rotation.y += dt * spin * (0.4 + i * 0.25) * (i % 2 ? -1 : 1); });
  }
  dispose() { for (const d of this.disposables) d.dispose(); this.disposables.length = 0; this.group.clear(); }
}
