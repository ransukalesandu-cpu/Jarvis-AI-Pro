/** Neck as ring segments: ellipses fitted to the reshaped neck's own vertices, band by band. Pure. */
import { NECK_BOTTOM, SHAPED } from '../shape';
import { NECK_CUT } from './regions';

export interface NeckRing {
    y: number;
    height: number;
    cx: number;
    cz: number;
    rx: number;
    rz: number;
}

export function neckRings(count = 7, gap = 0.035): NeckRing[] {
    const V = SHAPED,
        top = NECK_CUT + 0.04,
        step = (top - NECK_BOTTOM) / count;
    const rings: NeckRing[] = [];
    for (let k = 0; k < count; k++) {
        const hi = top - k * step,
            lo = hi - step;
        let minX = Infinity,
            maxX = -Infinity,
            minZ = Infinity,
            maxZ = -Infinity;
        for (let i = 0; i < V.length; i += 3) {
            const y = V[i + 1];
            if (y > hi + step * 0.5 || y < lo - step * 0.5) continue;
            minX = Math.min(minX, V[i]);
            maxX = Math.max(maxX, V[i]);
            minZ = Math.min(minZ, V[i + 2]);
            maxZ = Math.max(maxZ, V[i + 2]);
        }
        if (!Number.isFinite(minX)) continue;
        rings.push({
            y: (hi + lo) / 2,
            height: step - gap,
            cx: (minX + maxX) / 2,
            cz: (minZ + maxZ) / 2,
            rx: ((maxX - minX) / 2) * 0.92,
            rz: ((maxZ - minZ) / 2) * 0.92,
        });
    }
    return rings;
}
