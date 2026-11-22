/**
 * Compiles every hologram material in a real WebGL2 context and reports the result on
 * `window.__shaderCheck`. Bundled and run in headless Chromium by scripts/check_shaders.py.
 */
import { Color, DirectionalLight, Float32BufferAttribute, LineSegments, Mesh, OrthographicCamera, PlaneGeometry, Points, Scene, WebGLRenderer } from 'three';
import { eyeMaterial } from '../src/hologram/Eye';
import { glassMaterial, twinkleMaterial } from '../src/hologram/glass';
import { CHUNKS } from '../src/hologram/shaders/chunks';
import { arcMaterial, flowLineMaterial } from '../src/hologram/energy/flowLines';
import { plasmaMaterial } from '../src/hologram/energy/plasma';
import { irisGeometry, irisMaterial, poseIris } from '../src/hologram/face/irisMaterial';
import { blackChrome, carbon, titanium, weaveNormalMap } from '../src/hologram/materials/pbr';

type Result = { name: string; ok: boolean; log: string };
const results: Result[] = [];
const canvas = document.createElement('canvas');
const renderer = new WebGLRenderer({ canvas });
let lastError = '';
renderer.debug.onShaderError = (gl, program, vs, fs) => {
  lastError = [gl.getProgramInfoLog(program), gl.getShaderInfoLog(vs), gl.getShaderInfoLog(fs)].filter(Boolean).join(' | ');
};
const cam = new OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
const c = new Color('#ff7418');
const materials: [string, import('three').Material, 'mesh' | 'points' | 'iris' | 'flow' | 'arc'][] = [
  ['glass (default)', glassMaterial(c, c), 'mesh'],
  ['glass (all effects)', glassMaterial(c, c, { shade: 1, scan: 0.5, pulse: 0.5, displace: 0.01 }), 'mesh'],
  ['eye', eyeMaterial(1.7), 'mesh'],
  ['twinkle points', twinkleMaterial(c, 0.02), 'points'],
  ['titanium (physical)', titanium(), 'mesh'],
  ['black chrome (physical)', blackChrome(), 'mesh'],
  ['carbon (physical, weave normal map)', carbon(weaveNormalMap()), 'mesh'],
  ['iris blades', irisMaterial(), 'iris'],
  ['strand flow lines', flowLineMaterial(c, c), 'flow'],
  ['lightning arcs', arcMaterial(c), 'arc'],
  ['orb plasma', plasmaMaterial(c), 'mesh'],
];
for (const [name, mat, kind] of materials) {
  lastError = '';
  const scene = new Scene();
  scene.add(new DirectionalLight(0xffffff, 1));
  const geo = kind === 'iris' ? irisGeometry() : new PlaneGeometry(1, 1);
  if (kind === 'iris') poseIris(geo, 0.5);
  const n = geo.getAttribute('position').count;
  if (kind === 'flow') { geo.setAttribute('along', new Float32BufferAttribute(new Float32Array(n), 1)); geo.setAttribute('seed', new Float32BufferAttribute(new Float32Array(n), 1)); }
  if (kind === 'arc') { geo.setAttribute('along', new Float32BufferAttribute(new Float32Array(n), 1)); geo.setAttribute('arc', new Float32BufferAttribute(new Float32Array(n), 1)); geo.setAttribute('side', new Float32BufferAttribute(new Float32Array(n * 3), 3)); }
  if (kind === 'points') geo.setAttribute('phase', geo.getAttribute('position').clone());
  scene.add(kind === 'points' ? new Points(geo, mat) : kind === 'flow' || kind === 'arc' ? new LineSegments(geo, mat) : new Mesh(geo, mat));
  try { renderer.compile(scene, cam); renderer.render(scene, cam); } catch (e) { lastError ||= String(e); }
  results.push({ name, ok: !lastError, log: lastError });
}
(window as unknown as Record<string, unknown>).__shaderCheck = {
  webgl2: renderer.capabilities.isWebGL2 !== false,
  chunks: Object.keys(CHUNKS),
  results,
};
