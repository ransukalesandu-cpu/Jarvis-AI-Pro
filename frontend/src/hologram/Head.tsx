import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import { AdditiveBlending, BufferAttribute, BufferGeometry, type Group, type Mesh, type LineSegments } from 'three';
import mesh from './headMesh.json';
import { COLORS } from './palette';
import { useUi } from '../store';

const base = Float32Array.from(mesh.verts);
const jaw = Float32Array.from(mesh.jaw);
const [, pivotY, pivotZ] = mesh.jawPivot;

/** The standard JARVIS head: MediaPipe canonical mesh, flat-shaded, with an edge overlay, orange eyes and a voice-driven jaw. */
export function Head() {
  const group = useRef<Group>(null);
  const eyeL = useRef<Mesh>(null);
  const eyeR = useRef<Mesh>(null);
  const edgeRef = useRef<LineSegments>(null);
  const { faceGeo, edgeGeo, pos } = useMemo(() => {
    const pos = new BufferAttribute(new Float32Array(base), 3);
    pos.usage = 35048; // DynamicDrawUsage
    const faceGeo = new BufferGeometry();
    faceGeo.setAttribute('position', pos);
    faceGeo.setIndex(mesh.faces);
    const edgeGeo = new BufferGeometry();
    edgeGeo.setAttribute('position', pos);
    edgeGeo.setIndex(mesh.edges);
    return { faceGeo, edgeGeo, pos };
  }, []);
  const state = useRef({ mouth: 0, blink: 0, nextBlink: 2.5, lookX: 0, lookY: 0 });

  useFrame((s, dt) => {
    const ui = useUi.getState();
    const st = state.current;
    const speaking = ui.assistant === 'speaking';
    // Lip-sync from the OUTPUT level only, and only while speaking (never from the microphone).
    const target = speaking ? Math.min(1, ui.outputLevel * 1.6) : 0;
    st.mouth += (target - st.mouth) * Math.min(1, dt * 18);
    const a = st.mouth * mesh.jawMax * 2.4;
    const c = Math.cos(a), sn = Math.sin(a);
    const arr = pos.array as Float32Array;
    for (let i = 0; i < jaw.length; i++) {
      const o = i * 3, w = jaw[i];
      const y = base[o + 1], z = base[o + 2];
      if (w <= 0) { arr[o + 1] = y; arr[o + 2] = z; continue; }
      const dy = y - pivotY, dz = z - pivotZ;
      arr[o + 1] = y + (pivotY + dy * c - dz * sn - y) * w;
      arr[o + 2] = z + (pivotZ + dy * sn + dz * c - z) * w;
    }
    pos.needsUpdate = true;
    // blink
    const t = s.clock.elapsedTime;
    if (st.blink <= 0 && t > st.nextBlink) { st.blink = 1; st.nextBlink = t + 2.5 + Math.random() * 3.5; }
    if (st.blink > 0) st.blink = Math.max(0, st.blink - dt / 0.16);
    const lid = 1 - Math.sin((1 - st.blink) * Math.PI) * (st.blink > 0 ? 0.92 : 0);
    const reduced = ui.reducedMotion ? 0.3 : 1;
    for (const e of [eyeL.current, eyeR.current]) if (e) e.scale.set(1, Math.max(0.08, lid), 1);
    if (group.current) {
      group.current.rotation.y = Math.sin(t * 0.3) * 0.12 * reduced;
      group.current.rotation.x = Math.sin(t * 0.21) * 0.03 * reduced;
      group.current.position.y = Math.sin(t * 0.8) * 0.012 * reduced;
    }
    if (edgeRef.current) (edgeRef.current.material as { opacity: number }).opacity = 0.35 + 0.25 * Math.sin(t * 1.3) * reduced + (speaking ? 0.2 : 0);
  });

  const [exl, eyl, ezl] = mesh.eyeL, [exr, eyr, ezr] = mesh.eyeR;
  return (
    <group ref={group}>
      <mesh geometry={faceGeo}>
        <meshStandardMaterial color={COLORS.skin} emissive={COLORS.skinEmissive} emissiveIntensity={0.45} flatShading roughness={0.6} metalness={0.05} transparent opacity={0.96} />
      </mesh>
      <lineSegments ref={edgeRef} geometry={edgeGeo}>
        <lineBasicMaterial color={COLORS.edge} transparent opacity={0.45} blending={AdditiveBlending} depthWrite={false} />
      </lineSegments>
      {([[exl, eyl, ezl, eyeL], [exr, eyr, ezr, eyeR]] as const).map(([x, y, z, ref], i) => (
        <group key={i} position={[x, y, z + 0.07]}>
          <mesh ref={ref}>
            <circleGeometry args={[0.058, 24]} />
            <meshBasicMaterial color={COLORS.eye} />
          </mesh>
          <mesh position={[0, 0, -0.002]}>
            <circleGeometry args={[0.16, 24]} />
            <meshBasicMaterial color={COLORS.eye} transparent opacity={0.22} blending={AdditiveBlending} depthWrite={false} />
          </mesh>
        </group>
      ))}
    </group>
  );
}
