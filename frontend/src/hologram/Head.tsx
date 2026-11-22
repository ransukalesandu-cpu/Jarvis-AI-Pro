import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { AdditiveBlending, BufferAttribute, BufferGeometry, Float32BufferAttribute, type Group, type LineSegments, type Mesh, MeshBasicMaterial, Vector3 } from 'three';
import { Eye, eyeMaterial } from './Eye';
import mesh from './headMesh.json';
import { COLORS } from './palette';
import { glassMaterial, rng, twinkleMaterial } from './glass';
import { useUi } from '../store';

const base = Float32Array.from(mesh.verts);
const jaw = Float32Array.from(mesh.jaw);
const [, pivotY, pivotZ] = mesh.jawPivot;

/**
 * PCB-style traces over the face, skull and neck: short walks along the mesh's own edges that run
 * mostly up/down or across and turn at right angles, with a via at each end. Returned as vertex
 * index pairs, so the traces share the head's vertex buffer and move with the talking jaw.
 */
function circuits(count = 75) {
  const n = base.length / 3;
  const adj: number[][] = Array.from({ length: n }, () => []);
  const link = (a: number, b: number) => { if (!adj[a].includes(b)) { adj[a].push(b); adj[b].push(a); } };
  const f = mesh.faces;
  for (let i = 0; i < f.length; i += 3) { link(f[i], f[i + 1]); link(f[i + 1], f[i + 2]); link(f[i + 2], f[i]); }
  const r = rng(91);
  const x = (v: number) => base[v * 3], y = (v: number) => base[v * 3 + 1], z = (v: number) => base[v * 3 + 2];
  const clear = (v: number) => {
    for (const e of [mesh.eyeL, mesh.eyeR]) if (z(v) > 0 && (x(v) - e[0]) ** 2 + (y(v) - e[1]) ** 2 < 0.12 ** 2) return false;
    return true;
  };
  const segs: number[] = [], vias: number[] = [], paths: number[][] = [];
  for (let tries = 0; paths.length < count && tries < count * 12; tries++) {
    let v = Math.floor(r() * n);
    if (z(v) < -0.05 || !clear(v)) continue;                       // start on the front half
    let d: [number, number] = r() < 0.65 ? [0, r() < 0.5 ? 1 : -1] : [r() < 0.5 ? 1 : -1, 0];
    const path = [v], used = new Set([v]);
    const len = 5 + Math.floor(r() * 12);
    for (let s = 0; s < len; s++) {
      if (r() < 0.2) d = d[0] === 0 ? [r() < 0.5 ? 1 : -1, 0] : [0, r() < 0.5 ? 1 : -1];   // right-angle turn
      let best = -1, score = 0.55;
      for (const w of adj[v]) {
        if (used.has(w) || !clear(w)) continue;
        const dx = x(w) - x(v), dy = y(w) - y(v), l = Math.hypot(dx, dy) || 1;
        const sc = (dx * d[0] + dy * d[1]) / l;
        if (sc > score) { score = sc; best = w; }
      }
      if (best < 0) break;
      path.push(best); used.add(best); v = best;
    }
    if (path.length >= 4) {
      paths.push(path);
      for (let i = 0; i < path.length - 1; i++) segs.push(path[i], path[i + 1]);
      vias.push(path[0], path[path.length - 1]);
    }
  }
  return { segs, vias, paths };
}

/** Orange circuit traces running down from each eye, in right-angled steps. */
function eyeTraces(): Vector3[][] {
  const r = rng(7);
  const out: Vector3[][] = [];
  for (const e of [mesh.eyeL, mesh.eyeR]) {
    const side = Math.sign(e[0]);
    for (let k = 0; k < 3; k++) {
      let p = new Vector3(e[0] + side * (k - 1) * 0.035, e[1] - 0.1, e[2] + 0.01 - k * 0.02);
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
 * faint edge net, circuit-board traces with vias and running current, glowing orange eyes with circuit
 * traces, and a voice-driven jaw.
 */
export function Head() {
  const group = useRef<Group>(null);
  const eyeL = useRef<Mesh>(null);
  const eyeR = useRef<Mesh>(null);
  const edgeRef = useRef<LineSegments>(null);
  const circuitRef = useRef<LineSegments>(null);
  const { faceGeo, edgeGeo, nodeGeo, pos, glass, occluder, eyeMats, nodes, circuitGeo, viaGeo, pulseGeo, paths, traces } = useMemo(() => {
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
    const c = circuits();
    const circuitGeo = new BufferGeometry();
    circuitGeo.setAttribute('position', pos);
    circuitGeo.setIndex(c.segs);
    const viaGeo = new BufferGeometry();
    viaGeo.setAttribute('position', pos);
    viaGeo.setIndex(c.vias);
    const pulseGeo = new BufferGeometry();
    pulseGeo.setAttribute('position', new Float32BufferAttribute(new Float32Array(c.paths.length * 3), 3));
    return {
      faceGeo, edgeGeo, nodeGeo, pos, circuitGeo, viaGeo, pulseGeo, paths: c.paths,
      glass: glassMaterial(COLORS.rim, COLORS.skin, 0.06, 2.2, 0.85),
      // Depth-only pass of the head: whatever the glass hides (the neck inside the jaw, the back of
      // the skull, back traces) is not drawn through it. Pushed back a hair so the surface lines still pass.
      occluder: new MeshBasicMaterial({ colorWrite: false, depthWrite: true, transparent: true, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }),
      eyeMats: [eyeMaterial(1.7), eyeMaterial(5.3)],
      nodes: twinkleMaterial(COLORS.node, 0.016, 0.1),
      traces: lineGeo(eyeTraces()),
    };
  }, []);
  useEffect(() => () => { glass.dispose(); nodes.dispose(); occluder.dispose(); eyeMats.forEach((m) => m.dispose()); }, [glass, nodes, occluder, eyeMats]);
  const state = useRef({ mouth: 0, blink: 0, nextBlink: 2.5, gx: 0, gy: 0, tx: 0, ty: 0, nextLook: 1.5, dilate: 0.3 });

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
    for (const e of [eyeL.current, eyeR.current]) if (e) e.scale.set(1, Math.max(0.06, lid), 1);
    // Gaze: small saccades to a new point every 1.5-4 s (centred while listening or speaking).
    const attentive = ui.assistant === 'listening' || speaking;
    if (t > st.nextLook) {
      st.tx = attentive ? (Math.random() - 0.5) * 0.15 : (Math.random() - 0.5) * 0.9;
      st.ty = attentive ? 0 : (Math.random() - 0.5) * 0.5;
      st.nextLook = t + 1.5 + Math.random() * 2.5;
    }
    const k = Math.min(1, dt * 14 * reduced + (reduced < 1 ? dt * 2 : 0));
    st.gx += (st.tx - st.gx) * k; st.gy += (st.ty - st.gy) * k;
    // Pupil: wide while listening, narrow while speaking, breathing a little while thinking.
    const dil = ui.assistant === 'listening' ? 0.9 : speaking ? 0.15 : working ? 0.45 + 0.2 * Math.sin(t * 3) : 0.35;
    st.dilate += (dil - st.dilate) * Math.min(1, dt * 3);
    for (const m of eyeMats) {
      m.uniforms.time.value = t * reduced;
      m.uniforms.gaze.value.set(st.gx, st.gy);
      m.uniforms.dilate.value = st.dilate;
      m.uniforms.glow.value = speaking ? Math.min(1, ui.outputLevel * 1.5) : working ? 0.5 : 0.15;
    }
    if (group.current) {
      group.current.rotation.y = Math.sin(t * 0.3) * 0.12 * reduced;
      group.current.rotation.x = Math.sin(t * 0.21) * 0.03 * reduced;
      group.current.position.y = Math.sin(t * 0.8) * 0.012 * reduced;
    }
    glass.uniforms.boost.value = (speaking ? ui.outputLevel * 0.6 : 0) + 0.05 * Math.sin(t * 1.3) * reduced;
    nodes.uniforms.time.value = t * reduced;
    nodes.uniforms.gain.value = working ? 1.3 : 1;
    if (edgeRef.current) (edgeRef.current.material as { opacity: number }).opacity = 0.14 + 0.06 * Math.sin(t * 1.3) * reduced + (speaking ? 0.12 : 0);
    if (circuitRef.current) (circuitRef.current.material as { opacity: number }).opacity = (working ? 0.75 : 0.5) + 0.08 * Math.sin(t * 2.1) * reduced;
    // current running along the traces
    const pp = pulseGeo.getAttribute('position').array as Float32Array;
    const speed = (working ? 0.8 : 0.25) * reduced;
    paths.forEach((path, i) => {
      const k = ((t * speed + i * 0.173) % 1) * (path.length - 1);
      const j = Math.min(Math.floor(k), path.length - 2), fr = k - j, a = path[j] * 3, b2 = path[j + 1] * 3;
      const arr = pos.array as Float32Array;
      pp[i * 3] = arr[a] + (arr[b2] - arr[a]) * fr;
      pp[i * 3 + 1] = arr[a + 1] + (arr[b2 + 1] - arr[a + 1]) * fr;
      pp[i * 3 + 2] = arr[a + 2] + (arr[b2 + 2] - arr[a + 2]) * fr;
    });
    pulseGeo.getAttribute('position').needsUpdate = true;
  });

  const [exl, eyl, ezl] = mesh.eyeL, [exr, eyr, ezr] = mesh.eyeR;
  return (
    <group ref={group}>
      <mesh geometry={faceGeo} material={occluder} renderOrder={1} />
      <mesh geometry={faceGeo} material={glass} renderOrder={2} />
      <lineSegments ref={edgeRef} geometry={edgeGeo} renderOrder={3}>
        <lineBasicMaterial color={COLORS.edge} transparent opacity={0.25} blending={AdditiveBlending} depthWrite={false} />
      </lineSegments>
      <points geometry={nodeGeo} material={nodes} renderOrder={4} />
      <lineSegments ref={circuitRef} geometry={circuitGeo} renderOrder={3}>
        <lineBasicMaterial color={COLORS.circuit} transparent opacity={0.75} blending={AdditiveBlending} depthWrite={false} />
      </lineSegments>
      <points geometry={viaGeo} renderOrder={4}>
        <pointsMaterial color={COLORS.via} size={0.026} sizeAttenuation transparent opacity={0.75} blending={AdditiveBlending} depthWrite={false} />
      </points>
      <points geometry={pulseGeo} renderOrder={4}>
        <pointsMaterial color={COLORS.node} size={0.045} sizeAttenuation transparent opacity={0.95} blending={AdditiveBlending} depthWrite={false} />
      </points>
      <lineSegments geometry={traces} renderOrder={5}>
        <lineBasicMaterial color={COLORS.eye} transparent opacity={0.55} blending={AdditiveBlending} depthWrite={false} depthTest={false} />
      </lineSegments>
      {([[exl, eyl, ezl, eyeL, 0], [exr, eyr, ezr, eyeR, 1]] as const).map(([x, y, z, ref, i]) => (
        <group key={i} position={[x, y, z + 0.015]}>
          <Eye ref={ref} material={eyeMats[i]} size={0.27} />
        </group>
      ))}
    </group>
  );
}
