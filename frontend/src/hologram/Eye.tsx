import { forwardRef, useMemo } from 'react';
import { AdditiveBlending, Color, type Mesh, ShaderMaterial, Vector2 } from 'three';
import { compose, EYE_EMISSION } from './shaders/chunks';

/**
 * A hologram eye drawn by a shader on one small quad: an amber iris with fine radial fibres and a
 * bright limbal edge, a pupil that dilates (listening) and narrows (speaking), a glint, and a thin
 * scan ring that turns around it. `gaze` shifts the iris inside the eye; blinking is done by the
 * caller scaling the mesh vertically. `tint` recolours it (white = as designed).
 */
export function eyeMaterial(seed: number): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: {
      time: { value: 0 }, gaze: { value: new Vector2() }, dilate: { value: 0.3 },
      glow: { value: 0 }, seed: { value: seed }, open: { value: 1 }, tint: { value: new Color(1, 1, 1) },
    },
    vertexShader: /* glsl */ `
      varying vec2 vUv;
      void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: compose([EYE_EMISSION], /* glsl */ `
      uniform float time; uniform vec2 gaze; uniform float dilate; uniform float glow; uniform float seed; uniform float open; uniform vec3 tint;
      varying vec2 vUv;
      void main() {
        vec4 e = eyeEmission(vUv, gaze, dilate, glow, time, seed);
        gl_FragColor = vec4(e.rgb * tint * open, e.a * open);
      }`),
    transparent: true,
    depthWrite: false,
    depthTest: false,            // the eyes sit in the sockets; the socket rim must not cut them
    blending: AdditiveBlending,
  });
}

export const Eye = forwardRef<Mesh, { material: ShaderMaterial; size: number }>(function Eye({ material, size }, ref) {
  const geo = useMemo(() => [size, size] as [number, number], [size]);
  return (
    <mesh ref={ref} material={material} renderOrder={6}>
      <planeGeometry args={geo} />
    </mesh>
  );
});
