import { Canvas, useThree } from '@react-three/fiber';
import { useLayoutEffect } from 'react';
import { Head } from './Head';
import { Backdrop, LAYOUT, Orb, Strands } from './Stage';

const FOV = 28;
const BOUNDS = { halfWidth: 2.2, top: 1.7, bottom: -2.3 };   // room under the orb for the command bar

/** Contain the whole composition (face, heart, orb) in any window size. */
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

export function HologramScene() {
  return (
    <Canvas
      camera={{ fov: FOV, near: 0.1, far: 50, position: [0, 0, 10] }}
      gl={{ alpha: true, antialias: true, powerPreference: 'high-performance' }}
      dpr={[1, 2]}
      onCreated={({ gl }) => gl.setClearColor(0x000000, 0)}
    >
      <FitCamera />
      <ambientLight intensity={1.1} color="#6a9bff" />
      <directionalLight position={[-1.5, 2.2, 3]} intensity={3.2} color="#dff0ff" />
      <directionalLight position={[2, -0.5, 1.5]} intensity={0.6} color="#2f9bff" />
      <Backdrop />
      <group position={[LAYOUT.head.x, LAYOUT.head.y, 0]} scale={0.95}><Head /></group>
      <Strands />
      <Orb />
    </Canvas>
  );
}
