import { AdditiveBlending, type Color, ShaderMaterial } from 'three';
import { compose, FRESNEL } from '../shaders/chunks';
import { GLSL } from '../shaders/glsl.generated';

/** Swirling plasma inside the orb: layered noise on the sphere, brighter at the rim, tinted by state. */
export function plasmaMaterial(color: Color): ShaderMaterial {
    return new ShaderMaterial({
        uniforms: { color: { value: color.clone() }, time: { value: 0 }, energy: { value: 0.35 } },
        vertexShader: GLSL['plasma.vert'],
        fragmentShader: compose([FRESNEL], GLSL['plasma.frag']),
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
    });
}
