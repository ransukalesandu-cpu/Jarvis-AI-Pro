import * as THREE from '../vendor/three.module.min.js';

/** Wrap a WebGL2 context in a three renderer: transparent, no tone mapping, no shadows. */
export function createRenderer(canvas, gl) {
  const r = new THREE.WebGLRenderer({ canvas, context: gl, alpha: true, premultipliedAlpha: true, antialias: false, powerPreference: 'high-performance' });
  r.setClearColor(0x000000, 0);
  r.autoClear = true;
  r.outputColorSpace = THREE.LinearSRGBColorSpace;
  r.toneMapping = THREE.NoToneMapping;
  r.info.autoReset = true;
  return r;
}
