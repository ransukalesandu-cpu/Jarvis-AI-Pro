import { useFrame, useThree } from '@react-three/fiber';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { useEffect, useMemo, useRef } from 'react';
import { AdditiveBlending, BufferGeometry, CatmullRomCurve3, Color, Float32BufferAttribute, type Group, type LineSegments, type Mesh, type Points, Vector3 } from 'three';
import { COLORS, orbColor } from './palette';
import { glassMaterial, rng, twinkleMaterial } from './glass';
import { useUi } from '../store';

export const LAYOUT = { head: { x: 0, y: 0.55 }, neckY: -0.66, orb: { x: 0, y: -1.42, r: 0.3 } };
const STRANDS = 28;

const add = (color: Color, opacity: number) => ({ color, transparent: true, opacity, blending: AdditiveBlending, depthWrite: false } as const);
const busyState = (s: string) => s === 'speaking' || s === 'thinking' || s === 'executing' || s === 'searching';

/** Energy strands falling from the neck into the orb; light runs down them while JARVIS speaks or works. */
export function Strands() {
  const pulses = useRef<Points>(null);
  const linesRef = useRef<Group>(null);
  const curves = useMemo(() => {
    const r = rng(19);
    const top = LAYOUT.neckY, bottom = LAYOUT.orb.y + LAYOUT.orb.r * 0.75;
    return Array.from({ length: STRANDS }, (_, i) => {
      const k = (i - (STRANDS - 1) / 2) / ((STRANDS - 1) / 2);
      const z = (r() - 0.5) * 0.25;
      return new CatmullRomCurve3([
        new Vector3(k * 0.34, top, z),
        new Vector3(k * 0.30 + (r() - 0.5) * 0.06, top - 0.14, z * 0.8),
        new Vector3(k * 0.20 + (r() - 0.5) * 0.08, (top + bottom) / 2, z * 0.5),
        new Vector3(k * 0.10, bottom + 0.06, z * 0.2),
        new Vector3(k * 0.05, bottom, 0.05),
      ]);
    });
  }, []);
  const geos = useMemo(() => curves.map((c) => new BufferGeometry().setFromPoints(c.getPoints(40))), [curves]);
  const pulseGeo = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(new Float32Array(STRANDS * 2 * 3), 3));
    return g;
  }, []);
  useEffect(() => () => { geos.forEach((g) => g.dispose()); pulseGeo.dispose(); }, [geos, pulseGeo]);
  const tmp = useMemo(() => new Vector3(), []);
  useFrame((s) => {
    const ui = useUi.getState(), t = s.clock.elapsedTime, red = ui.reducedMotion ? 0.3 : 1;
    const busy = busyState(ui.assistant);
    const arr = pulseGeo.getAttribute('position').array as Float32Array;
    const speed = (busy ? 0.5 : 0.15) * red;
    for (let i = 0; i < STRANDS; i++) for (let j = 0; j < 2; j++) {
      curves[i].getPoint((t * speed + i * 0.137 + j * 0.5) % 1, tmp);
      arr.set([tmp.x, tmp.y, tmp.z], (i * 2 + j) * 3);
    }
    pulseGeo.getAttribute('position').needsUpdate = true;
    const mat = pulses.current?.material as { opacity: number } | undefined;
    if (mat) mat.opacity += ((busy ? 0.95 : 0.45) - mat.opacity) * 0.1;
    linesRef.current?.children.forEach((l, i) => {
      ((l as Mesh).material as unknown as { opacity: number }).opacity = (busy ? 0.42 : 0.24) + 0.08 * Math.sin(t * 0.9 + i * 1.7) * red;
    });
  });
  return (
    <group>
      <group ref={linesRef}>
        {geos.map((g, i) => (
          <line key={i}>
            <primitive object={g} attach="geometry" />
            <lineBasicMaterial {...add(COLORS.wire, 0.3)} />
          </line>
        ))}
      </group>
      <points ref={pulses} geometry={pulseGeo}>
        <pointsMaterial color={COLORS.orbCore} size={0.05} sizeAttenuation transparent opacity={0.45} blending={AdditiveBlending} depthWrite={false} />
      </points>
    </group>
  );
}

/** A glass energy orb: fresnel shell, latitude net, bright core, tilted orbit rings and two platform rings below. */
export function Orb() {
  const shell = useRef<Mesh>(null);
  const net = useRef<Mesh>(null);
  const core = useRef<Mesh>(null);
  const halo = useRef<Mesh>(null);
  const rings = useRef<Group>(null);
  const plates = useRef<Group>(null);
  const glass = useMemo(() => glassMaterial(COLORS.orb, COLORS.orbBody, 0.08, 1.8), []);
  useEffect(() => () => glass.dispose(), [glass]);
  const col = useMemo(() => new Color(COLORS.orb), []);
  useFrame((s, dt) => {
    const ui = useUi.getState(), t = s.clock.elapsedTime, red = ui.reducedMotion ? 0.3 : 1;
    col.lerp(orbColor(ui.assistant), Math.min(1, dt * 4));
    const level = ui.assistant === 'speaking' ? ui.outputLevel : ui.assistant === 'listening' ? ui.inputLevel : 0;
    const busy = busyState(ui.assistant);
    glass.uniforms.rim.value.copy(col);
    glass.uniforms.boost.value = level * 0.5;
    const breathe = 1 + 0.04 * Math.sin(t * 1.4) * red + level * 0.25;
    core.current?.scale.setScalar(breathe);
    halo.current?.scale.setScalar(1 + level * 0.5 + 0.05 * Math.sin(t * 1.1) * red);
    if (net.current) net.current.rotation.y += dt * 0.25 * red;
    const spin = (busy ? 1.8 : 0.35) * red;
    rings.current?.children.forEach((m, i) => {
      m.rotation.z += dt * spin * (i % 2 ? -1 : 1) * (0.6 + i * 0.25);
      ((m as Mesh).material as unknown as { color: Color }).color.copy(col);
    });
    plates.current?.children.forEach((m, i) => { m.rotation.z += dt * 0.2 * red * (i % 2 ? -1 : 1); });
    for (const m of [halo.current, net.current]) if (m) ((m.material as unknown) as { color: Color }).color.copy(col);
  });
  const { x, y, r } = LAYOUT.orb;
  return (
    <group position={[x, y, 0.1]}>
      <mesh ref={halo}><circleGeometry args={[r * 2.2, 48]} /><meshBasicMaterial {...add(COLORS.orb, 0.025)} /></mesh>
      <mesh ref={shell} material={glass}><sphereGeometry args={[r, 48, 32]} /></mesh>
      <mesh ref={net}><sphereGeometry args={[r * 0.99, 18, 12]} /><meshBasicMaterial {...add(COLORS.orb, 0.12)} wireframe /></mesh>
      <mesh ref={core}><sphereGeometry args={[r * 0.22, 24, 16]} /><meshBasicMaterial {...add(COLORS.orbCore, 0.95)} /></mesh>
      <mesh><circleGeometry args={[r * 0.6, 32]} /><meshBasicMaterial {...add(COLORS.orbCore, 0.25)} /></mesh>
      <group ref={rings}>
        {[[1.25, 1.2, 0.012], [1.5, 1.38, 0.008], [1.8, 1.5, 0.006]].map(([s, tilt, w], i) => (
          <mesh key={i} rotation={[tilt, 0, i * 0.7]}><torusGeometry args={[r * s, w, 8, 128]} /><meshBasicMaterial {...add(COLORS.orb, 0.75 - i * 0.18)} /></mesh>
        ))}
      </group>
      <group ref={plates} position={[0, -r * 0.95, 0]}>
        {[[1.6, 0.010, 0.6], [2.3, 0.007, 0.35], [3.0, 0.005, 0.2]].map(([s, w, o], i) => (
          <mesh key={i} rotation={[Math.PI / 2 - 0.12, 0, 0]}><torusGeometry args={[r * s, w, 6, 128]} /><meshBasicMaterial {...add(COLORS.ring, o)} /></mesh>
        ))}
      </group>
    </group>
  );
}

/** A slowly turning constellation around the head: nodes joined to their near neighbours. */
export function Plexus() {
  const group = useRef<Group>(null);
  const lines = useRef<LineSegments>(null);
  const { pointGeo, lineGeo, mat } = useMemo(() => {
    const r = rng(77);
    const pts: Vector3[] = [];
    while (pts.length < 150) {
      const th = r() * Math.PI * 2, ph = Math.acos(2 * r() - 1), rad = 1.05 + r() * 0.45;
      const p = new Vector3(Math.sin(ph) * Math.cos(th) * rad * 1.15, Math.cos(ph) * rad * 0.95 + 0.1, Math.sin(ph) * Math.sin(th) * rad * 0.6 - 0.2);
      if (Math.abs(p.x) < 0.75 && p.y < 0.9 && p.z > -0.1) continue;     // keep the face clear
      pts.push(p);
    }
    const seg: number[] = [];
    for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++)
      if (pts[i].distanceTo(pts[j]) < 0.3) seg.push(pts[i].x, pts[i].y, pts[i].z, pts[j].x, pts[j].y, pts[j].z);
    const pointGeo = new BufferGeometry().setFromPoints(pts);
    pointGeo.setAttribute('phase', new Float32BufferAttribute(pts.map(() => r()), 1));
    const lineGeo = new BufferGeometry();
    lineGeo.setAttribute('position', new Float32BufferAttribute(seg, 3));
    return { pointGeo, lineGeo, mat: twinkleMaterial(COLORS.node, 0.035, 0.3) };
  }, []);
  useEffect(() => () => { pointGeo.dispose(); lineGeo.dispose(); mat.dispose(); }, [pointGeo, lineGeo, mat]);
  useFrame((s, dt) => {
    const ui = useUi.getState(), red = ui.reducedMotion ? 0.3 : 1;
    if (group.current) group.current.rotation.y += dt * 0.05 * red;
    mat.uniforms.time.value = s.clock.elapsedTime * red;
    if (lines.current) (lines.current.material as { opacity: number }).opacity = busyState(ui.assistant) ? 0.24 : 0.14;
  });
  return (
    <group ref={group} position={[0, LAYOUT.head.y, -0.3]}>
      <lineSegments ref={lines} geometry={lineGeo}><lineBasicMaterial {...add(COLORS.edge, 0.14)} /></lineSegments>
      <points geometry={pointGeo} material={mat} />
    </group>
  );
}

/** Behind the head, as in the reference: blue circuit traces running out from faint HUD rings, orange sparks among them, drifting dust. */
export function Backdrop() {
  const rings = useRef<Group>(null);
  const size = useThree((s) => s.size);
  const { dustGeo, dustMat, sparkGeo, sparkMat, arcs, traces } = useMemo(() => {
    const r = rng(5);
    const n = 260, pos = new Float32Array(n * 3), phase = new Float32Array(n);
    for (let i = 0; i < n; i++) { pos.set([(r() - 0.5) * 7, (r() - 0.5) * 4.6, -1.5 - r() * 2], i * 3); phase[i] = r(); }
    const dustGeo = new BufferGeometry();
    dustGeo.setAttribute('position', new Float32BufferAttribute(pos, 3));
    dustGeo.setAttribute('phase', new Float32BufferAttribute(phase, 1));
    // Circuit traces: start on a ring around the head, run outwards in right-angled steps.
    const seg: number[] = [], ends: number[] = [];
    const cy = LAYOUT.head.y - 0.1, zz = -1.3;
    for (let k = 0; k < 46; k++) {
      const ang = (k / 46) * Math.PI * 2 + r() * 0.08;
      let px = Math.cos(ang) * (1.45 + r() * 0.25), py = cy + Math.sin(ang) * (1.3 + r() * 0.2);
      let horiz = Math.abs(Math.cos(ang)) > 0.5;
      for (let s2 = 0; s2 < 3 + Math.floor(r() * 4); s2++) {
        const len = 0.2 + r() * 0.55;
        const nx = horiz ? px + Math.sign(Math.cos(ang) || 1) * len : px;
        const ny = horiz ? py : py + Math.sign(Math.sin(ang) || 1) * len * 0.8;
        seg.push(px, py, zz, nx, ny, zz);
        px = nx; py = ny; horiz = !horiz;
        if (Math.abs(px) > 3.8 || Math.abs(py - cy) > 2.6) break;
      }
      if (r() < 0.6) ends.push(px, py, zz + 0.01);
    }
    for (let i = 0; i < 30; i++) ends.push((r() - 0.5) * 6.5, cy + (r() - 0.5) * 4, zz + 0.02);
    const sparkGeo = new BufferGeometry();
    sparkGeo.setAttribute('position', new Float32BufferAttribute(ends, 3));
    sparkGeo.setAttribute('phase', new Float32BufferAttribute(ends.filter((_, i) => i % 3 === 0).map(() => r()), 1));
    const tg = new LineSegmentsGeometry();
    tg.setPositions(seg);
    const tl = (w: number, o: number) => new LineSegments2(tg, new LineMaterial({ color: COLORS.backdrop.getHex(), linewidth: w, transparent: true, opacity: o, blending: AdditiveBlending, depthWrite: false }));
    // radius, arc length (fraction of a turn), width, opacity, start angle
    const arcs: [number, number, number, number, number][] = [
      [1.55, 1, 0.004, 0.25, 0], [1.85, 0.32, 0.012, 0.35, 0.3], [1.85, 0.22, 0.012, 0.35, 3.6],
      [2.25, 1, 0.003, 0.16, 0], [2.6, 0.18, 0.02, 0.25, 1.2], [2.6, 0.12, 0.02, 0.25, 4.4], [3.1, 1, 0.003, 0.1, 0],
    ];
    return { dustGeo, dustMat: twinkleMaterial(COLORS.backdrop, 0.025, 0.15), sparkGeo, sparkMat: twinkleMaterial(COLORS.spark, 0.09, 0.35), arcs, traces: [tl(6, 0.12), tl(1.6, 0.55)] };
  }, []);
  useEffect(() => () => { dustGeo.dispose(); dustMat.dispose(); sparkGeo.dispose(); sparkMat.dispose(); traces[0].geometry.dispose(); traces.forEach((l) => l.material.dispose()); }, [dustGeo, dustMat, sparkGeo, sparkMat, traces]);
  useEffect(() => { traces.forEach((l) => l.material.resolution.set(size.width, size.height)); }, [traces, size]);
  useFrame((s, dt) => {
    const red = useUi.getState().reducedMotion ? 0.3 : 1;
    rings.current?.children.forEach((m, i) => { m.rotation.z += dt * 0.04 * red * (i % 2 ? -1 : 1) * (1 + i * 0.2); });
    dustMat.uniforms.time.value = s.clock.elapsedTime * red;
    sparkMat.uniforms.time.value = s.clock.elapsedTime * red;
  });
  return (
    <group>
      <group ref={rings} position={[0, LAYOUT.head.y - 0.1, -1.2]}>
        {arcs.map(([rad, len, w, o, a0], i) => (
          <mesh key={i} rotation={[0, 0, a0]}>
            <torusGeometry args={[rad, w, 4, 160, Math.PI * 2 * len]} />
            <meshBasicMaterial {...add(COLORS.backdrop, o)} />
          </mesh>
        ))}
      </group>
      {traces.map((l, i) => <primitive key={i} object={l} />)}
      <points geometry={sparkGeo} material={sparkMat} />
      <points geometry={dustGeo} material={dustMat} />
    </group>
  );
}
