/**
 * Energy line materials that animate entirely on the GPU: current running along a 0..1 `along`
 * attribute (strands), and lightning arcs whose shape jitters in the vertex shader (arcs).
 */
import { AdditiveBlending, Color, ShaderMaterial } from 'three';
import { CIRCUIT_FLOW, compose } from '../shaders/chunks';
import { GLSL } from '../shaders/glsl.generated';

/** Light packets running down lines; `along` 0 = start, 1 = end; `seed` offsets each line. */
export function flowLineMaterial(color: Color, core: Color): ShaderMaterial {
    return new ShaderMaterial({
        uniforms: {
            color: { value: color.clone() },
            core: { value: core.clone() },
            time: { value: 0 },
            speed: { value: 0.15 },
            base: { value: 0.24 },
            gain: { value: 0.6 },
        },
        vertexShader: GLSL['flow.line.vert'],
        fragmentShader: compose([CIRCUIT_FLOW], GLSL['flow.line.frag']),
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
    });
}

/**
 * Lightning arcs: each vertex knows its arc, its place along the arc and a side direction; the
 * vertex shader shakes it sideways with noise that changes several times a second, pinned at both
 * ends. Each arc flickers on and off on its own.
 */
export function arcMaterial(color: Color): ShaderMaterial {
    return new ShaderMaterial({
        uniforms: { color: { value: color.clone() }, time: { value: 0 }, amp: { value: 0.05 }, energy: { value: 0.3 }, count: { value: 4 } },
        vertexShader: GLSL['flow.arc.vert'],
        fragmentShader: GLSL['flow.arc.frag'],
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
    });
}
