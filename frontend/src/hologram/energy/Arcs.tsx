import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo } from 'react';
import { BufferGeometry, Float32BufferAttribute } from 'three';
import { useUi } from '../../store';
import { COLORS, orbColor } from '../palette';
import { arcMaterial } from './flowLines';
import { arcSegments } from './paths';
import { busyState } from './Strands';
import { visualState } from '../visualState';

/**
 * Lightning arcs between the face and the orb, all in one draw; their shape and flicker are
 * computed in the vertex/fragment shaders. More arcs are live while JARVIS works or speaks; none
 * with reduced motion (they flicker by nature).
 */
export function Arcs({ count }: { count: number }) {
  const { geo, mat } = useMemo(() => {
    const a = arcSegments();
    const geo = new BufferGeometry();
    geo.setAttribute('position', new Float32BufferAttribute(a.position, 3));
    geo.setAttribute('along', new Float32BufferAttribute(a.along, 1));
    geo.setAttribute('arc', new Float32BufferAttribute(a.arc, 1));
    geo.setAttribute('side', new Float32BufferAttribute(a.side, 3));
    return { geo, mat: arcMaterial(COLORS.orb) };
  }, []);
  useEffect(() => () => { geo.dispose(); mat.dispose(); }, [geo, mat]);
  useFrame((_s, dt) => {
    const ui = useUi.getState();
    const vs = visualState(ui);   // real state only: 'offline' when the backend link is down, never 'listening' with the mic muted
    const u = mat.uniforms;
    u.time.value += dt;
    u.count.value = ui.reducedMotion ? 0 : count;
    const level = vs === 'speaking' ? ui.outputLevel : 0;
    const target = vs === 'error' ? 0.7 : busyState(vs) ? 0.45 + level * 0.4 : (vs === 'sleeping' || vs === 'offline') ? 0 : 0.12;
    u.energy.value += (target - u.energy.value) * Math.min(1, dt * 4);
    u.amp.value = 0.035 + level * 0.05;
    u.color.value.lerp(orbColor(vs), Math.min(1, dt * 4));
  });
  if (count <= 0) return null;
  return <lineSegments geometry={geo} material={mat} renderOrder={3} />;
}
