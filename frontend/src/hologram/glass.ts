import { AdditiveBlending, Color, ShaderMaterial } from 'three';

/**
 * Hologram glass: nearly clear where the surface faces you, glowing at the silhouette (fresnel).
 * Drawn additively, so it emits light instead of covering what is behind it.
 */
export function glassMaterial(rim: Color, body: Color, bodyAlpha = 0.1, power = 2.2, shade = 0): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: { rim: { value: rim.clone() }, body: { value: body.clone() }, bodyAlpha: { value: bodyAlpha }, power: { value: power }, boost: { value: 0 }, shade: { value: shade } },
    vertexShader: /* glsl */ `
      varying vec3 vN; varying vec3 vV;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vN = normalize(normalMatrix * normal);
        vV = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 rim; uniform vec3 body; uniform float bodyAlpha; uniform float power; uniform float boost; uniform float shade;
      varying vec3 vN; varying vec3 vV;
      void main() {
        vec3 n = normalize(vN);
        float f = pow(1.0 - abs(dot(n, normalize(vV))), power);
        // Soft key light from the upper left, so the features (nose, lips, brow) read through the glass.
        float lam = max(dot(n, normalize(vec3(-0.45, 0.55, 0.75))), 0.0);
        float lit = shade * (0.30 * lam + 0.70 * pow(lam, 4.0));
        vec3 c = mix(body, rim, f) + rim * lit;
        float a = clamp(bodyAlpha + lit * 0.55 + f * (0.85 + boost), 0.0, 1.0);
        gl_FragColor = vec4(c * a, a);
      }`,
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
  });
}

/** Points that twinkle on their own phase (attribute `phase`), sized in world units. */
export function twinkleMaterial(color: Color, size: number, base = 0.35): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: { color: { value: color.clone() }, size: { value: size }, time: { value: 0 }, base: { value: base }, gain: { value: 1 } },
    vertexShader: /* glsl */ `
      attribute float phase; uniform float size; uniform float time; varying float vA;
      uniform float base; uniform float gain;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        float tw = 0.5 + 0.5 * sin(time * (1.2 + fract(phase * 7.3) * 2.0) + phase * 6.283);
        vA = (base + (1.0 - base) * pow(tw, 3.0)) * gain;
        gl_PointSize = size * (300.0 / -mv.z) * (0.6 + 0.8 * tw);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 color; varying float vA;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float a = smoothstep(0.5, 0.0, d) * vA;
        gl_FragColor = vec4(color * a, a);
      }`,
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
  });
}

/** Deterministic random numbers, so the brain, the plexus and the dust look the same every launch. */
export function rng(seed: number) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}
