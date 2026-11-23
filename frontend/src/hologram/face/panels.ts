/**
 * Mechanical panels: each region of the head becomes a closed, bevelled plate raised off the skull,
 * with a real groove between neighbouring plates (the boundary is inset along the surface). The
 * grooves' centre lines are returned for the emissive engravings. Pure geometry, unit-tested.
 */
import mesh from '../headMesh.json';
import { SHAPED } from '../shape';
import { partition, type Partition } from './regions';

export interface PanelParams {
    groove: number;
    height: number;
    bevel: number;
}
export const PANEL: PanelParams = { groove: 0.011, height: 0.02, bevel: 0.007 };

export interface Panel {
    name: string;
    jaw: boolean;
    positions: Float32Array; // top, then base copies of the panel's vertices (non-indexed groups below)
    index: Uint32Array; // top + walls + bottom: a closed shell
}

export interface Engraving {
    a: number;
    b: number;
    jaw: boolean;
} // a mesh edge between two panels

/** Area-weighted vertex normals of the whole head (outward: the mesh winds counter-clockwise outside). */
export function vertexNormals(V: Float32Array = SHAPED): Float32Array {
    const n = new Float32Array(V.length);
    const f = mesh.faces;
    for (let t = 0; t < f.length; t += 3) {
        const [a, b, c] = [f[t] * 3, f[t + 1] * 3, f[t + 2] * 3];
        const ux = V[b] - V[a],
            uy = V[b + 1] - V[a + 1],
            uz = V[b + 2] - V[a + 2];
        const vx = V[c] - V[a],
            vy = V[c + 1] - V[a + 1],
            vz = V[c + 2] - V[a + 2];
        const nx = uy * vz - uz * vy,
            ny = uz * vx - ux * vz,
            nz = ux * vy - uy * vx;
        for (const o of [a, b, c]) {
            n[o] += nx;
            n[o + 1] += ny;
            n[o + 2] += nz;
        }
    }
    for (let i = 0; i < n.length; i += 3) {
        const l = Math.hypot(n[i], n[i + 1], n[i + 2]) || 1;
        n[i] /= l;
        n[i + 1] /= l;
        n[i + 2] /= l;
    }
    return n;
}

const key = (a: number, b: number) => `${a},${b}`;

/** Builds one closed panel from a set of mesh triangles. */
export function buildPanel(
    tris: number[],
    normals: Float32Array,
    p: PanelParams = PANEL,
    V: Float32Array = SHAPED,
): { positions: Float32Array; index: Uint32Array } {
    const f = mesh.faces;
    const directed = new Map<string, number>(); // directed edges inside the panel
    for (const t of tris)
        for (let k = 0; k < 3; k++) {
            const a = f[t * 3 + k],
                b = f[t * 3 + ((k + 1) % 3)];
            directed.set(key(a, b), (directed.get(key(a, b)) ?? 0) + 1);
        }
    const boundary: [number, number][] = []; // edges with no twin inside the panel
    for (const t of tris)
        for (let k = 0; k < 3; k++) {
            const a = f[t * 3 + k],
                b = f[t * 3 + ((k + 1) % 3)];
            if (!directed.has(key(b, a))) boundary.push([a, b]);
        }
    const onEdge = new Set(boundary.flat());
    const verts = [...new Set(tris.flatMap((t) => [f[t * 3], f[t * 3 + 1], f[t * 3 + 2]]))];
    const local = new Map(verts.map((v, i) => [v, i]));
    // Interior neighbours of each boundary vertex: where its inset points.
    const pull = new Map<number, [number, number, number, number]>();
    for (const t of tris)
        for (let k = 0; k < 3; k++) {
            const v = f[t * 3 + k];
            if (!onEdge.has(v)) continue;
            for (const w of [f[t * 3 + ((k + 1) % 3)], f[t * 3 + ((k + 2) % 3)]]) {
                const s = pull.get(v) ?? [0, 0, 0, 0];
                const weight = onEdge.has(w) ? 0.25 : 1; // prefer truly interior neighbours
                s[0] += V[w * 3] * weight;
                s[1] += V[w * 3 + 1] * weight;
                s[2] += V[w * 3 + 2] * weight;
                s[3] += weight;
                pull.set(v, s);
            }
        }
    const n = verts.length;
    const pos = new Float32Array(n * 2 * 3); // [0, n) top, [n, 2n) base
    verts.forEach((v, i) => {
        const o = v * 3;
        const nx = normals[o],
            ny = normals[o + 1],
            nz = normals[o + 2];
        let bx = V[o],
            by = V[o + 1],
            bz = V[o + 2];
        let tx = bx,
            ty = by,
            tz = bz,
            h = p.height;
        const s = pull.get(v);
        if (s && s[3] > 0) {
            let dx = s[0] / s[3] - bx,
                dy = s[1] / s[3] - by,
                dz = s[2] / s[3] - bz;
            const dn = dx * nx + dy * ny + dz * nz; // keep the inset on the surface (tangent plane)
            dx -= dn * nx;
            dy -= dn * ny;
            dz -= dn * nz;
            const len = Math.hypot(dx, dy, dz);
            if (len > 1e-6) {
                const g = Math.min(p.groove, len * 0.45),
                    b = Math.min(p.groove + p.bevel, len * 0.7);
                bx += (dx / len) * g;
                by += (dy / len) * g;
                bz += (dz / len) * g;
                tx = V[o] + (dx / len) * b;
                ty = V[o + 1] + (dy / len) * b;
                tz = V[o + 2] + (dz / len) * b;
            }
            h = p.height * 0.75; // bevelled edge sits a little lower
        }
        pos.set([tx + nx * h, ty + ny * h, tz + nz * h], i * 3);
        pos.set([bx, by, bz], (n + i) * 3);
    });
    const idx: number[] = [];
    for (const t of tris) {
        const a = local.get(f[t * 3])!,
            b = local.get(f[t * 3 + 1])!,
            c = local.get(f[t * 3 + 2])!;
        idx.push(a, b, c, n + c, n + b, n + a); // top, and the bottom reversed
    }
    for (const [ga, gb] of boundary) {
        const a = local.get(ga)!,
            b = local.get(gb)!;
        idx.push(b, a, n + a, b, n + a, n + b); // the wall along the groove
    }
    return { positions: pos, index: Uint32Array.from(idx) };
}

export interface MechanicalFace {
    panels: Panel[];
    engravings: Engraving[];
    partition: Partition;
    positions: Float32Array;
    normals: Float32Array;
}

/**
 * Straightens the grooves: vertices on a border between exactly two panels slide toward the midpoint
 * of their two border neighbours (junctions stay put). Topology is unchanged; only the head's
 * positions move, so plates on both sides of a groove still meet it exactly.
 */
export function relaxBorders(part: Partition, iterations = 6, rate = 0.5, maxMove = 0.09): Float32Array {
    const V = Float32Array.from(SHAPED);
    const f = mesh.faces;
    const tri = part.triRegion;
    const seen = new Map<string, number>();
    const link = new Map<number, Set<number>>();
    for (let t = 0; t < tri.length; t++)
        for (let k = 0; k < 3; k++) {
            const a = f[t * 3 + k],
                b = f[t * 3 + ((k + 1) % 3)];
            const o = seen.get(key(b, a));
            if (o !== undefined && tri[o] !== tri[t]) {
                (link.get(a) ?? link.set(a, new Set()).get(a)!).add(b);
                (link.get(b) ?? link.set(b, new Set()).get(b)!).add(a);
            }
            seen.set(key(a, b), t);
        }
    for (let it = 0; it < iterations; it++) {
        const prev = Float32Array.from(V);
        for (const [v, ns] of link) {
            if (ns.size !== 2) continue;
            const [a, b] = [...ns];
            for (let c = 0; c < 3; c++) V[v * 3 + c] += ((prev[a * 3 + c] + prev[b * 3 + c]) / 2 - prev[v * 3 + c]) * rate;
            // Never drag a vertex far from where it was (sparse skull edges would otherwise pull it across the head).
            const o = v * 3,
                dx = V[o] - SHAPED[o],
                dy = V[o + 1] - SHAPED[o + 1],
                dz = V[o + 2] - SHAPED[o + 2];
            const d = Math.hypot(dx, dy, dz);
            if (d > maxMove) {
                const k = maxMove / d;
                V[o] = SHAPED[o] + dx * k;
                V[o + 1] = SHAPED[o + 1] + dy * k;
                V[o + 2] = SHAPED[o + 2] + dz * k;
            }
        }
    }
    return V;
}

export function buildMechanicalFace(p: PanelParams = PANEL): MechanicalFace {
    const part = partition();
    const positions = relaxBorders(part);
    const normals = vertexNormals(positions);
    const byRegion = part.regions.map(() => [] as number[]);
    part.triRegion.forEach((r, t) => {
        if (r >= 0) byRegion[r].push(t);
    });
    const panels: Panel[] = [];
    part.regions.forEach((r, k) => {
        if (!byRegion[k].length) return;
        const g = buildPanel(byRegion[k], normals, p, positions);
        panels.push({ name: r.name, jaw: r.jaw, ...g });
    });
    // Engravings: mesh edges whose two triangles belong to different panels.
    const f = mesh.faces;
    const seen = new Map<string, number>();
    const engravings: Engraving[] = [];
    for (let t = 0; t < part.triRegion.length; t++) {
        const r = part.triRegion[t];
        if (r < 0) continue;
        for (let k = 0; k < 3; k++) {
            const a = f[t * 3 + k],
                b = f[t * 3 + ((k + 1) % 3)];
            const other = seen.get(key(b, a));
            if (other !== undefined && other !== r) engravings.push({ a, b, jaw: part.regions[r].jaw && part.regions[other].jaw });
            seen.set(key(a, b), r);
        }
    }
    return { panels, engravings, partition: part, positions, normals };
}
