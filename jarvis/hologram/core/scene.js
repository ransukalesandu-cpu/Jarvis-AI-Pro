// World layout and camera. The face is the dominant element; the heart sits on its left;
// the orb sits below it and is larger than the heart. Units are arbitrary world units.

import * as THREE from '../vendor/three.module.min.js';

export const LAYOUT = Object.freeze({
  face:  { x: 0, y: 0.20, height: 2.34 },          // head+bust, crown at y=1.22, bust fades near y=-1.1
  heart: { x: -1.52, y: -0.58, radius: 0.30 },
  orb:   { x: 0, y: -2.02, radius: 0.46 },
  bounds: { halfWidth: 2.0, top: 1.5, bottom: -2.62 },
});

export const FOV = 28;

export function createCamera() {
  const cam = new THREE.PerspectiveCamera(FOV, 1, 0.1, 50);
  cam.position.set(0, 0, 10);
  return cam;
}

/** Fit the whole composition into the viewport (contain). */
export function fitCamera(cam, aspect) {
  const { halfWidth, top, bottom } = LAYOUT.bounds;
  const h = top - bottom, cy = (top + bottom) / 2;
  const t = Math.tan((FOV * Math.PI) / 360);
  const distH = (h / 2) / t, distW = (halfWidth / aspect) / t;
  const dist = Math.max(distH, distW) * 1.04;
  cam.aspect = aspect;
  cam.position.set(0, cy, dist);
  cam.lookAt(0, cy, 0);
  cam.updateProjectionMatrix();
  return dist;
}

/** Pixels per world unit at distance 1, for point-size scaling. */
export function pointScale(heightPx) { return heightPx / (2 * Math.tan((FOV * Math.PI) / 360)); }

export function createScene() { return new THREE.Scene(); }
