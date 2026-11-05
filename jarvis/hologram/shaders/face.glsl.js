import { UNIFORM_DECL, HELPERS, FACE_DISPLACE } from './common.glsl.js';

const HEAD = `${UNIFORM_DECL}\n${HELPERS}\n${FACE_DISPLACE}\n`;

// ── translucent skin surface ────────────────────────────────────────────────
export const surface = {
  vert: HEAD + /* glsl */ `
attribute vec3 positionB;
varying vec3 vN; varying vec3 vView; varying float vY;
void main(){
  vec3 p = faceDisplace(position, positionB);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vN = normalize(normalMatrix * normal); vView = -mv.xyz; vY = p.y;
  gl_Position = projectionMatrix * mv;
}`,
  frag: HEAD + /* glsl */ `
varying vec3 vN; varying vec3 vView; varying float vY;
void main(){
  vec3 N = normalize(vN), V = normalize(vView);
  float fr = pow(1.0 - abs(dot(N, V)), 2.0);
  float lit = max(0.0, dot(N, normalize(vec3(-0.35, 0.55, 0.75))));
  float sp = fract(vY * 0.42 - uTime * (0.04 + uScan * 0.22));
  float scan = exp(-pow((sp - 0.5) * 7.0, 2.0));
  float lines = 0.5 + 0.5 * sin(vY * 240.0 - uTime * 2.0);
  float a = 0.06 + lit * 0.34 + fr * 0.5 + scan * (0.14 + 0.2 * uScan) + lines * 0.035 + (uListen + uSpeak) * 0.10 * fr;
  a *= smoothstep(-1.6, -0.85, vY);
  vec3 col = mix(uFaceDeep, uFace, clamp(fr * 1.3 + scan * 0.7, 0.0, 1.0)) + uSpark * scan * 0.45;
  float k = (0.45 + 0.75 * uEnergy) * uGlow;
  gl_FragColor = vec4(tint(col) * k, a * k);
}`,
};

// ── wire grid, neural chords and accent curves (KIND 0 / 1 / 2) ─────────────
export const wire = {
  vert: HEAD + /* glsl */ `
attribute vec3 positionB; attribute float aSeed;
varying vec3 vN; varying vec3 vView; varying float vY; varying float vSeed; varying float vX;
void main(){
  vec3 p = faceDisplace(position, positionB);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vN = normalize(normalMatrix * normal); vView = -mv.xyz; vY = p.y; vSeed = aSeed; vX = p.x;
  gl_Position = projectionMatrix * mv;
}`,
  frag: HEAD + /* glsl */ `
varying vec3 vN; varying vec3 vView; varying float vY; varying float vSeed; varying float vX;
void main(){
  vec3 N = normalize(vN), V = normalize(vView);
  float fr = pow(1.0 - abs(dot(N, V)), 1.6);
  float facing = clamp(dot(N, V), 0.0, 1.0);
  float lit = max(0.0, dot(N, normalize(vec3(-0.35, 0.55, 0.75))));
  float sp = fract(vY * 0.42 - uTime * (0.04 + uScan * 0.22));
  float scan = exp(-pow((sp - 0.5) * 7.0, 2.0));
  #if KIND == 0
    float a = 0.16 + lit * 0.45 + fr * 0.35 + scan * 0.45;
    float k = 1.0;
  #elif KIND == 1
    float fire = smoothstep(0.82, 1.0, sin(uTime * (0.5 + uFlow * 1.6) + vSeed * 40.0));
    float a = 0.10 + fire * 0.9 + scan * 0.2;
    float k = 1.0;
  #else
    float a = 0.75 + scan * 0.25 + uSpeak * 0.2;
    float k = 1.7;
  #endif
  a *= smoothstep(-1.6, -0.9, vY) * (0.40 + 0.65 * smoothstep(-0.2, 0.6, facing + fr * 0.4));
  vec3 col = mix(uWireC, uSpark, clamp(scan * 0.6 + fr * 0.2, 0.0, 1.0));
  float b = (0.45 + 0.75 * uEnergy) * uGlow * k;
  gl_FragColor = vec4(tint(col) * b, a * b);
}`,
};

// ── glowing nodes (face = kind 0, hair = kind 1) ────────────────────────────
export const nodes = {
  vert: HEAD + /* glsl */ `
attribute vec3 positionB; attribute float aSeed; attribute float aSize; attribute float aKind; attribute float aT;
varying float vSeed; varying float vKind; varying float vY; varying float vF; varying float vT;
void main(){
  vec3 p = faceDisplace(position, positionB);
  if (aKind > 0.5) {   // hair node: sway like the strands
    float sw = (0.012 + 0.03 * uHair) * aT;
    p += vec3(sin(uTime * 0.8 + aSeed * 31.0), cos(uTime * 0.6 + aSeed * 17.0) * 0.5, sin(uTime * 0.7 + aSeed * 23.0)) * sw;
  }
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vSeed = aSeed; vKind = aKind; vY = p.y; vT = aT;
  vF = clamp(normalize(normalMatrix * normalize(p)).z, -1.0, 1.0);
  float tw = 0.75 + 0.25 * sin(uTime * (1.0 + aSeed * 2.0) + aSeed * 40.0);
  gl_PointSize = max(1.0, aSize * tw * uPointScale / max(0.1, -mv.z));
  gl_Position = projectionMatrix * mv;
}`,
  frag: HEAD + /* glsl */ `
varying float vSeed; varying float vKind; varying float vY; varying float vF; varying float vT;
void main(){
  float d = length(gl_PointCoord - 0.5);
  float a = smoothstep(0.5, 0.0, d); a *= a;
  float pulse = smoothstep(0.88, 1.0, sin(uTime * (0.6 + uFlow * 1.4) + vSeed * 50.0));
  vec3 base = vKind > 0.5 ? uHairC : uFace;
  vec3 col = mix(base, uSpark, 0.35 + 0.65 * pulse);
  a *= (0.35 + 0.65 * pulse + 0.25) * (0.5 + 0.5 * smoothstep(-0.6, 0.6, vF));
  a *= smoothstep(-1.45, -0.7, vY);
  float k = (0.5 + 0.9 * uEnergy) * uGlow;
  gl_FragColor = vec4(tint(col) * k, a * k);
}`,
};

// ── curly hair strands ──────────────────────────────────────────────────────
export const hair = {
  vert: HEAD + /* glsl */ `
attribute vec3 positionB; attribute float aSeed; attribute float aT;
varying float vSeed; varying float vT; varying float vY;
void main(){
  vec3 p = mix(position, positionB, uShape);
  float sw = (0.012 + 0.035 * uHair) * aT * aT * 2.2;
  p += vec3(sin(uTime * 0.8 + aSeed * 31.0), cos(uTime * 0.6 + aSeed * 17.0) * 0.5, sin(uTime * 0.7 + aSeed * 23.0)) * sw;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vSeed = aSeed; vT = aT; vY = p.y;
  gl_Position = projectionMatrix * mv;
}`,
  frag: HEAD + /* glsl */ `
varying float vSeed; varying float vT; varying float vY;
void main(){
  float run = fract(uTime * (0.12 + uHair * 0.5) + vSeed * 7.0);
  float spark = exp(-pow((run - vT) * 9.0, 2.0));
  float a = (0.13 + 0.55 * spark) * (1.0 - 0.4 * vT);
  vec3 col = mix(uHairC, uSpark, spark);
  float k = (0.45 + 0.8 * uEnergy) * uGlow;
  gl_FragColor = vec4(tint(col) * k, a * k);
}`,
};

// ── eyes ────────────────────────────────────────────────────────────────────
export const eyes = {
  vert: HEAD + /* glsl */ `
attribute vec3 positionB; attribute float aSide;
varying float vSide;
void main(){
  vec3 p = faceDisplace(position, positionB);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vSide = aSide;
  gl_PointSize = 0.17 * uPointScale / max(0.1, -mv.z);
  gl_Position = projectionMatrix * mv;
}`,
  frag: HEAD + /* glsl */ `
varying float vSide;
void main(){
  vec2 uv = (gl_PointCoord - 0.5) * 2.0;
  uv.y /= max(0.08, 1.0 - uBlink * 0.92);
  float d = length(vec2(uv.x * 0.8, uv.y));
  float iris = smoothstep(0.62, 0.50, d) * smoothstep(0.12, 0.30, length(uv - uLook * 0.18));
  float ring = smoothstep(0.62, 0.55, d) * smoothstep(0.34, 0.46, d);
  float glow = smoothstep(1.0, 0.0, d) * 0.35;
  float a = clamp(iris * 0.8 + ring * 0.7 + glow, 0.0, 1.0);
  vec3 col = mix(uFace, uSpark, 0.55 + 0.3 * ring);
  float k = (0.6 + 0.8 * uEnergy) * uGlow;
  gl_FragColor = vec4(tint(col) * k, a * k);
}`,
};
