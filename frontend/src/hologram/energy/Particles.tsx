import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { AdditiveBlending, BufferGeometry, Float32BufferAttribute, ShaderMaterial } from 'three';
import { useUi } from '../../store';
import { COLORS } from '../palette';
import { LAYOUT, particleSeeds } from './paths';
import { busyState } from './Strands';
import { visualState } from '../visualState';

/**
 * Neural energy particles rising in a helix from the orb up the strands to the neck. One Points
 * draw; every particle's motion is computed in the vertex shader from its seeds (no CPU work per
 * frame beyond two uniforms). The count comes from the quality profile.
 */
export function Particles({ count }: { count: number }) {
  const height = useThree((s) => s.size.height);
  const rate = useRef(1);
  const { geo, mat } = useMemo(() => {
    const s = particleSeeds(Math.max(1, count));
    const geo = new BufferGeometry();
    geo.setAttribute('position', new Float32BufferAttribute(new Float32Array(s.phase.length * 3), 3));   // unused; motion is in the shader
    geo.setAttribute('phase', new Float32BufferAttribute(s.phase, 1));
    geo.setAttribute('radius', new Float32BufferAttribute(s.radius, 1));
    geo.setAttribute('speed', new Float32BufferAttribute(s.speed, 1));
    geo.setAttribute('spin', new Float32BufferAttribute(s.spin, 1));
    const mat = new ShaderMaterial({
      uniforms: { time: { value: 0 }, color: { value: COLORS.node.clone() }, scale: { value: 1000 }, size: { value: 0.02 }, y0: { value: LAYOUT.orb.y }, y1: { value: LAYOUT.neckY + 0.05 } },
      vertexShader: /* glsl */ `
        attribute float phase; attribute float radius; attribute float speed; attribute float spin;
        uniform float time; uniform float scale; uniform float size; uniform float y0; uniform float y1;
        varying float vA;
        void main() {
          float life = fract(time * speed + phase);
          float ang = time * spin + phase * 6.2831853;
          float rad = radius * sin(3.14159 * life) * (0.55 + 0.45 * life);
          vec3 p = vec3(cos(ang) * rad, mix(y0, y1, life), sin(ang) * rad * 0.6 + 0.1);
          vec4 mv = modelViewMatrix * vec4(p, 1.0);
          vA = sin(3.14159 * life);
          gl_PointSize = size * scale / -mv.z;
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: /* glsl */ `
        uniform vec3 color; varying float vA;
        void main() {
          float d = length(gl_PointCoord - 0.5);
          float a = smoothstep(0.5, 0.0, d) * vA;
          gl_FragColor = vec4(color * a, a);
        }`,
      transparent: true, depthWrite: false, blending: AdditiveBlending,
    });
    return { geo, mat };
  }, [count]);
  useEffect(() => () => { geo.dispose(); mat.dispose(); }, [geo, mat]);
  useEffect(() => { mat.uniforms.scale.value = height * 2; }, [mat, height]);
  useFrame((_s, dt) => {
    const ui = useUi.getState(), red = ui.reducedMotion ? 0.3 : 1;
    const vs = visualState(ui);   // real state only: 'offline' when the backend link is down, never 'listening' with the mic muted
    // Faster while JARVIS works: the clock itself runs faster, so particles never jump.
    const goal = busyState(vs) ? 2.2 : (vs === 'sleeping' || vs === 'offline') ? 0.3 : 1;
    rate.current += (goal - rate.current) * Math.min(1, dt * 2);
    mat.uniforms.time.value += dt * red * rate.current;
  });
  if (count <= 0) return null;
  return <points geometry={geo} material={mat} frustumCulled={false} renderOrder={3} />;
}
