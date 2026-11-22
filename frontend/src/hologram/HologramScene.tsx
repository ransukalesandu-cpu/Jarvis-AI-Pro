import { Canvas, useThree } from '@react-three/fiber';
import { useEffect, useLayoutEffect, useState } from 'react';
import { useUi } from '../store';
import { qualityFor } from './engine/quality';
import { Head } from './Head';
import { Backdrop, LAYOUT, Orb, Strands } from './Stage';

const FOV = 28;
const BOUNDS = { halfWidth: 2.2, top: 1.7, bottom: -2.3 };   // room under the orb for the command bar

/** Contain the whole composition (face, strands, orb) in any window size. */
function FitCamera() {
  const { camera, size } = useThree();
  useLayoutEffect(() => {
    const aspect = size.width / Math.max(1, size.height);
    const h = BOUNDS.top - BOUNDS.bottom, cy = (BOUNDS.top + BOUNDS.bottom) / 2;
    const t = Math.tan((FOV * Math.PI) / 360);
    const dist = Math.max(h / 2 / t, BOUNDS.halfWidth / aspect / t) * 1.04;
    camera.position.set(0, cy, dist);
    camera.lookAt(0, cy, 0);
    camera.updateProjectionMatrix();
  }, [camera, size]);
  return null;
}

/** Caps the frame rate (Eco): render on demand and ask for a frame at the cap. */
function FrameCap({ fps }: { fps: number }) {
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => { const id = setInterval(() => invalidate(), 1000 / fps); return () => clearInterval(id); }, [fps, invalidate]);
  return null;
}

/** True while the page is hidden (window minimised or covered by another tab/app): nothing is drawn then. */
function usePageHidden(): boolean {
  const [hidden, setHidden] = useState(() => typeof document !== 'undefined' && document.hidden);
  useEffect(() => {
    const on = () => setHidden(document.hidden);
    document.addEventListener('visibilitychange', on);
    return () => document.removeEventListener('visibilitychange', on);
  }, []);
  return hidden;
}

export function HologramScene() {
  const q = qualityFor(useUi((s) => s.perfTier));
  const hidden = usePageHidden();
  return (
    <Canvas
      camera={{ fov: FOV, near: 0.1, far: 50, position: [0, 0, 10] }}
      gl={{ alpha: true, antialias: true, powerPreference: 'high-performance' }}
      dpr={q.dpr}
      frameloop={hidden ? 'never' : q.fpsCap ? 'demand' : 'always'}
      onCreated={({ gl }) => gl.setClearColor(0x000000, 0)}
    >
      <FitCamera />
      {q.fpsCap && !hidden && <FrameCap fps={q.fpsCap} />}
      <Backdrop halo={q.backdropHalo} dust={q.dust} />
      <group position={[LAYOUT.head.x, LAYOUT.head.y, 0]} scale={0.95}><Head /></group>
      <Strands />
      <Orb />
    </Canvas>
  );
}
