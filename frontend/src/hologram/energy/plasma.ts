import { AdditiveBlending, type Color, ShaderMaterial } from 'three';
import { compose, FRESNEL } from '../shaders/chunks';

/** Swirling plasma inside the orb: layered noise on the sphere, brighter at the rim, tinted by state. */
export function plasmaMaterial(color: Color): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: { color: { value: color.clone() }, time: { value: 0 }, energy: { value: 0.35 } },
    vertexShader: /* glsl */ `
      varying vec3 vN; varying vec3 vV; varying vec3 vP;
      void main() { vec4 mv = modelViewMatrix * vec4(position, 1.0); vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz); vP = normalize(position); gl_Position = projectionMatrix * mv; }`,
    fragmentShader: compose([FRESNEL], /* glsl */ `
      uniform vec3 color; uniform float time; uniform float energy;
      varying vec3 vN; varying vec3 vV; varying vec3 vP;
      float h(vec3 p) { return fract(sin(dot(p, vec3(12.9898, 78.233, 37.719))) * 43758.5453); }
      float n3(vec3 p) {
        vec3 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
        return mix(mix(mix(h(i), h(i + vec3(1,0,0)), f.x), mix(h(i + vec3(0,1,0)), h(i + vec3(1,1,0)), f.x), f.y),
                   mix(mix(h(i + vec3(0,0,1)), h(i + vec3(1,0,1)), f.x), mix(h(i + vec3(0,1,1)), h(i + vec3(1,1,1)), f.x), f.y), f.z);
      }
      void main() {
        vec3 p = vP * 2.2;
        float n = n3(p + vec3(0.0, time * 0.6, time * 0.3)) * 0.6 + n3(p * 2.3 - vec3(time * 0.8, 0.0, 0.0)) * 0.4;
        float veins = smoothstep(0.42, 0.5, n) * (1.0 - smoothstep(0.5, 0.58, n));   // thin bright filaments
        float f = holoFresnel(vN, vV, 1.6);
        float a = clamp((veins * 0.9 + f * 0.25) * (0.4 + energy), 0.0, 1.0);
        vec3 c = mix(color, vec3(1.0, 0.95, 0.85), veins * 0.5);
        gl_FragColor = vec4(c * a, a);
      }`),
    transparent: true, depthWrite: false, blending: AdditiveBlending,
  });
}
