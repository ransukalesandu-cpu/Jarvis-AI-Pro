/**
 * The circuit-board face, designed on MediaPipe landmarks (the head mesh keeps MediaPipe's vertex
 * order: 1 nose tip, 10 forehead top, 152 chin, 33/263 eye corners, ...). Everything here is pure
 * geometry on vertex indices, so lines drawn from it share the head's vertex buffer and move with
 * the talking jaw. Paths are drawn on the face's right side and mirrored, so the face is symmetric.
 */
import mesh from './headMesh.json';
import { rng } from './glass';

const V = mesh.verts;
const N = V.length / 3;
const x = (i: number) => V[i * 3], y = (i: number) => V[i * 3 + 1], z = (i: number) => V[i * 3 + 2];

export function adjacency(): number[][] {
  const adj: number[][] = Array.from({ length: N }, () => []);
  const f = mesh.faces;
  const link = (a: number, b: number) => { if (!adj[a].includes(b)) { adj[a].push(b); adj[b].push(a); } };
  for (let i = 0; i < f.length; i += 3) { link(f[i], f[i + 1]); link(f[i + 1], f[i + 2]); link(f[i + 2], f[i]); }
  return adj;
}

/** For every vertex, the vertex closest to its mirror image across x = 0. */
export function mirrorMap(): Int32Array {
  const m = new Int32Array(N);
  for (let i = 0; i < N; i++) {
    let best = i, bd = Infinity;
    const mx = -x(i), my = y(i), mz = z(i);
    for (let j = 0; j < N; j++) {
      const d = (x(j) - mx) ** 2 + (y(j) - my) ** 2 + (z(j) - mz) ** 2;
      if (d < bd) { bd = d; best = j; }
    }
    m[i] = best;
  }
  return m;
}

/** Shortest path along mesh edges (fewest hops, then shortest length), as vertex indices. */
export function meshPath(adj: number[][], from: number, to: number, avoid?: (v: number) => boolean): number[] {
  const prev = new Int32Array(N).fill(-1);
  const dist = new Float64Array(N).fill(Infinity);
  dist[from] = 0;
  const open = [from];
  while (open.length) {
    let k = 0;
    for (let i = 1; i < open.length; i++) if (dist[open[i]] < dist[open[k]]) k = i;
    const v = open.splice(k, 1)[0];
    if (v === to) break;
    for (const w of adj[v]) {
      if (avoid && w !== to && avoid(w)) continue;
      const d = dist[v] + Math.hypot(x(w) - x(v), y(w) - y(v), z(w) - z(v));
      if (d < dist[w]) { if (dist[w] === Infinity) open.push(w); dist[w] = d; prev[w] = v; }
    }
  }
  if (prev[to] < 0 && from !== to) return [];
  const out = [to];
  while (out[out.length - 1] !== from) out.push(prev[out[out.length - 1]]);
  return out.reverse();
}

// MediaPipe landmark loops (the face's right side is negative x here).
export const LIPS_OUTER = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185, 61];
export const LIPS_MID = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191, 78];
export const EYE_R = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246, 33];
export const EYE_L = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466, 263];
export const BROW_R = [46, 53, 52, 65, 55];
export const BROW_L = [276, 283, 282, 295, 285];
export const FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152,
  148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109, 10];
export const NOSE_RIDGE = [168, 6, 197, 195, 5, 4, 1];

/** Designed traces (right side, mirrored): the forehead channel, brow and temple lines, cheek runs and jaw drops. */
const DESIGN: [number, number][] = [
  [109, 107],   // forehead channel wall down to the inner brow
  [67, 66],     // forehead to mid brow
  [103, 105],   // upper forehead to brow
  [54, 70],     // temple top to brow end
  [70, 127],    // brow end down the temple
  [55, 193],    // inner brow down beside the nose bridge
  [193, 129],   // beside the nose to the nose wing
  [226, 116],   // outer eye to the cheekbone
  [116, 192],   // cheekbone down the cheek
  [192, 61],    // cheek to the mouth corner
  [129, 205],   // nose wing across the cheek
  [205, 172],   // cheek down to the jaw angle
  [61, 136],    // mouth corner to the jaw
  [146, 150],   // under the lip to the jaw
  [234, 132],   // side of the face to the jaw angle
  [151, 108],   // forehead centre out
];

const pairs = (loop: number[]) => { const s: number[] = []; for (let i = 0; i < loop.length - 1; i++) s.push(loop[i], loop[i + 1]); return s; };

export interface FaceCircuit {
  main: number[];      // bright designed traces, as index pairs
  contour: number[];   // lips, eyes, brows, face oval
  fill: number[];      // fine background traces
  nose: number[];      // the blue nose ridge
  vias: number[];      // trace ends
  paths: number[][];   // for the running current
}

export function buildFaceCircuit(): FaceCircuit {
  const adj = adjacency();
  const mir = mirrorMap();
  const nearEye = (v: number) => z(v) > 0 && [mesh.eyeL, mesh.eyeR].some((e) => (x(v) - e[0]) ** 2 + (y(v) - e[1]) ** 2 < 0.1 ** 2);
  const main: number[] = [], vias: number[] = [], paths: number[][] = [];
  for (const [a, b] of DESIGN) {
    const p = meshPath(adj, a, b, nearEye);
    if (p.length < 2) continue;
    for (const path of [p, p.map((v) => mir[v])]) {
      paths.push(path);
      main.push(...pairs(path));
      vias.push(path[0], path[path.length - 1]);
    }
  }
  // Fine traces filling the skull and cheeks: short right-angled walks, mirrored.
  const r = rng(91);
  const fill: number[] = [];
  for (let tries = 0, made = 0; made < 34 && tries < 600; tries++) {
    let v = Math.floor(r() * N);
    if (x(v) > -0.05 || z(v) < -0.2 || nearEye(v)) continue;
    let d: [number, number] = r() < 0.6 ? [0, r() < 0.5 ? 1 : -1] : [-1, 0];
    const path = [v], used = new Set(path);
    for (let s = 0; s < 4 + Math.floor(r() * 8); s++) {
      if (r() < 0.25) d = d[0] === 0 ? [-1, 0] : [0, r() < 0.5 ? 1 : -1];
      let best = -1, score = 0.5;
      for (const w of adj[v]) {
        if (used.has(w) || nearEye(w) || x(w) > -0.02) continue;
        const dx = x(w) - x(v), dy = y(w) - y(v), l = Math.hypot(dx, dy) || 1;
        const sc = (dx * d[0] + dy * d[1]) / l;
        if (sc > score) { score = sc; best = w; }
      }
      if (best < 0) break;
      path.push(best); used.add(best); v = best;
    }
    if (path.length < 3) continue;
    made++;
    for (const p of [path, path.map((u) => mir[u])]) { fill.push(...pairs(p)); vias.push(p[p.length - 1]); paths.push(p); }
  }
  const contour = [...pairs(LIPS_OUTER), ...pairs(LIPS_MID), ...pairs(EYE_R), ...pairs(EYE_L), ...pairs(BROW_R), ...pairs(BROW_L), ...pairs(FACE_OVAL)];
  return { main, contour, fill, nose: pairs(NOSE_RIDGE), vias, paths };
}

/** Front surface of the neck (it is a low-poly tube): z for a given x, fitted to its vertex rings. */
export const neckZ = (xx: number) => -0.1 + 0.45 * Math.sqrt(Math.max(0, 1 - (xx / 0.58) ** 2)) + 0.012;

/**
 * Neck traces like the reference: vertical runs from under the jaw down to the base, some stepping
 * sideways half-way, with ring vias on every other run. Returned as straight segments in head space
 * (the neck does not move with the jaw).
 */
export function neckRuns(count = 10): { segs: number[]; rings: [number, number, number][]; paths: [number, number, number][][] } {
  const segs: number[] = [], rings: [number, number, number][] = [], paths: [number, number, number][][] = [];
  const top = -1.05, bottom = -1.31;
  for (let k = 0; k < count; k++) {
    const x0 = -0.42 + (0.84 * k) / (count - 1);
    const step = k % 3 === 1 ? Math.sign(x0 || 1) * 0.05 : 0;
    const mid = top + (bottom - top) * (0.35 + 0.1 * (k % 2));
    const pts: [number, number][] = step ? [[x0, top], [x0, mid], [x0 + step, mid - 0.04], [x0 + step, bottom]] : [[x0, top], [x0, bottom]];
    const path = pts.map(([xx, yy]) => [xx, yy, neckZ(xx)] as [number, number, number]);
    for (let i = 0; i < path.length - 1; i++) segs.push(...path[i], ...path[i + 1]);
    paths.push(path);
    if (k % 2 === 1) { const yy = top + (bottom - top) * 0.62; rings.push([x0 + step, yy, neckZ(x0 + step)]); }
  }
  return { segs, rings, paths };
}
