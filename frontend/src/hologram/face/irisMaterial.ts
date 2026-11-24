/**
 * The iris blades of one eye as a single mesh (one draw): positions are rewritten each frame from
 * the blade poses, in eye space. The shader shades the blades as dark gunmetal with an orange edge
 * along each blade's inner edge, and discards anything outside the socket ring.
 */
import { BufferAttribute, BufferGeometry, NormalBlending, ShaderMaterial } from 'three';
import { BLADES, BLADE_LEN, BLADE_W, bladePose } from './iris';
import { GLSL } from '../shaders/glsl.generated';

const STEPS = 16;
const PER_BLADE = (STEPS + 1) * 2;

/** Builds the strip topology once: per blade, inner-edge points then outer-edge points. */
export function irisGeometry(): BufferGeometry {
    const g = new BufferGeometry();
    const n = BLADES * PER_BLADE;
    const edge = new Float32Array(n),
        blade = new Float32Array(n);
    const idx: number[] = [];
    for (let b = 0; b < BLADES; b++) {
        const o = b * PER_BLADE;
        for (let i = 0; i <= STEPS; i++) {
            edge[o + i] = 0;
            edge[o + STEPS + 1 + i] = 1;
            blade[o + i] = blade[o + STEPS + 1 + i] = b;
        }
        for (let i = 0; i < STEPS; i++) {
            const a = o + i,
                c = o + i + 1,
                d = o + STEPS + 1 + i + 1,
                e = o + STEPS + 1 + i;
            idx.push(a, e, c, c, e, d);
        }
    }
    g.setAttribute('position', new BufferAttribute(new Float32Array(n * 3), 3));
    g.setAttribute('edge', new BufferAttribute(edge, 1));
    g.setAttribute('blade', new BufferAttribute(blade, 1));
    g.setIndex(idx);
    return g;
}

/** Writes the blade positions for an aperture 0..1 (eye space, radius 1 = socket ring). */
export function poseIris(g: BufferGeometry, aperture: number): void {
    const pos = g.getAttribute('position') as BufferAttribute;
    const arr = pos.array as Float32Array;
    for (let b = 0; b < BLADES; b++) {
        const p = bladePose(b, aperture),
            c = Math.cos(p.angle),
            s = Math.sin(p.angle);
        for (let i = 0; i <= STEPS; i++) {
            const sx = (BLADE_LEN * i) / STEPS;
            const w = -BLADE_W * Math.min(1, 2 * Math.sin((Math.PI * sx) / BLADE_LEN));
            for (const [k, y] of [
                [i, 0],
                [STEPS + 1 + i, w],
            ] as const) {
                const o = (b * PER_BLADE + k) * 3;
                arr[o] = p.x + sx * c - y * s;
                arr[o + 1] = p.y + sx * s + y * c;
                arr[o + 2] = 0.001 * b;
            }
        }
    }
    pos.needsUpdate = true;
}

export function irisMaterial(): ShaderMaterial {
    return new ShaderMaterial({
        uniforms: { glow: { value: 0.3 }, tint: { value: [1, 1, 1] } },
        vertexShader: GLSL['iris.vert'],
        fragmentShader: GLSL['iris.frag'],
        transparent: true, // drawn in the transparent pass, after the emission (renderOrder decides)
        depthTest: false,
        depthWrite: false,
        blending: NormalBlending,
    });
}
