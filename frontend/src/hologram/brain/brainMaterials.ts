/**
 * GPU materials for the neural brain. Everything that makes it "live" runs in the shaders:
 * nodes fire on their own clocks, synapses grow out from a node, carry signals and dissolve while
 * others form, and lobes glow with the assistant's state. `target` + `morph` let every node flow
 * into another shape (morph 0 = brain, 1 = target).
 */
import { AdditiveBlending, Color, ShaderMaterial } from 'three';
import { CIRCUIT_FLOW, compose } from '../shaders/chunks';
import { GLSL } from '../shaders/glsl.generated';

const LOBE_LOOKUP = GLSL['brain.lobe-lookup'];

/** Neurons inside the brain drift slowly on their own paths (cortex neurons stay put). */
const DRIFT = GLSL['brain.drift'];

const common = () => ({
    time: { value: 0 },
    morph: { value: 0 },
    lobeLevel: { value: [0.25, 0.25, 0.25, 0.25, 0.25, 0.3] },
    tint: { value: new Color(1, 1, 1) },
});

export function nodeMaterial(color: Color, core: Color): ShaderMaterial {
    return new ShaderMaterial({
        uniforms: {
            ...common(),
            color: { value: color.clone() },
            core: { value: core.clone() },
            firing: { value: 0.25 },
            scale: { value: 1000 },
            size: { value: 0.016 },
        },
        vertexShader: LOBE_LOOKUP + DRIFT + GLSL['brain.node.vert'],
        fragmentShader: GLSL['brain.node.frag'],
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
    });
}

export function synapseMaterial(color: Color, core: Color): ShaderMaterial {
    return new ShaderMaterial({
        uniforms: {
            ...common(),
            color: { value: color.clone() },
            core: { value: core.clone() },
            growth: { value: 0.45 },
            flow: { value: 0.4 },
            boost: { value: 0 },
        },
        vertexShader: LOBE_LOOKUP + DRIFT + GLSL['brain.synapse.vert'],
        fragmentShader: compose([CIRCUIT_FLOW], GLSL['brain.synapse.frag']),
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
    });
}

/** Soft glow behind the brain so it reads as one luminous object. */
export function haloMaterial(color: Color): ShaderMaterial {
    return new ShaderMaterial({
        uniforms: { color: { value: color.clone() }, strength: { value: 0.2 }, tint: { value: new Color(1, 1, 1) } },
        vertexShader: GLSL['brain.halo.vert'],
        fragmentShader: GLSL['brain.halo.frag'],
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
    });
}
