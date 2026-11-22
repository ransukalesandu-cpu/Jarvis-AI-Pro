import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { AdditiveBlending, BufferAttribute, BufferGeometry, CylinderGeometry, type Group, type Material, type ShaderMaterial } from 'three';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { useUi } from '../../store';
import { Ears } from '../Ears';
import { eyeMaterial } from '../Eye';
import { ForeheadChips } from '../FaceData';
import { glassMaterial } from '../glass';
import mesh from '../headMesh.json';
import { blackChrome, carbon, roomEnvironment, titanium, weaveNormalMap } from '../materials/pbr';
import { COLORS, glitchChance } from '../palette';
import { lidOpen, newEyeLife, stepEyes } from './eyeLife';
import { ease, eyeTarget, withLid } from './eyeStates';
import { MechanicalEye, makeIris } from './MechanicalEye';
import { poseIris } from './irisMaterial';
import { neckRings } from './neck';
import { buildMechanicalFace, type Panel } from './panels';

const [, PIVOT_Y, PIVOT_Z] = mesh.jawPivot;
const ACCENT = new Set(['browL', 'browR', 'cheekboneL', 'cheekboneR', 'noseBridge', 'chin', 'crown']);   // titanium; the rest black chrome

/** Merge closed panels into one geometry, shifted so the jaw's hinge is the origin when `hinge`. */
function merge(panels: Panel[], hinge: boolean): BufferGeometry {
  const total = panels.reduce((n, p) => n + p.positions.length, 0);
  const pos = new Float32Array(total);
  const idx: number[] = [];
  let off = 0;
  for (const p of panels) {
    pos.set(p.positions, off);
    const base = off / 3;
    for (const i of p.index) idx.push(i + base);
    off += p.positions.length;
  }
  if (hinge) for (let i = 0; i < pos.length; i += 3) { pos[i + 1] -= PIVOT_Y; pos[i + 2] -= PIVOT_Z; }
  const g = new BufferGeometry();
  g.setAttribute('position', new BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

/** Emissive engraving lines over mesh edges, lifted off the groove floor. */
function engravingLines(SHAPED: Float32Array, edges: [number, number][], normals: Float32Array, hinge: boolean): LineSegmentsGeometry {
  const out = new Float32Array(edges.length * 6);
  edges.forEach(([a, b], i) => {
    for (const [k, v] of [[0, a], [1, b]] as const) {
      const o = v * 3;
      out[i * 6 + k * 3] = SHAPED[o] + normals[o] * 0.003;
      out[i * 6 + k * 3 + 1] = SHAPED[o + 1] + normals[o + 1] * 0.003 - (hinge ? PIVOT_Y : 0);
      out[i * 6 + k * 3 + 2] = SHAPED[o + 2] + normals[o + 2] * 0.003 - (hinge ? PIVOT_Z : 0);
    }
  });
  const g = new LineSegmentsGeometry();
  g.setPositions(out);
  return g;
}

/** The skull under the plates (seen in the grooves): carbon, pulled in a hair along the normals. */
function underSkull(SHAPED: Float32Array, tris: number[], normals: Float32Array, hinge: boolean): BufferGeometry {
  const pos = new Float32Array(SHAPED.length);
  for (let i = 0; i < pos.length; i += 3) {
    pos[i] = SHAPED[i] - normals[i] * 0.004;
    pos[i + 1] = SHAPED[i + 1] - normals[i + 1] * 0.004 - (hinge ? PIVOT_Y : 0);
    pos[i + 2] = SHAPED[i + 2] - normals[i + 2] * 0.004 - (hinge ? PIVOT_Z : 0);
  }
  const g = new BufferGeometry();
  g.setAttribute('position', new BufferAttribute(pos, 3));
  g.setIndex(tris.flatMap((t) => [mesh.faces[t * 3], mesh.faces[t * 3 + 1], mesh.faces[t * 3 + 2]]));
  g.computeVertexNormals();
  // A carbon weave needs UVs: a simple cylindrical wrap is enough at this scale.
  const uv = new Float32Array((pos.length / 3) * 2);
  for (let i = 0; i < pos.length / 3; i++) { uv[i * 2] = Math.atan2(SHAPED[i * 3], SHAPED[i * 3 + 2]) * 6; uv[i * 2 + 1] = SHAPED[i * 3 + 1] * 8; }
  g.setAttribute('uv', new BufferAttribute(uv, 2));
  return g;
}

/**
 * Phase 2 mechanical head: bevelled black-chrome and titanium plates over a carbon skull, glowing
 * orange engravings in the grooves with current running through them, a separate jaw that hinges
 * at the pivot as one rigid part, segmented neck rings, an orange holo fresnel over the metal, and
 * the same eyes, forehead chips and ears as the circuit head. No phoneme lip-sync: the jaw follows
 * JARVIS's output level only while speaking.
 */
export function MechanicalHead() {
  const group = useRef<Group>(null);
  const jawRef = useRef<Group>(null);
  const irises = useMemo(() => [makeIris(), makeIris()], []);
  useEffect(() => () => irises.forEach((i) => { i.geometry.dispose(); i.material.dispose(); }), [irises]);
  const irisState = useRef([{ aperture: 0.55, glow: 0.3, phase: 0 }, { aperture: 0.55, glow: 0.3, phase: 0 }]);
  const { gl, scene, size } = useThree();

  const built = useMemo(() => {
    const face = buildMechanicalFace();
    const { positions: P, normals } = face;
    const pick = (jaw: boolean, accent: boolean) => face.panels.filter((p) => p.jaw === jaw && ACCENT.has(p.name) === accent);
    const geos = {
      chrome: merge(pick(false, false), false), metal: merge(pick(false, true), false),
      jawChrome: merge(pick(true, false), true), jawMetal: merge(pick(true, true), true),
    };
    const { regions, triRegion } = face.partition;
    const staticTris: number[] = [], jawTris: number[] = [];
    triRegion.forEach((r, t) => { if (r >= 0) (regions[r].jaw ? jawTris : staticTris).push(t); });
    const skull = underSkull(P, staticTris, normals, false), jawSkull = underSkull(P, jawTris, normals, true);
    const edges = (jaw: boolean) => face.engravings.filter((e) => e.jaw === jaw).map((e) => [e.a, e.b] as [number, number]);
    const lineGeos = [engravingLines(P, edges(false), normals, false), engravingLines(P, edges(true), normals, true)];
    const lineMat = (w: number, o: number, dashed: boolean) => new LineMaterial({
      color: (dashed ? COLORS.node : COLORS.circuit).getHex(), linewidth: w, transparent: true, opacity: o,
      blending: AdditiveBlending, depthWrite: false, dashed, dashSize: 0.05, gapSize: 0.32,
    });
    const mats = { steady: lineMat(1.8, 0.9, false), halo: lineMat(6, 0.18, false), flow: lineMat(2.4, 1, true) };
    const lines = lineGeos.map((g) => [mats.halo, mats.steady, mats.flow].map((m) => {
      const l = new LineSegments2(g, m);
      if (m.dashed) l.computeLineDistances();
      l.renderOrder = 4;
      return l;
    }));
    const weave = weaveNormalMap();
    const materials = {
      chrome: blackChrome({ color: '#14161a' }), metal: titanium({ color: '#4c5058', roughness: 0.32 }), carbon: carbon(weave),
      holo: glassMaterial(COLORS.rim, COLORS.skin, { bodyAlpha: 0.03, power: 2.0, scan: 0.25, pulse: 0.25 }),
      ring: titanium({ color: '#3a3e46', roughness: 0.3 }),
    };
    const rings = neckRings();
    const ringGeo = new CylinderGeometry(1, 1, 1, 48, 1, true);
    const eyeMats = [eyeMaterial(1.7), eyeMaterial(5.3)];
    return { geos, skull, jawSkull, lineGeos, mats, lines, weave, materials, rings, ringGeo, eyeMats };
  }, []);
  const { geos, skull, jawSkull, lineGeos, mats, lines, weave, materials, rings, ringGeo, eyeMats } = built;

  useEffect(() => {
    const env = roomEnvironment(gl);
    const before = scene.environment;
    const intensity = scene.environmentIntensity;
    scene.environment = env;
    scene.environmentIntensity = 0.55;          // a dark studio: the orange light and the engravings lead
    return () => { scene.environment = before; scene.environmentIntensity = intensity; env.dispose(); };
  }, [gl, scene]);
  useEffect(() => () => {
    [...Object.values(geos), skull, jawSkull, ...lineGeos, ringGeo].forEach((g) => g.dispose());
    ([...Object.values(mats), ...Object.values(materials), ...eyeMats] as Material[]).forEach((m) => m.dispose());
    weave.dispose();
  }, [geos, skull, jawSkull, lineGeos, ringGeo, mats, materials, eyeMats, weave]);
  useEffect(() => { for (const m of Object.values(mats)) m.resolution.set(size.width, size.height); }, [mats, size]);

  const life = useRef({ mouth: 0, eyes: newEyeLife() });
  useFrame((s, dt) => {
    const ui = useUi.getState();
    const st = life.current;
    const t = s.clock.elapsedTime;
    const speaking = ui.assistant === 'speaking';
    const working = speaking || ui.assistant === 'thinking' || ui.assistant === 'executing' || ui.assistant === 'searching';
    const reduced = ui.reducedMotion ? 0.3 : 1;
    // The jaw: one rigid part on its hinge, from the OUTPUT level only, only while speaking.
    const target = speaking ? Math.min(1, ui.outputLevel * 1.6) : 0;
    st.mouth += (target - st.mouth) * Math.min(1, dt * 18);
    if (jawRef.current) jawRef.current.rotation.x = st.mouth * mesh.jawMax * 2.4;
    // Shared gaze and blink timing; the mechanical iris then takes over aperture, glow, scan and tint,
    // per eye (they act independently while thinking and searching).
    stepEyes(st.eyes, [], eyeMats as ShaderMaterial[], { state: ui.assistant, outputLevel: ui.outputLevel, reducedMotion: ui.reducedMotion, t, dt });
    const lid = lidOpen(st.eyes);
    (['L', 'R'] as const).forEach((side, i) => {
      const goal = eyeTarget(ui.assistant, side, t * reduced, ui.outputLevel);
      const is = irisState.current[i];
      is.aperture = ease(is.aperture, goal.aperture, 8, dt);
      is.glow = ease(is.glow, goal.glow, 6, dt);
      is.phase += dt * goal.scan * 8 * reduced;          // the scan ring's dash speed is time * 0.12 in the shader
      poseIris(irises[i].geometry, withLid(is.aperture, lid));
      irises[i].material.uniforms.glow.value = is.glow;
      irises[i].material.uniforms.tint.value = goal.tint;
      const m = eyeMats[i] as ShaderMaterial;
      m.uniforms.time.value = is.phase;
      m.uniforms.dilate.value = 0.6 + 0.4 * is.aperture;   // keep the core bright behind the blades
      m.uniforms.glow.value = is.glow;
      m.uniforms.tint.value.setRGB(...goal.tint);
    });
    if (group.current) {
      group.current.rotation.y = Math.sin(t * 0.3) * 0.12 * reduced;
      group.current.rotation.x = Math.sin(t * 0.21) * 0.03 * reduced;
      group.current.position.y = Math.sin(t * 0.8) * 0.012 * reduced;
    }
    const h = materials.holo;
    h.uniforms.time.value = t * reduced;
    h.uniforms.boost.value = speaking ? ui.outputLevel * 0.5 : 0;
    h.uniforms.glitch.value = ui.reducedMotion ? 0 : glitchChance(ui.assistant);
    // Current in the engravings: faster while working, with the voice.
    mats.flow.dashOffset -= dt * (working ? 0.5 : 0.15) * reduced;
    const glow = (working ? 1 : 0.8) + 0.08 * Math.sin(t * 2.1) * reduced + (speaking ? ui.outputLevel * 0.3 : 0);
    mats.steady.opacity = Math.min(1, 0.85 * glow);
    mats.halo.opacity = 0.18 * glow;
  });

  const [exl, eyl, ezl] = mesh.eyeL, [exr, eyr, ezr] = mesh.eyeR;
  const plates = (chrome: BufferGeometry, metal: BufferGeometry, under: BufferGeometry) => (
    <>
      <mesh geometry={under} material={materials.carbon} renderOrder={1} />
      <mesh geometry={chrome} material={materials.chrome} renderOrder={1} />
      <mesh geometry={metal} material={materials.metal} renderOrder={1} />
      <mesh geometry={chrome} material={materials.holo} renderOrder={2} />
      <mesh geometry={metal} material={materials.holo} renderOrder={2} />
    </>
  );
  return (
    <group ref={group}>
      <directionalLight position={[-2.5, 3, 4]} intensity={1.6} color="#fff1e0" />
      <directionalLight position={[2.5, 1, -3]} intensity={2.4} color="#ff8a2a" />
      {plates(geos.chrome, geos.metal, skull)}
      {lines[0].map((l, i) => <primitive key={`s${i}`} object={l} />)}
      <group ref={jawRef} position={[0, PIVOT_Y, PIVOT_Z]}>
        {plates(geos.jawChrome, geos.jawMetal, jawSkull)}
        {lines[1].map((l, i) => <primitive key={`j${i}`} object={l} />)}
      </group>
      {rings.map((r, i) => (
        <group key={i} position={[r.cx, r.y, r.cz]}>
          <mesh geometry={ringGeo} material={materials.ring} scale={[r.rx, r.height, r.rz]} />
          <mesh position={[0, -r.height / 2 - 0.012, 0]} rotation={[Math.PI / 2, 0, 0]} scale={[r.rx * 0.98, r.rz * 0.98, 1]} renderOrder={4}>
            <ringGeometry args={[0.97, 1, 64]} />
            <meshBasicMaterial color={COLORS.circuit} transparent opacity={0.85} blending={AdditiveBlending} depthWrite={false} side={2} />
          </mesh>
        </group>
      ))}
      <ForeheadChips />
      <Ears />
      {([[exl, eyl, ezl, 0, 0], [exr, eyr, ezr, 1, 1]] as const).map(([x, y, z, ref, i]) => (
        <group key={i} position={[x, y, z + 0.035]}>
          <MechanicalEye emission={eyeMats[i]} iris={irises[ref]} />
        </group>
      ))}
    </group>
  );
}
