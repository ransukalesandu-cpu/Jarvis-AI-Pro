import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { AdditiveBlending, BufferAttribute, BufferGeometry, type Color, Float32BufferAttribute, type Group, type InterleavedBufferAttribute, type LineSegments, type Mesh, MeshBasicMaterial } from 'three';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { Eye, eyeMaterial } from './Eye';
import { ForeheadChips } from './FaceData';
import { buildFaceCircuit, neckRuns } from './faceCircuit';
import { Ears } from './Ears';
import { newEyeLife, stepEyes } from './face/eyeLife';
import { SHAPED } from './shape';
import mesh from './headMesh.json';
import { COLORS, glitchChance } from './palette';
import { glassMaterial } from './glass';
import { useUi } from '../store';

const base = Float32Array.from(SHAPED);     // re-proportioned to the reference face (shape.ts)
const jaw = Float32Array.from(mesh.jaw);
const [, pivotY, pivotZ] = mesh.jawPivot;

/** A thick, glowing line set over index pairs of the head's vertices (re-filled when the jaw moves). */
class FatTraces {
  readonly line: LineSegments2;
  readonly halo: LineSegments2;
  private readonly idx: number[];
  private readonly geos: LineSegmentsGeometry[];
  constructor(idx: number[], color: Color, width: number, opacity: number) {
    this.idx = idx;
    this.geos = [new LineSegmentsGeometry(), new LineSegmentsGeometry()];
    for (const g of this.geos) g.setPositions(new Float32Array(idx.length * 3));
    const mat = (w: number, o: number) => new LineMaterial({ color: color.getHex(), linewidth: w, transparent: true, opacity: o, blending: AdditiveBlending, depthWrite: false });
    this.line = new LineSegments2(this.geos[0], mat(width, opacity));
    this.halo = new LineSegments2(this.geos[1], mat(width * 4, opacity * 0.22));
    this.line.renderOrder = 4;
    this.halo.renderOrder = 3;
    this.fill(base);
  }
  fill(pos: Float32Array) {
    for (const g of this.geos) {
      const attr = g.attributes.instanceStart as InterleavedBufferAttribute;
      const arr = attr.data.array as Float32Array;
      for (let i = 0; i < this.idx.length; i++) { const o = this.idx[i] * 3; arr[i * 3] = pos[o]; arr[i * 3 + 1] = pos[o + 1]; arr[i * 3 + 2] = pos[o + 2]; }
      attr.data.needsUpdate = true;
      g.computeBoundingSphere();
    }
  }
  materials(): [LineMaterial, LineMaterial] { return [this.line.material, this.halo.material]; }
  dispose() { this.geos.forEach((g) => g.dispose()); this.materials().forEach((m) => m.dispose()); }
}

/**
 * The JARVIS head as a circuit-board hologram, after the owner's reference face: a dark glass skin
 * with an orange rim, thick glowing orange traces designed on the face's landmarks (forehead channel,
 * brows, cheeks, jaw), orange contours on the lips, eyes, brows and face outline, a blue nose ridge,
 * fine background traces, running current, two blue forehead chips with live CPU and RAM, neck runs
 * with ring vias, and burning orange shader eyes. The jaw follows JARVIS's voice and so do the traces on it.
 */
export function Head() {
  const group = useRef<Group>(null);
  const eyeL = useRef<Mesh>(null);
  const eyeR = useRef<Mesh>(null);
  const edgeRef = useRef<LineSegments>(null);
  const size = useThree((s) => s.size);
  const built = useMemo(() => {
    const pos = new BufferAttribute(new Float32Array(base), 3);
    pos.usage = 35048; // DynamicDrawUsage
    const faceGeo = new BufferGeometry();
    faceGeo.setAttribute('position', pos);
    faceGeo.setIndex(mesh.faces);
    faceGeo.computeVertexNormals();
    const edgeGeo = new BufferGeometry();
    edgeGeo.setAttribute('position', pos);
    edgeGeo.setIndex(mesh.edges);
    const fc = buildFaceCircuit();
    const neck = neckRuns();
    const neckGeo = new LineSegmentsGeometry();
    neckGeo.setPositions(neck.segs);
    const neckLine = (w: number, o: number) => {
      const l = new LineSegments2(neckGeo, new LineMaterial({ color: COLORS.circuit.getHex(), linewidth: w, transparent: true, opacity: o, blending: AdditiveBlending, depthWrite: false }));
      l.renderOrder = 4;
      return l;
    };
    const fillGeo = new BufferGeometry();
    fillGeo.setAttribute('position', pos);
    fillGeo.setIndex(fc.fill);
    const viaGeo = new BufferGeometry();
    viaGeo.setAttribute('position', pos);
    viaGeo.setIndex(fc.vias);
    const allPaths = fc.paths;
    const pulseGeo = new BufferGeometry();
    pulseGeo.setAttribute('position', new Float32BufferAttribute(new Float32Array(allPaths.length * 3), 3));
    return {
      pos, faceGeo, edgeGeo, fillGeo, viaGeo, pulseGeo, allPaths, rings: neck.rings,
      main: new FatTraces(fc.main, COLORS.circuit, 2.2, 0.95),
      contour: new FatTraces(fc.contour, COLORS.contour, 1.8, 0.9),
      neckLines: [neckLine(8, 0.2), neckLine(2.2, 0.9)],
      nose: new FatTraces(fc.nose, COLORS.blue, 3.0, 0.9),
      // No displacement on the head: the depth pass and the traces share its exact surface.
      glass: glassMaterial(COLORS.rim, COLORS.skin, { bodyAlpha: 0.06, power: 2.2, shade: 0.55, scan: 0.14, pulse: 0.18 }),
      // Depth-only pass of the head: what the glass hides (the neck inside the jaw, the back of the
      // skull, back traces) is not drawn through it. Pushed back a hair so the surface lines still pass.
      occluder: new MeshBasicMaterial({ colorWrite: false, depthWrite: true, transparent: true, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }),
      eyeMats: [eyeMaterial(1.7), eyeMaterial(5.3)],
    };
  }, []);
  const { pos, faceGeo, edgeGeo, fillGeo, viaGeo, pulseGeo, allPaths, rings, main, contour, nose, neckLines, glass, occluder, eyeMats } = built;
  const fat = useMemo(() => [main, contour, nose], [main, contour, nose]);
  useEffect(() => () => {
    glass.dispose(); occluder.dispose(); eyeMats.forEach((m) => m.dispose()); fat.forEach((f) => f.dispose());
    neckLines[0].geometry.dispose(); neckLines.forEach((l) => l.material.dispose());
  }, [glass, occluder, eyeMats, fat, neckLines]);
  useEffect(() => {
    for (const m of [...fat.flatMap((f) => f.materials()), ...neckLines.map((l) => l.material)]) m.resolution.set(size.width, size.height);
  }, [fat, neckLines, size]);
  const state = useRef({ mouth: 0 });
  const eyes = useMemo(newEyeLife, []);

  useFrame((s, dt) => {
    const ui = useUi.getState();
    const st = state.current;
    const speaking = ui.assistant === 'speaking';
    const working = speaking || ui.assistant === 'thinking' || ui.assistant === 'executing' || ui.assistant === 'searching';
    // Lip-sync from the OUTPUT level only, and only while speaking (never from the microphone).
    const target = speaking ? Math.min(1, ui.outputLevel * 1.6) : 0;
    const before = st.mouth;
    st.mouth += (target - st.mouth) * Math.min(1, dt * 18);
    const arr = pos.array as Float32Array;
    if (st.mouth > 0.001 || before > 0.001) {          // a closed, silent jaw needs no vertex work
      const a = st.mouth * mesh.jawMax * 2.4;
      const c = Math.cos(a), sn = Math.sin(a);
      for (let i = 0; i < jaw.length; i++) {
        const o = i * 3, w = jaw[i];
        const y = base[o + 1], z = base[o + 2];
        if (w <= 0) { arr[o + 1] = y; arr[o + 2] = z; continue; }
        const dy = y - pivotY, dz = z - pivotZ;
        arr[o + 1] = y + (pivotY + dy * c - dz * sn - y) * w;
        arr[o + 2] = z + (pivotZ + dy * sn + dz * c - z) * w;
      }
      pos.needsUpdate = true;
      main.fill(arr); contour.fill(arr);                // the traces on the jaw open with it
    }
    const t = s.clock.elapsedTime;
    const reduced = ui.reducedMotion ? 0.3 : 1;
    stepEyes(eyes, [eyeL.current, eyeR.current], eyeMats, { state: ui.assistant, outputLevel: ui.outputLevel, reducedMotion: ui.reducedMotion, t, dt });
    if (group.current) {
      group.current.rotation.y = Math.sin(t * 0.3) * 0.12 * reduced;
      group.current.rotation.x = Math.sin(t * 0.21) * 0.03 * reduced;
      group.current.position.y = Math.sin(t * 0.8) * 0.012 * reduced;
    }
    glass.uniforms.boost.value = (speaking ? ui.outputLevel * 0.6 : 0) + 0.05 * Math.sin(t * 1.3) * reduced;
    glass.uniforms.time.value = t * reduced;
    glass.uniforms.glitch.value = ui.reducedMotion ? 0 : glitchChance(ui.assistant);   // never with reduced motion
    if (edgeRef.current) (edgeRef.current.material as { opacity: number }).opacity = 0.04 + (speaking ? 0.04 : 0);
    // Traces breathe; brighter while JARVIS works, and with the voice.
    const glow = (working ? 1 : 0.8) + 0.08 * Math.sin(t * 2.1) * reduced + (speaking ? ui.outputLevel * 0.3 : 0);
    { const [l, h] = main.materials(); l.opacity = Math.min(1, 0.85 * glow); h.opacity = 0.2 * glow; }
    neckLines[1].material.opacity = Math.min(1, 0.85 * glow); neckLines[0].material.opacity = 0.2 * glow;
    // Current running along every trace.
    const pp = pulseGeo.getAttribute('position').array as Float32Array;
    const speed = (working ? 0.8 : 0.25) * reduced;
    allPaths.forEach((path, i) => {
      const kk = ((t * speed + i * 0.173) % 1) * (path.length - 1);
      const j = Math.min(Math.floor(kk), path.length - 2), fr = kk - j, a = path[j] * 3, b2 = path[j + 1] * 3;
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
        <lineBasicMaterial color={COLORS.edge} transparent opacity={0.04} blending={AdditiveBlending} depthWrite={false} />
      </lineSegments>
      <lineSegments geometry={fillGeo} renderOrder={3}>
        <lineBasicMaterial color={COLORS.circuit} transparent opacity={0.45} blending={AdditiveBlending} depthWrite={false} />
      </lineSegments>
      {fat.map((f, i) => <group key={i}><primitive object={f.halo} /><primitive object={f.line} /></group>)}
      {neckLines.map((l, i) => <primitive key={`n${i}`} object={l} />)}
      <points geometry={viaGeo} renderOrder={5}>
        <pointsMaterial color={COLORS.via} size={0.024} sizeAttenuation transparent opacity={0.9} blending={AdditiveBlending} depthWrite={false} />
      </points>
      <points geometry={pulseGeo} renderOrder={5}>
        <pointsMaterial color={COLORS.node} size={0.04} sizeAttenuation transparent opacity={0.95} blending={AdditiveBlending} depthWrite={false} />
      </points>
      {rings.map(([x, y, z], i) => (
        <mesh key={i} position={[x, y, z + 0.01]} renderOrder={5}>
          <ringGeometry args={[0.022, 0.032, 24]} />
          <meshBasicMaterial color={COLORS.via} transparent opacity={0.9} blending={AdditiveBlending} depthWrite={false} />
        </mesh>
      ))}
      <ForeheadChips />
      <Ears />
      {([[exl, eyl, ezl, eyeL, 0], [exr, eyr, ezr, eyeR, 1]] as const).map(([x, y, z, ref, i]) => (
        <group key={i} position={[x, y, z + 0.015]}>
          <Eye ref={ref} material={eyeMats[i]} size={0.34} />
        </group>
      ))}
    </group>
  );
}
