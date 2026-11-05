// Shared GLSL: uniforms every entity reads, small helpers, and the face displacement
// (jaw hinge, profile morph, glitch band) used by the face surface, wire, nodes and accents.

export const UNIFORM_DECL = /* glsl */ `
uniform float uTime;
uniform float uEnergy;   // overall brightness from the state machine
uniform float uDim;
uniform float uWarn;     // error tint
uniform float uLock;     // privacy-lock tint
uniform float uScan;
uniform float uFlow;
uniform float uHeart;
uniform float uOrb;
uniform float uHair;
uniform float uRing;
uniform float uListen;   // microphone envelope * listening gain
uniform float uSpeak;    // output envelope * speaking gain
uniform float uMouth;    // jaw opening 0..0.9
uniform float uWidth;    // mouth width -1..1
uniform float uShape;    // 0 = JARVIS head, 1 = Bihansa head
uniform float uGlow;     // user glow intensity
uniform float uPointScale;
uniform float uBlink;
uniform vec2  uLook;
uniform float uPulseRate;
uniform vec3 uFace; uniform vec3 uFaceDeep; uniform vec3 uHairC; uniform vec3 uWireC; uniform vec3 uSpark;
uniform vec3 uHeartC; uniform vec3 uHeartHot; uniform vec3 uHeartSoft;
uniform vec3 uOrbC; uniform vec3 uOrbCore; uniform vec3 uRingC;
`;

export const HELPERS = /* glsl */ `
float hash11(float p){ p = fract(p * .1031); p *= p + 33.33; p *= p + p; return fract(p); }
float hash21(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * .1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float noise1(float x){ float i = floor(x), f = fract(x); f = f*f*(3.0-2.0*f); return mix(hash11(i), hash11(i+1.0), f); }
vec3 tint(vec3 c){
  // error -> red/amber, privacy lock -> desaturated amber; dimming for sleeping/disconnected
  vec3 w = mix(c, vec3(1.0, 0.25, 0.18) * (0.6 + 0.4 * dot(c, vec3(0.33))), uWarn);
  float l = dot(w, vec3(0.33));
  w = mix(w, vec3(l) * vec3(1.0, 0.55, 0.35) * 1.3, uLock);
  return w * (1.0 - 0.55 * uDim);
}
`;

// Jaw hinge + profile morph. pA = JARVIS head, pB = Bihansa head. Returns displaced position.
export const FACE_DISPLACE = /* glsl */ `
vec3 faceDisplace(vec3 pA, vec3 pB){
  vec3 p = mix(pA, pB, uShape);
  // Jaw: rigid hinge rotation of the lower face about a point inside the skull.
  float jawW = smoothstep(-0.12, -0.30, p.y) * (1.0 - smoothstep(-0.64, -0.86, p.y)) * smoothstep(-0.45, 0.25, p.z);
  float a = uMouth * 0.17;
  float c = cos(a), s = sin(a);
  vec2 H = vec2(-0.10, -0.25);                       // (y, z) hinge
  vec2 d = vec2(p.y - H.x, p.z - H.y);
  vec2 r = vec2(H.x + d.x * c - d.y * s, H.y + d.x * s + d.y * c);
  p.yz = mix(p.yz, r, jawW);
  // Mouth width: gentle x stretch around the lip band.
  float lipBand = exp(-pow((p.y + 0.20) * 9.0, 2.0)) * smoothstep(0.0, 0.5, p.z);
  p.x *= 1.0 + uWidth * 0.05 * lipBand;
  // Very small breathing of the whole surface with listening / speaking energy.
  float lvl = uListen + uSpeak;
  vec2 rad = normalize(p.xz + vec2(1e-4));
  p.xz += rad * lvl * 0.006 * (0.5 + 0.5 * sin(p.y * 14.0 - uTime * 6.0));
  // Restrained glitch band (stronger only in the error state).
  float band = exp(-pow((fract(uTime * 0.11) * 3.0 - 1.0 - p.y) * 7.0, 2.0));
  p.x += band * (0.004 + 0.02 * uWarn) * sin(uTime * 40.0 + p.y * 30.0);
  return p;
}
`;
