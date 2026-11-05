// Environment around the bust: orbital rings, a base disc of concentric rings, vertical data
// lines and drifting sparks. Purely atmospheric; it follows the state through uniforms.
import * as THREE from '../vendor/three.module.min.js';
import { auraRing, base, dataLine, sparks } from '../shaders/fx.glsl.js';

function mulberry(seed) { let a = seed >>> 0; return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

export class Aura {
  constructor(q, uniforms) {
    this.group = new THREE.Group();
    this.disposables = [];
    const rnd = mulberry(555);
    const mk = (s, local = {}) => new THREE.ShaderMaterial({ uniforms: { ...uniforms, ...local }, vertexShader: s.vert, fragmentShader: s.frag, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const add = (o) => { this.group.add(o); this.disposables.push(o.geometry, o.material); o.frustumCulled = false; };

    // tilted orbital rings around the head and shoulders
    this.rings = new THREE.Group();
    for (let k = 0; k < q.rings; k++) {
      const seg = 160, p = new Float32Array((seg + 1) * 3), t = new Float32Array(seg + 1);
      const rx = 1.35 + k * 0.17 + rnd() * 0.1, rz = rx * (0.7 + rnd() * 0.2);
      for (let i = 0; i <= seg; i++) { const a = (i / seg) * Math.PI * 2; p.set([Math.cos(a) * rx, 0, Math.sin(a) * rz], i * 3); t[i] = i / seg; }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(p, 3)); g.setAttribute('aT', new THREE.BufferAttribute(t, 1));
      const line = new THREE.Line(g, mk(auraRing, { uRingSeed: { value: k + 1 } }));
      line.position.y = -0.85 + k * (1.7 / Math.max(1, q.rings - 1)) - 0.05;
      line.rotation.set(0.05 * (k % 2 ? 1 : -1), rnd() * 6, 0.03 * k);
      this.rings.add(line); this.disposables.push(g, line.material);
    }
    this.rings.rotation.x = 0.30;
    this.group.add(this.rings);

    // base disc: concentric rings under the bust
    const discs = new THREE.Group();
    for (let k = 0; k < 7; k++) {
      const r = 0.25 + k * 0.24, seg = 128, p = new Float32Array((seg + 1) * 3), rr = new Float32Array(seg + 1);
      for (let i = 0; i <= seg; i++) { const a = (i / seg) * Math.PI * 2; p.set([Math.cos(a) * r, 0, Math.sin(a) * r], i * 3); rr[i] = r / 1.9; }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(p, 3)); g.setAttribute('aR', new THREE.BufferAttribute(rr, 1));
      const line = new THREE.Line(g, mk(base)); discs.add(line); this.disposables.push(g, line.material);
    }
    discs.position.set(0, -1.16, 0); discs.rotation.x = 0.30;
    this.group.add(discs);

    // vertical data lines (behind everything)
    const cols = Math.floor(10 * q.nodes) + 4, lp = [], lt = [], ls = [];
    for (let c = 0; c < cols; c++) {
      const x = (c / (cols - 1) - 0.5) * 3.9 + (rnd() - 0.5) * 0.1, seed = rnd(), seg = 24, top = 1.45 - rnd() * 0.5, bot = -1.0 - rnd() * 1.3;
      for (let i = 0; i < seg; i++) { const y0 = top + (bot - top) * (i / seg), y1 = top + (bot - top) * ((i + 1) / seg); lp.push(x, y0, -0.7, x, y1, -0.7); lt.push(i / seg, (i + 1) / seg); ls.push(seed, seed); }
    }
    const dg = new THREE.BufferGeometry();
    dg.setAttribute('position', new THREE.Float32BufferAttribute(lp, 3)); dg.setAttribute('aT', new THREE.Float32BufferAttribute(lt, 1)); dg.setAttribute('aSeed', new THREE.Float32BufferAttribute(ls, 1));
    add(new THREE.LineSegments(dg, mk(dataLine)));

    // drifting sparks
    const n = Math.floor(260 * q.nodes) + 40, sp = [], ss = [], sz = [];
    for (let i = 0; i < n; i++) { sp.push((rnd() - 0.5) * 3.9, (rnd() - 0.5) * 4.2, (rnd() - 0.5) * 1.6); ss.push(rnd()); sz.push(0.012 + rnd() * 0.02); }
    const sg = new THREE.BufferGeometry();
    sg.setAttribute('position', new THREE.Float32BufferAttribute(sp, 3)); sg.setAttribute('aSeed', new THREE.Float32BufferAttribute(ss, 1)); sg.setAttribute('aSize', new THREE.Float32BufferAttribute(sz, 1));
    add(new THREE.Points(sg, mk(sparks)));
  }
  update(dt, now, p) { this.rings.rotation.y += dt * (0.05 + p.ring * 0.25); }
  dispose() { for (const d of this.disposables) d.dispose(); this.disposables.length = 0; this.group.clear(); }
}
