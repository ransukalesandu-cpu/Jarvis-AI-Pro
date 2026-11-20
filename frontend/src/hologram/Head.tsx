import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { AdditiveBlending, BufferAttribute, BufferGeometry, CatmullRomCurve3, Float32BufferAttribute, type Group, type LineSegments, type Mesh, Vector3 } from 'three';
import mesh from './headMesh.json';
import { COLORS } from './palette';
import { glassMaterial, rng, twinkleMaterial } from './glass';
import { useUi } from '../store';

const base = Float32Array.from(mesh.verts);
const jaw = Float32Array.from(mesh.jaw);
const [, pivotY, pivotZ] = mesh.jawPivot;

/** Curly neural "brain" lines inside the cranium: random walks in an ellipsoid, one set per hemisphere. */
function brainCurves(count = 140): Vector3[][] {
  const r = rng(42);
  const c = new Vector3(0, 0.5, -0.2), R = new Vector3(0.5, 0.36, 0.48);
  const inside = (p: Vector3) => ((p.x - c.x) / R.x) ** 2 + ((p.y - c.y) / R.y) ** 2 + ((p.z - c.z) / R.z) ** 2 < 1;
  const out: Vector3[][] = [];
  for (let i = 0; i < count; i++) {
    const side = i % 2 ? 1 : -1;
    const p = new Vector3(c.x + side * (0.06 + r() * 0.38), c.y + (r() - 0.5) * 0.55, c.z + (r() - 0.5) * 0.8);
    if (!inside(p)) continue;
    const pts = [p.clone()];
    const d = new Vector3(r() - 0.5, r() - 0.5, r() - 0.5).normalize();
    for (let k = 0; k < 12; k++) {
      d.add(new Vector3(r() - 0.5, r() - 0.5, r() - 0.5).multiplyScalar(1.3)).normalize();
      const n = pts[pts.length - 1].clone().addScaledVector(d, 0.06);
      if (!inside(n) || Math.sign(n.x) !== side || Math.abs(n.x) < 0.03) break;
      pts.push(n);
    }
    if (pts.length >= 4) out.push(new CatmullRomCurve3(pts).getPoints(pts.length * 4));
  }
  return out;
}

/** Orange circuit traces running down from each eye, in right-angled steps. */
function eyeTraces(): Vector3[][] {
  const r = rng(7);
  const out: Vector3[][] = [];
  for (const e of [mesh.eyeL, mesh.eyeR]) {
    const side = Math.sign(e[0]);
    for (let k = 0; k < 3; k++) {
      let p = new Vector3(e[0] + side * (k - 1) * 0.035, e[1] - 0.06, e[2] + 0.02 - k * 0.02);
      const pts = [p.clone()];
      for (let s = 0; s < 4; s++) {
        p = p.clone().add(new Vector3(0, -(0.06 + r() * 0.08), -0.015));
        pts.push(p.clone());
        if (s % 2 === 0) { p = p.clone().add(new Vector3(side * (0.02 + r() * 0.04), 0, -0.01)); pts.push(p.clone()); }
      }
      out.push(pts);
    }
  }
  return out;
}

function lineGeo(curves: Vector3[][]): BufferGeometry {
  const arr: number[] = [];
  for (const c of curves) for (let i = 0; i < c.length - 1; i++) arr.push(c[i].x, c[i].y, c[i].z, c[i + 1].x, c[i + 1].y, c[i + 1].z);
  const g = new BufferGeometry();
  g.setAttribute('position', new Float32BufferAttribute(arr, 3));
  return g;
}

/**
 * The JARVIS head as a glass hologram: MediaPipe canonical mesh with a fresnel glass skin, a cyan
 * edge net, twinkling nodes, a neural brain inside the cranium, glowing orange eyes with circuit
 * traces, and a voice-driven jaw.
 */
export function Head() {
  const group = useRef<Group>(null);
  const eyeL = useRef<Mesh>(null);
  const eyeR = useRef<Mesh>(null);
  const edgeRef = useRef<LineSegments>(null);
  const brainRef = useRef<LineSegments>(null);
  const { faceGeo, edgeGeo, nodeGeo, pos, glass, nodes, brain, brainPulseGeo, brainCurveList, traces } = useMemo(() => {
    const pos = new BufferAttribute(new Float32Array(base), 3);
    pos.usage = 35048; // DynamicDrawUsage
    const faceGeo = new BufferGeometry();
    faceGeo.setAttribute('position', pos);
    faceGeo.setIndex(mesh.faces);
    faceGeo.computeVertexNormals();
    const edgeGeo = new BufferGeometry();
    edgeGeo.setAttribute('position', pos);
    edgeGeo.setIndex(mesh.edges);
    const nodeGeo = new BufferGeometry();
    nodeGeo.setAttribute('position', pos);
    const r = rng(3);
    nodeGeo.setAttribute('phase', new Float32BufferAttribute(Array.from({ length: base.length / 3 }, () => r()), 1));
    const brainCurveList = brainCurves();
    const brainPulseGeo = new BufferGeometry();
    brainPulseGeo.setAttribute('position', new Float32BufferAttribute(new Float32Array(brainCurveList.length * 3), 3));
    brainPulseGeo.setAttribute('phase', new Float32BufferAttribute(brainCurveList.map(() => r()), 1));
    return {
      faceGeo, edgeGeo, nodeGeo, pos, brainCurveList, brainPulseGeo,
      glass: glassMaterial(COLORS.rim, COLORS.skin, 0.05, 2.2, 1.15),
      nodes: twinkleMaterial(COLORS.node, 0.022, 0.25),
      brain: lineGeo(brainCurveList),
      traces: lineGeo(eyeTraces()),
    };
  }, []);
  useEffect(() => () => { glass.dispose(); nodes.dispose(); }, [glass, nodes]);
  const state = useRef({ mouth: 0, blink: 0, nextBlink: 2.5 });

  useFrame((s, dt) => {
    const ui = useUi.getState();
    const st = state.current;
    const speaking = ui.assistant === 'speaking';
    const working = speaking || ui.assistant === 'thinking' || ui.assistant === 'executing' || ui.assistant === 'searching';
    // Lip-sync from the OUTPUT level only, and only while speaking (never from the microphone).
    const target = speaking ? Math.min(1, ui.outputLevel * 1.6) : 0;
    const before = st.mouth;
    st.mouth += (target - st.mouth) * Math.min(1, dt * 18);
    if (st.mouth > 0.001 || before > 0.001) {          // a closed, silent jaw needs no vertex work
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
    }
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
    glass.uniforms.boost.value = (speaking ? ui.outputLevel * 0.6 : 0) + 0.05 * Math.sin(t * 1.3) * reduced;
    nodes.uniforms.time.value = t * reduced;
    nodes.uniforms.gain.value = working ? 1.3 : 1;
    if (edgeRef.current) (edgeRef.current.material as { opacity: number }).opacity = 0.14 + 0.06 * Math.sin(t * 1.3) * reduced + (speaking ? 0.12 : 0);
    if (brainRef.current) (brainRef.current.material as { opacity: number }).opacity = (working ? 0.8 : 0.55) + 0.12 * Math.sin(t * 2.1) * reduced;
    // light running along the brain lines
    const bp = brainPulseGeo.getAttribute('position').array as Float32Array;
    const speed = working ? 0.9 : 0.3;
    brainCurveList.forEach((c, i) => {
      const k = ((t * speed * reduced + i * 0.173) % 1) * (c.length - 1);
      const p = c[Math.floor(k)];
      bp[i * 3] = p.x; bp[i * 3 + 1] = p.y; bp[i * 3 + 2] = p.z;
    });
    brainPulseGeo.getAttribute('position').needsUpdate = true;
  });

  const [exl, eyl, ezl] = mesh.eyeL, [exr, eyr, ezr] = mesh.eyeR;
  return (
    <group ref={group}>
      <mesh geometry={faceGeo} material={glass} renderOrder={1} />
      <lineSegments ref={edgeRef} geometry={edgeGeo} renderOrder={2}>
        <lineBasicMaterial color={COLORS.edge} transparent opacity={0.25} blending={AdditiveBlending} depthWrite={false} />
      </lineSegments>
      <points geometry={nodeGeo} material={nodes} renderOrder={3} />
      <lineSegments ref={brainRef} geometry={brain} renderOrder={2}>
        <lineBasicMaterial color={COLORS.brain} transparent opacity={0.35} blending={AdditiveBlending} depthWrite={false} />
      </lineSegments>
      <points geometry={brainPulseGeo} renderOrder={3}>
        <pointsMaterial color={COLORS.node} size={0.035} sizeAttenuation transparent opacity={0.9} blending={AdditiveBlending} depthWrite={false} />
      </points>
      <lineSegments geometry={traces} renderOrder={2}>
        <lineBasicMaterial color={COLORS.eye} transparent opacity={0.55} blending={AdditiveBlending} depthWrite={false} />
      </lineSegments>
      {([[exl, eyl, ezl, eyeL], [exr, eyr, ezr, eyeR]] as const).map(([x, y, z, ref], i) => (
        <group key={i} position={[x, y, z + 0.02]}>
          <mesh ref={ref}>
            <circleGeometry args={[0.032, 24]} />
            <meshBasicMaterial color={COLORS.eyeCore} />
          </mesh>
          <mesh position={[0, 0, -0.002]}>
            <circleGeometry args={[0.058, 24]} />
            <meshBasicMaterial color={COLORS.eye} transparent opacity={0.75} blending={AdditiveBlending} depthWrite={false} />
          </mesh>
          <mesh position={[0, 0, -0.004]}>
            <circleGeometry args={[0.13, 32]} />
            <meshBasicMaterial color={COLORS.eye} transparent opacity={0.22} blending={AdditiveBlending} depthWrite={false} />
          </mesh>
        </group>
      ))}
    </group>
  );
}
