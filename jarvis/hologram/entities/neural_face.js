// Neural face: a procedurally generated head-and-shoulders bust rendered as
//   skin surface + wire grid + neural chords + accent curves + glowing nodes + curly hair strands + eyes.
// Everything is built once per quality tier; animation is entirely in the vertex shaders
// (jaw hinge, profile morph, sway), driven by shared uniforms. Nothing is rebuilt per frame.
// The head is generic and invented from math; it is not modelled on any real person.

import * as THREE from '../vendor/three.module.min.js';
import { surface, wire, nodes, hair, eyes } from '../shaders/face.glsl.js';

const TAU = Math.PI * 2;
const Y_TOP = 1.02, Y_BOT = -1.32;

// Control tables: y, half-width (x), half-depth (z). Catmull-Rom interpolated.
const Y = [1.02, 0.98, 0.92, 0.82, 0.68, 0.50, 0.32, 0.12, -0.08, -0.26, -0.42, -0.54, -0.62, -0.72, -0.84, -0.96, -1.06, -1.16, -1.32];
const A = [0.00, 0.20, 0.32, 0.43, 0.52, 0.585, 0.61, 0.605, 0.575, 0.52, 0.43, 0.31, 0.215, 0.235, 0.26, 0.36, 0.70, 1.15, 1.45];
const B = [0.00, 0.22, 0.34, 0.45, 0.54, 0.60, 0.63, 0.62, 0.59, 0.55, 0.48, 0.38, 0.27, 0.25, 0.26, 0.30, 0.38, 0.50, 0.62];

function lookup(tbl, y) {
  // descending Y table
  let i = 0;
  while (i < Y.length - 2 && y < Y[i + 1]) i++;
  const y0 = Y[i], y1 = Y[i + 1];
  const t = Math.min(1, Math.max(0, (y0 - y) / (y0 - y1)));
  const p0 = tbl[Math.max(0, i - 1)], p1 = tbl[i], p2 = tbl[i + 1], p3 = tbl[Math.min(tbl.length - 1, i + 2)];
  const t2 = t * t, t3 = t2 * t;
  return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
}
const g = (x, c, s) => { const d = (x - c) / s; return Math.exp(-d * d); };
const sstep = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

/** Surface point for height y and angle th (0 = straight ahead, +pi/2 = right). shape 0 = JARVIS, 1 = Bihansa. */
export function vertexAt(shape, y, th) {
  let a = lookup(A, y), b = lookup(B, y);
  if (shape > 0) {                                  // Bihansa: narrower jaw, softer chin, fuller cheeks
    a *= 1 - 0.10 * sstep(0.1, -0.45, y) * Math.min(1, Math.max(0, (0.9 - y) * 3));
    b *= 1 - 0.07 * g(y, -0.52, 0.12);
  }
  a = Math.max(0, a); b = Math.max(0, b);
  const s = Math.sin(th), c = Math.cos(th);
  let x = a * s, z = b * c;
  const wf = sstep(0.1, 0.85, c);                   // front weight
  const ax = Math.abs(x);
  const nose = shape ? 0.85 : 1.0;
  let dz = 0;
  dz += 0.15 * nose * g(x, 0, 0.045 + 0.02 * sstep(0.05, -0.02, y)) * sstep(0.34, 0.03, y) * (1 - sstep(-0.01, -0.07, y));
  dz += 0.045 * nose * g(ax, 0.075, 0.028) * g(y, -0.02, 0.035);
  dz += (shape ? 0.02 : 0.034) * g(y, 0.40, 0.045) * (1 - sstep(0.30, 0.50, ax));
  dz -= 0.052 * g(ax, 0.22, 0.09) * g(y, 0.31, 0.06);
  dz += (shape ? 0.05 : 0.034) * g(ax, 0.38, 0.12) * g(y, 0.12, 0.09);
  dz += (shape ? 0.045 : 0.035) * g(y, -0.20, 0.034) * (1 - sstep(0.10, 0.22, ax));
  dz += 0.046 * g(y, -0.52, 0.07) * g(x, 0, 0.18) * (shape ? 0.8 : 1.0);
  dz += 0.02 * g(y, 0.62, 0.12);
  z += dz * wf;
  // ears
  x += Math.sign(s) * 0.05 * g(y, 0.2, 0.1) * Math.pow(Math.abs(s), 6);
  return [x, y, z];
}

function mulberry(seed) { let a = seed >>> 0; return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

export class NeuralFace {
  constructor(q, uniforms) {
    this.q = q;
    this.group = new THREE.Group();
    this.disposables = [];
    const [C, R] = q.grid;
    const rnd = mulberry(1337);

    // ── grid vertices for both shapes ──
    const n = C * R;
    const posA = new Float32Array(n * 3), posB = new Float32Array(n * 3);
    const seed = new Float32Array(n);
    for (let r = 0; r < R; r++) {
      const y = Y_TOP + (Y_BOT - Y_TOP) * (r / (R - 1));
      for (let c = 0; c < C; c++) {
        const th = (c / C) * TAU, i = r * C + c;
        const pa = vertexAt(0, y, th), pb = vertexAt(1, y, th);
        posA.set(pa, i * 3); posB.set(pb, i * 3); seed[i] = rnd();
      }
    }
    const attrA = new THREE.BufferAttribute(posA, 3), attrB = new THREE.BufferAttribute(posB, 3);
    const attrSeed = new THREE.BufferAttribute(seed, 1);

    // ── skin surface ──
    const tri = [];
    for (let r = 0; r < R - 1; r++) for (let c = 0; c < C; c++) {
      const c2 = (c + 1) % C, i = r * C + c, i2 = r * C + c2, j = (r + 1) * C + c, j2 = (r + 1) * C + c2;
      tri.push(i, j, i2, i2, j, j2);
    }
    const sg = new THREE.BufferGeometry();
    sg.setAttribute('position', attrA); sg.setAttribute('positionB', attrB);
    sg.setIndex(tri); sg.computeVertexNormals();
    const normals = sg.getAttribute('normal');
    const mk = (shader, extra = {}) => new THREE.ShaderMaterial({
      uniforms, vertexShader: shader.vert, fragmentShader: shader.frag,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, ...extra,
    });
    this.surface = new THREE.Mesh(sg, mk(surface, { side: THREE.FrontSide }));
    this.surface.renderOrder = 1;

    // ── wire grid (rings + meridians) ──
    const lines = [];
    for (let r = 0; r < R - 1; r++) for (let c = 0; c < C; c++) {
      const i = r * C + c;
      lines.push(i, r * C + (c + 1) % C);          // ring
      lines.push(i, (r + 1) * C + c);              // meridian
    }
    const wg = new THREE.BufferGeometry();
    wg.setAttribute('position', attrA); wg.setAttribute('positionB', attrB); wg.setAttribute('normal', normals);
    wg.setAttribute('aSeed', attrSeed); wg.setIndex(lines);
    this.wire = new THREE.LineSegments(wg, mk(wire, { defines: { KIND: 0 } }));
    this.wire.renderOrder = 2;

    // ── neural chords: longer links between nearby grid vertices, front-biased ──
    const chordCount = Math.floor(2200 * q.nodes);
    const chords = [];
    for (let k = 0; k < chordCount; k++) {
      const r = 3 + Math.floor(rnd() * (R * 0.75));
      const c = Math.floor(rnd() * C);
      const th = (c / C) * TAU;
      if (Math.cos(th) < -0.35 && rnd() < 0.7) continue;
      const dr = Math.floor((rnd() - 0.5) * 12), dc = Math.floor((rnd() - 0.5) * 18);
      const r2 = Math.min(R - 2, Math.max(1, r + dr)), c2 = (c + dc + C * 4) % C;
      if (Math.abs(dr) + Math.abs(dc) < 4) continue;
      chords.push(r * C + c, r2 * C + c2);
    }
    const cg = new THREE.BufferGeometry();
    cg.setAttribute('position', attrA); cg.setAttribute('positionB', attrB); cg.setAttribute('normal', normals);
    cg.setAttribute('aSeed', attrSeed); cg.setIndex(chords);
    this.chords = new THREE.LineSegments(cg, mk(wire, { defines: { KIND: 1 } }));
    this.chords.renderOrder = 3;

    // ── accent curves: eyes, brows, lips, nose, jaw line ──
    const acc = [];                                   // arrays of [x,y] polylines
    const ell = (cx, cy, rx, ry, steps = 18) => Array.from({ length: steps + 1 }, (_, k) => { const a = (k / steps) * TAU; return [cx + rx * Math.cos(a), cy + ry * Math.sin(a)]; });
    for (const sgn of [-1, 1]) {
      acc.push(ell(sgn * 0.215, 0.31, 0.115, 0.042));
      acc.push(Array.from({ length: 12 }, (_, k) => { const t = k / 11; return [sgn * (0.10 + 0.24 * t), 0.405 + 0.03 * Math.sin(t * Math.PI) - 0.012 * t]; }));
    }
    acc.push(Array.from({ length: 16 }, (_, k) => { const t = k / 15; return [-0.15 + 0.3 * t, -0.20 + 0.014 * Math.sin(t * TAU * 1.5)]; }));
    acc.push(ell(0, -0.215, 0.14, 0.04, 20));
    acc.push(Array.from({ length: 10 }, (_, k) => [0, 0.32 - k * 0.034]));
    acc.push(Array.from({ length: 14 }, (_, k) => { const t = k / 13; return [-0.21 + 0.42 * t, -0.005 + (Math.abs(t - 0.5) < 0.1 ? 0.02 : -0.02) * 0.6]; }));
    const accPosA = [], accPosB = [], accSeed = [];
    for (const poly of acc) for (let k = 0; k < poly.length - 1; k++) {
      for (const [x, y] of [poly[k], poly[k + 1]]) {
        const a0 = lookup(A, y), th = Math.asin(Math.max(-0.999, Math.min(0.999, x / Math.max(0.05, a0))));
        const pa = vertexAt(0, y, th), pb = vertexAt(1, y, th);
        accPosA.push(pa[0], pa[1], pa[2] + 0.008); accPosB.push(pb[0], pb[1], pb[2] + 0.008); accSeed.push(rnd());
      }
    }
    const ag = new THREE.BufferGeometry();
    ag.setAttribute('position', new THREE.Float32BufferAttribute(accPosA, 3));
    ag.setAttribute('positionB', new THREE.Float32BufferAttribute(accPosB, 3));
    ag.setAttribute('normal', new THREE.Float32BufferAttribute(new Float32Array(accPosA.length).map((_, i) => (i % 3 === 2 ? 1 : 0)), 3));
    ag.setAttribute('aSeed', new THREE.Float32BufferAttribute(accSeed, 1));
    this.accents = new THREE.LineSegments(ag, mk(wire, { defines: { KIND: 2 } }));
    this.accents.renderOrder = 4;

    // ── glowing nodes on the skin ──
    const nodeIdx = [];
    const want = Math.floor(n * 0.13 * q.nodes);
    for (let k = 0; k < want; k++) nodeIdx.push(Math.floor(rnd() * n));
    for (let k = 0; k < chords.length; k += 3) nodeIdx.push(chords[k]);
    const nPos = [], nPosB = [], nSeed = [], nSize = [], nKind = [], nT = [];
    for (const i of nodeIdx) {
      nPos.push(posA[i * 3], posA[i * 3 + 1], posA[i * 3 + 2]); nPosB.push(posB[i * 3], posB[i * 3 + 1], posB[i * 3 + 2]);
      nSeed.push(rnd()); nSize.push(0.012 + rnd() * 0.02); nKind.push(0); nT.push(0);
    }

    // ── curly hair ──
    const strands = q.hair, M = 12;
    const hPosA = new Float32Array(strands * (M - 1) * 2 * 3), hPosB = new Float32Array(hPosA.length);
    const hT = new Float32Array(strands * (M - 1) * 2), hSeed = new Float32Array(hT.length);
    let w = 0;
    const strandPath = (shape, th, y, L, curl, hand, drapeExtra) => {
      const base = vertexAt(shape, y, th);
      const rad = [Math.sin(th), Math.cos(th)];       // radial direction in xz
      const frontness = sstep(0.2, 0.9, Math.cos(th));
      const pts = [];
      for (let m = 0; m < M; m++) {
        const t = m / (M - 1);
        const out = L * (0.34 * Math.sin(t * Math.PI * 0.5) + 0.10 * t);
        const down = L * (0.55 + drapeExtra) * t * t * (1 - 0.85 * frontness);
        const up = frontness * 0.10 * Math.sin(t * Math.PI);
        const ang = hand * (t * (9 + curl * 5) + th);
        const cr = 0.045 * curl * Math.sin(Math.min(1, t * 1.15) * Math.PI * 0.85 + 0.15);
        pts.push([
          base[0] * 1.03 + rad[0] * out + cr * Math.cos(ang) * rad[1],
          base[1] - down + up + cr * Math.sin(ang),
          base[2] * 1.03 + rad[1] * out - cr * Math.cos(ang) * rad[0],
        ]);
      }
      return pts;
    };
    for (let s = 0; s < strands; s++) {
      let th, y;
      for (let tries = 0; tries < 12; tries++) {
        th = rnd() * TAU; y = 0.30 + Math.pow(rnd(), 0.65) * 0.70;
        const front = Math.cos(th) > 0.30;
        const hairline = 0.76 - 0.34 * sstep(0.3, 1.0, Math.abs(Math.sin(th)));  // lower at the sides
        if (front && y < hairline + 0.05) continue;
        break;
      }
      const L = 0.30 + rnd() * 0.42, curl = 0.5 + rnd() * 0.8, hand = rnd() < 0.5 ? -1 : 1, extra = rnd() * 0.35;
      const pa = strandPath(0, th, y, L, curl, hand, 0), pb = strandPath(1, th, y, L * 1.5, curl * 0.7, hand, 0.55 + extra);
      const sd = rnd();
      for (let m = 0; m < M - 1; m++) {
        for (const [pt, ptb, tt] of [[pa[m], pb[m], m / (M - 1)], [pa[m + 1], pb[m + 1], (m + 1) / (M - 1)]]) {
          hPosA.set(pt, w * 3); hPosB.set(ptb, w * 3); hT[w] = tt; hSeed[w] = sd; w++;
        }
      }
      if (s % 3 === 0) for (const m of [3, 6, 9, 11]) {
        nPos.push(...pa[m]); nPosB.push(...pb[m]); nSeed.push(sd); nSize.push(0.010 + rnd() * 0.012); nKind.push(1); nT.push(m / (M - 1));
      }
    }
    const hg = new THREE.BufferGeometry();
    hg.setAttribute('position', new THREE.BufferAttribute(hPosA, 3)); hg.setAttribute('positionB', new THREE.BufferAttribute(hPosB, 3));
    hg.setAttribute('aT', new THREE.BufferAttribute(hT, 1)); hg.setAttribute('aSeed', new THREE.BufferAttribute(hSeed, 1));
    this.hair = new THREE.LineSegments(hg, mk(hair));
    this.hair.renderOrder = 2;

    const ng = new THREE.BufferGeometry();
    ng.setAttribute('position', new THREE.Float32BufferAttribute(nPos, 3)); ng.setAttribute('positionB', new THREE.Float32BufferAttribute(nPosB, 3));
    ng.setAttribute('aSeed', new THREE.Float32BufferAttribute(nSeed, 1)); ng.setAttribute('aSize', new THREE.Float32BufferAttribute(nSize, 1));
    ng.setAttribute('aKind', new THREE.Float32BufferAttribute(nKind, 1)); ng.setAttribute('aT', new THREE.Float32BufferAttribute(nT, 1));
    this.nodes = new THREE.Points(ng, mk(nodes));
    this.nodes.renderOrder = 5;

    // ── eyes ──
    const eg = new THREE.BufferGeometry();
    const eA = [], eB = [];
    for (const sgn of [-1, 1]) {
      const th = Math.asin(sgn * 0.215 / lookup(A, 0.31));
      const pa = vertexAt(0, 0.31, th), pb = vertexAt(1, 0.31, th);
      eA.push(pa[0], pa[1], pa[2] + 0.02); eB.push(pb[0], pb[1], pb[2] + 0.02);
    }
    eg.setAttribute('position', new THREE.Float32BufferAttribute(eA, 3)); eg.setAttribute('positionB', new THREE.Float32BufferAttribute(eB, 3));
    eg.setAttribute('aSide', new THREE.Float32BufferAttribute([-1, 1], 1));
    this.eyes = new THREE.Points(eg, mk(eyes));
    this.eyes.renderOrder = 6;

    for (const o of [this.surface, this.wire, this.chords, this.accents, this.hair, this.nodes, this.eyes]) {
      this.group.add(o); this.disposables.push(o.geometry, o.material);
    }
    this.vertexCount = n;
  }

  dispose() {
    for (const d of this.disposables) d.dispose();
    this.disposables.length = 0;
    this.group.clear();
  }
}
