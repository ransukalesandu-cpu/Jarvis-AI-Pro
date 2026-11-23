/**
 * Energy line materials that animate entirely on the GPU: current running along a 0..1 `along`
 * attribute (strands), and lightning arcs whose shape jitters in the vertex shader (arcs).
 */
import { AdditiveBlending, Color, ShaderMaterial } from 'three';
import { CIRCUIT_FLOW, compose } from '../shaders/chunks';

/** Light packets running down lines; `along` 0 = start, 1 = end; `seed` offsets each line. */
export function flowLineMaterial(color: Color, core: Color): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: { color: { value: color.clone() }, core: { value: core.clone() }, time: { value: 0 }, speed: { value: 0.15 }, base: { value: 0.24 }, gain: { value: 0.6 } },
    vertexShader: /* glsl */ `
      attribute float along; attribute float seed;
      varying float vAlong; varying float vSeed;
      void main() { vAlong = along; vSeed = seed; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: compose([CIRCUIT_FLOW], /* glsl */ `
      uniform vec3 color; uniform vec3 core; uniform float time; uniform float speed; uniform float base; uniform float gain;
      varying float vAlong; varying float vSeed;
      void main() {
        float f = circuitFlow(vAlong + vSeed, time, speed, 2.0);
        vec3 c = mix(color, core, f);
        float a = clamp(base * (0.8 + 0.2 * sin(time * 0.9 + vSeed * 11.0)) + f * gain, 0.0, 1.0);
        gl_FragColor = vec4(c * a, a);
      }`),
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
    vertexShader: /* glsl */ `
      attribute float along; attribute float arc; attribute vec3 side;
      uniform float time; uniform float amp; uniform float count;
      varying float vAlong; varying float vArc;
      float h(float n) { return fract(sin(n) * 43758.5453); }
      float n1(float x) { float i = floor(x), f = fract(x); return mix(h(i), h(i + 1.0), f * f * (3.0 - 2.0 * f)) * 2.0 - 1.0; }
      void main() {
        vAlong = along; vArc = arc;
        float tick = floor(time * 14.0);
        float pin = sin(3.14159 * along);                                   // fixed at both ends
        float j = n1(along * 9.0 + arc * 17.0 + tick * 3.1) * 0.7 + n1(along * 23.0 + tick * 7.7 + arc) * 0.3;
        vec3 p = position + side * j * amp * pin;
        if (arc >= count) p = vec3(0.0, 0.0, -100.0);                      // arcs beyond the profile's count
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 color; uniform float time; uniform float energy;
      varying float vAlong; varying float vArc;
      float h(float n) { return fract(sin(n) * 43758.5453); }
      void main() {
        float on = step(1.0 - energy, h(floor(time * 6.0) + vArc * 13.0));  // flicker: more arcs live with more energy
        float a = on * (0.75 + 0.25 * h(floor(time * 20.0) + vArc));
        vec3 c = mix(color, vec3(1.0, 0.95, 0.85), 0.55);
        gl_FragColor = vec4(c * a, a);
      }`,
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
  });
}
