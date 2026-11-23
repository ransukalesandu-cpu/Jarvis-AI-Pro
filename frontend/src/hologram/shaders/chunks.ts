/**
 * The hologram's GLSL library: one concern per chunk, plain functions only (no uniforms, no main),
 * so any material can compose what it needs. Every chunk is compiled in a real WebGL2 context by
 * `scripts/check-shaders.mjs`, and its shape is unit-tested.
 */

/** Edge glow: 0 facing the viewer, 1 at the silhouette. */
export const FRESNEL = /* glsl */ `
float holoFresnel(vec3 n, vec3 v, float power) {
  return pow(1.0 - abs(dot(normalize(n), normalize(v))), power);
}`;

/** Soft key light from the upper left so features read through the glass (0..~1). */
export const KEY_LIGHT = /* glsl */ `
float holoKeyLight(vec3 n) {
  float lam = max(dot(normalize(n), normalize(vec3(-0.45, 0.55, 0.75))), 0.0);
  return 0.30 * lam + 0.70 * pow(lam, 4.0);
}`;

/** Energy running along a 0..1 parameter: bright packets that move with time. */
export const CIRCUIT_FLOW = /* glsl */ `
float circuitFlow(float along, float time, float speed, float density) {
  float x = fract(along * density - time * speed);
  return smoothstep(0.0, 0.08, x) * (1.0 - smoothstep(0.08, 0.35, x));
}`;

/** Horizontal projector lines drifting slowly (y in world or screen units). */
export const SCANLINES = /* glsl */ `
float holoScanlines(float y, float time, float density, float speed) {
  return 0.5 + 0.5 * sin((y * density - time * speed) * 6.2831853);
}`;

/** A slow wave of brightness travelling over the surface. */
export const SURFACE_PULSE = /* glsl */ `
float surfacePulse(vec3 p, float time, float freq) {
  return 0.5 + 0.5 * sin(p.y * freq - time * 2.0 + sin(p.x * freq * 0.5) * 0.6);
}`;

/** Controlled glitch: rare, short bands. Returns 0 (no glitch) or a band intensity 0..1. */
export const GLITCH = /* glsl */ `
float holoHash(float n) { return fract(sin(n) * 43758.5453); }
float glitchBand(float y, float time, float chance) {
  float slot = floor(time * 8.0);
  if (holoHash(slot) > chance) return 0.0;
  float centre = holoHash(slot + 17.0) * 2.0 - 1.0;
  float width = 0.02 + 0.05 * holoHash(slot + 31.0);
  return 1.0 - smoothstep(0.0, width, abs(y - centre));
}`;

/** Subtle breathing displacement along the normal (amount 0 = none). */
export const DISPLACEMENT = /* glsl */ `
vec3 holoDisplace(vec3 p, vec3 n, float time, float amount) {
  float w = sin(p.y * 9.0 + time * 1.7) * sin(p.x * 7.0 - time * 1.3);
  return p + n * w * amount;
}`;

/** Eye emission: iris fibres, limbal ring, dilating pupil, glint, turning scan ring, socket glow. */
export const EYE_EMISSION = /* glsl */ `
float eyeHash(float n) { return fract(sin(n) * 43758.5453); }
float eyeNoise(float x, float seed) { float i = floor(x), f = fract(x); return mix(eyeHash(i + seed), eyeHash(i + 1.0 + seed), f * f * (3.0 - 2.0 * f)); }
vec4 eyeEmission(vec2 uv, vec2 gaze, float dilate, float glow, float time, float seed) {
  vec2 q = (uv - 0.5) * 2.0;
  float rq = length(q);
  vec2 p = q - gaze * 0.22;
  float r = length(p);
  float a = atan(p.y, p.x);
  vec3 col = vec3(0.0);
  float alpha = 0.0;
  float halo = smoothstep(1.0, 0.2, rq) * 0.34;
  col += vec3(1.0, 0.45, 0.08) * halo; alpha += halo;
  float irisR = 0.5;
  float pupilR = 0.15 + 0.16 * dilate;
  float inIris = smoothstep(irisR + 0.02, irisR - 0.02, r) * smoothstep(pupilR - 0.02, pupilR + 0.03, r);
  float fib = 0.45 + 0.55 * eyeNoise(a * 9.0 + r * 3.0, seed) * (0.5 + 0.5 * sin(a * 46.0 + eyeNoise(a * 3.0, seed) * 6.0));
  float t = clamp((r - pupilR) / (irisR - pupilR), 0.0, 1.0);
  vec3 irisCol = mix(vec3(1.0, 0.86, 0.48), vec3(1.0, 0.42, 0.02), t);
  float limbal = smoothstep(0.06, 0.0, abs(r - irisR + 0.03)) * 0.9;
  float collar = smoothstep(0.05, 0.0, abs(r - pupilR - 0.08)) * 0.5;
  float irisA = inIris * (0.55 + 0.45 * fib) * (0.85 + 0.3 * glow);
  col += irisCol * irisA + vec3(1.0, 0.55, 0.12) * limbal + vec3(1.0, 0.92, 0.7) * collar * inIris;
  alpha += irisA + limbal * 0.8;
  float pupil = smoothstep(pupilR + 0.01, pupilR - 0.03, r);
  col += vec3(0.6, 0.18, 0.0) * pupil * 0.18;
  float g = smoothstep(0.09, 0.0, length(p - vec2(-0.2, 0.22)));
  col += vec3(1.0) * g * 0.9; alpha += g * 0.9;
  float ring = smoothstep(0.03, 0.0, abs(rq - 0.74));
  float dash = step(0.45, fract((atan(q.y, q.x) / 6.2831853) * 18.0 + time * 0.12));
  col += vec3(1.0, 0.62, 0.2) * ring * dash * (0.6 + 0.4 * glow);
  alpha += ring * dash * 0.6;
  return vec4(col, clamp(alpha, 0.0, 1.0));
}`;

export const CHUNKS = { FRESNEL, KEY_LIGHT, CIRCUIT_FLOW, SCANLINES, SURFACE_PULSE, GLITCH, DISPLACEMENT, EYE_EMISSION } as const;
export type ChunkName = keyof typeof CHUNKS;

/** Joins chunks (each once, in order) ahead of a shader body. */
export function compose(chunks: string[], body: string): string {
  return [...new Set(chunks)].join('\n') + '\n' + body;
}
