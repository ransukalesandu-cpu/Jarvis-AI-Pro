/**
 * Splits the reshaped head into mechanical panels (forehead plate, brows, temples, sockets,
 * cheekbones, cheeks, nose, muzzle, chin, jaw sides, skull plates). Pure geometry: a geodesic
 * Voronoi over the mesh from landmark seeds, built on one side and mirrored, so panels are symmetric.
 * Vertices that move with the jaw can only belong to jaw panels (and vice versa), so the jaw is a
 * clean, separate part that hinges at the existing pivot.
 */
import mesh from '../headMesh.json';
import { adjacency, mirrorMap } from '../faceCircuit';
import { SHAPED } from '../shape';

export const NECK_CUT = -1.02;       // triangles whose centroid is below this are the neck (built as rings)
export const JAW_MIN = 0.5;          // jaw weight from which a vertex belongs to the hinged jaw

const V = SHAPED;
const N = V.length / 3;
const pt = (i: number): [number, number, number] => [V[i * 3], V[i * 3 + 1], V[i * 3 + 2]];

export interface Region { name: string; jaw: boolean; seeds: number[] }

function nearest(p: [number, number, number], ok: (i: number) => boolean = () => true): number {
  let best = 0, bd = Infinity;
  for (let i = 0; i < N; i++) {
    if (!ok(i)) continue;
    const d = (V[i * 3] - p[0]) ** 2 + (V[i * 3 + 1] - p[1]) ** 2 + (V[i * 3 + 2] - p[2]) ** 2;
    if (d < bd) { bd = d; best = i; }
  }
  return best;
}

const isJaw = (i: number) => mesh.jaw[i] >= JAW_MIN;

/** The panel layout: [name, seeds on the face's -x side or centre line]. Sided entries are mirrored. */
function layout(): Region[] {
  const mir = mirrorMap();
  let minZ = Infinity, maxX = 0, crown = -Infinity;
  for (let i = 0; i < N; i++) { minZ = Math.min(minZ, V[i * 3 + 2]); maxX = Math.max(maxX, Math.abs(V[i * 3])); crown = Math.max(crown, V[i * 3 + 1]); }
  let jawSide = -1;
  for (let i = 0; i < N; i++) if (isJaw(i) && V[i * 3] < 0 && (jawSide < 0 || V[i * 3] < V[jawSide * 3])) jawSide = i;
  const centre: [string, number[]][] = [
    ['forehead', [151]], ['noseBridge', [6]], ['noseTip', [4]], ['muzzle', [164]],
    ['crown', [nearest([0, crown, -0.1])]], ['occiput', [nearest([0, 0.35, minZ])]], ['nape', [nearest([0, -0.6, -0.6])]],
  ];
  const sided: [string, number[]][] = [
    ['brow', [105]], ['temple', [54]], ['socket', [159, 145]], ['cheekbone', [116]], ['cheek', [207]],
    ['jawAngle', [136]], ['temporal', [234]], ['parietal', [nearest([-maxX * 0.85, 0.5, -0.3])]],
  ];
  const out: Region[] = [];
  for (const [name, seeds] of centre) out.push({ name, jaw: false, seeds });
  out.push({ name: 'chin', jaw: true, seeds: [175, 17] });
  for (const [name, seeds] of sided) {
    out.push({ name: `${name}R`, jaw: false, seeds });
    out.push({ name: `${name}L`, jaw: false, seeds: seeds.map((s) => mir[s]) });
  }
  out.push({ name: 'jawR', jaw: true, seeds: [jawSide] });
  out.push({ name: 'jawL', jaw: true, seeds: [mir[jawSide]] });
  return out;
}

export interface Partition {
  regions: Region[];
  vertexRegion: Int32Array;    // per vertex (-1 = neck / unreached)
  triRegion: Int32Array;       // per triangle of mesh.faces (-1 = neck)
}

/** Geodesic Voronoi from the seeds; jaw vertices only reachable from jaw seeds and vice versa. */
export function partition(): Partition {
  const regions = layout();
  const adj = adjacency();
  const dist = new Float64Array(N).fill(Infinity);
  const owner = new Int32Array(N).fill(-1);
  const open: number[] = [];
  regions.forEach((r, k) => r.seeds.forEach((s) => { dist[s] = 0; owner[s] = k; open.push(s); }));
  while (open.length) {
    let m = 0;
    for (let i = 1; i < open.length; i++) if (dist[open[i]] < dist[open[m]]) m = i;
    const v = open.splice(m, 1)[0];
    const jawSide = regions[owner[v]].jaw;
    for (const w of adj[v]) {
      if (isJaw(w) !== jawSide) continue;
      if (V[w * 3 + 1] < NECK_CUT - 0.1) continue;
      const d = dist[v] + Math.hypot(V[w * 3] - V[v * 3], V[w * 3 + 1] - V[v * 3 + 1], V[w * 3 + 2] - V[v * 3 + 2]);
      if (d < dist[w] - 1e-12 || (Math.abs(d - dist[w]) <= 1e-12 && owner[v] < owner[w])) {
        if (dist[w] === Infinity) open.push(w);
        dist[w] = d; owner[w] = owner[v];
      }
    }
  }
  const f = mesh.faces;
  const tri = new Int32Array(f.length / 3).fill(-1);
  for (let t = 0; t < tri.length; t++) {
    const a = f[t * 3], b = f[t * 3 + 1], c = f[t * 3 + 2];
    if ((V[a * 3 + 1] + V[b * 3 + 1] + V[c * 3 + 1]) / 3 < NECK_CUT) continue;
    const owners = [owner[a], owner[b], owner[c]].filter((o) => o >= 0);
    if (!owners.length) continue;
    // Majority; on a three-way tie, the owner whose seed is closest to the centroid.
    const count = (o: number) => owners.filter((x) => x === o).length;
    let best = owners[0];
    for (const o of owners) if (count(o) > count(best)) best = o;
    if (count(best) === 1 && owners.length > 1) {
      const cx = (V[a * 3] + V[b * 3] + V[c * 3]) / 3, cy = (V[a * 3 + 1] + V[b * 3 + 1] + V[c * 3 + 1]) / 3, cz = (V[a * 3 + 2] + V[b * 3 + 2] + V[c * 3 + 2]) / 3;
      const sd = (o: number) => Math.min(...regions[o].seeds.map((s) => { const p = pt(s); return (p[0] - cx) ** 2 + (p[1] - cy) ** 2 + (p[2] - cz) ** 2; }));
      best = owners.reduce((x, y) => (sd(y) < sd(x) ? y : x));
    }
    tri[t] = best;
  }
  smooth(tri, regions);
  return { regions, vertexRegion: owner, triRegion: tri };
}

/**
 * A Voronoi over triangles leaves saw-tooth borders. A few synchronous passes let a triangle take
 * the panel that two of its three neighbours share (never across the jaw line), which straightens
 * the grooves while keeping the layout symmetric.
 */
export function smooth(tri: Int32Array, regions: Region[], passes = 4): void {
  const f = mesh.faces;
  const byEdge = new Map<string, number>();
  const nb: number[][] = Array.from({ length: tri.length }, () => []);
  for (let t = 0; t < tri.length; t++) for (let k = 0; k < 3; k++) {
    const a = f[t * 3 + k], b = f[t * 3 + (k + 1) % 3];
    const o = byEdge.get(`${b},${a}`);
    if (o !== undefined) { nb[t].push(o); nb[o].push(t); }
    byEdge.set(`${a},${b}`, t);
  }
  for (let p = 0; p < passes; p++) {
    const prev = Int32Array.from(tri);
    for (let t = 0; t < tri.length; t++) {
      const own = prev[t];
      if (own < 0) continue;
      const labels = nb[t].map((o) => prev[o]).filter((r) => r >= 0 && r !== own && regions[r].jaw === regions[own].jaw);
      for (const r of labels) if (labels.filter((x) => x === r).length >= 2) { tri[t] = r; break; }
    }
  }
}
