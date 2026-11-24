#include "lygia/generative/random.glsl"
float eyeNoise(float x, float seed) { float i = floor(x), f = fract(x); return mix(random(i + seed), random(i + 1.0 + seed), f * f * (3.0 - 2.0 * f)); }
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
}
