import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import { AdditiveBlending, BufferGeometry, CatmullRomCurve3, Color, Float32BufferAttribute, type Group, type Mesh, type Points, Vector3 } from 'three';
import { COLORS, orbColor } from './palette';
import { useUi } from '../store';

export const LAYOUT = { head: { x: 0, y: 0.55 }, heart: { x: -1.35, y: -0.78, r: 0.17 }, orb: { x: 0, y: -1.5, r: 0.28 } };
const WIRES = 5;

function glowMat(color: Color, opacity: number) {
  return { color, transparent: true, opacity, blending: AdditiveBlending, depthWrite: false } as const;
}

/** Small quantum heart (left) with a warm aura. Beats with the shared clock. */
export function Heart() {
  const core = useRef<Group>(null);
  useFrame((s) => {
    const t = s.clock.elapsedTime, red = useUi.getState().reducedMotion ? 0.3 : 1;
    const beat = 1 + 0.12 * Math.max(0, Math.sin(t * 5.2)) ** 3 * red + 0.03 * Math.sin(t * 2.1) * red;
    core.current?.scale.setScalar(beat);
  });
  const { x, y, r } = LAYOUT.heart;
  return (
    <group position={[x, y, 0.2]} ref={core}>
      <mesh><circleGeometry args={[r * 2.6, 40]} /><meshBasicMaterial {...glowMat(COLORS.heartSoft, 0.10)} /></mesh>
      <mesh><circleGeometry args={[r * 1.6, 40]} /><meshBasicMaterial {...glowMat(COLORS.heart, 0.22)} /></mesh>
      <mesh><icosahedronGeometry args={[r, 1]} /><meshStandardMaterial color={COLORS.heart} emissive={COLORS.heart} emissiveIntensity={1.1} flatShading /></mesh>
    </group>
  );
}

/** Larger energy orb under the face. Reflects the assistant state with real levels only. */
export function Orb() {
  const ring = useRef<Mesh>(null);
  const ring2 = useRef<Mesh>(null);
  const halo = useRef<Mesh>(null);
  const core = useRef<Mesh>(null);
  const col = useMemo(() => new Color(), []);
  useFrame((s, dt) => {
    const ui = useUi.getState(), t = s.clock.elapsedTime, red = ui.reducedMotion ? 0.3 : 1;
    col.lerp(orbColor(ui.assistant), Math.min(1, dt * 4));
    const level = ui.assistant === 'speaking' ? ui.outputLevel : ui.assistant === 'listening' ? ui.inputLevel : 0;
    const spin = ui.assistant === 'thinking' || ui.assistant === 'searching' || ui.assistant === 'executing' ? 2.4 : 0.35;
    const breathe = 1 + 0.05 * Math.sin(t * 1.4) * red + level * 0.35;
    core.current?.scale.setScalar(breathe);
    halo.current?.scale.setScalar(1 + level * 0.5 + 0.04 * Math.sin(t * 1.1) * red);
    if (ring.current) { ring.current.rotation.z += dt * spin * red; ring.current.rotation.x = 1.15 + Math.sin(t * 0.5) * 0.1 * red; }
    if (ring2.current) { ring2.current.rotation.z -= dt * spin * 0.7 * red; ring2.current.rotation.x = 1.0; }
    for (const m of [ring.current, ring2.current, halo.current, core.current]) if (m) ((m.material as unknown) as { color: Color }).color.copy(col);
  });
  const { x, y, r } = LAYOUT.orb;
  return (
    <group position={[x, y, 0.2]}>
      <mesh ref={halo}><circleGeometry args={[r * 1.8, 48]} /><meshBasicMaterial {...glowMat(COLORS.orb, 0.10)} /></mesh>
      <mesh ref={core}><sphereGeometry args={[r, 32, 24]} /><meshBasicMaterial {...glowMat(COLORS.orb, 0.38)} /></mesh>
      <mesh><sphereGeometry args={[r * 0.42, 24, 16]} /><meshBasicMaterial {...glowMat(COLORS.orbCore, 0.55)} /></mesh>
      <mesh ref={ring}><torusGeometry args={[r * 1.35, 0.008, 8, 96]} /><meshBasicMaterial {...glowMat(COLORS.orb, 0.8)} /></mesh>
      <mesh ref={ring2}><torusGeometry args={[r * 1.65, 0.006, 8, 96]} /><meshBasicMaterial {...glowMat(COLORS.orb, 0.5)} /></mesh>
    </group>
  );
}

/** Energy wires neck -> heart and heart -> orb; light travels along them while JARVIS speaks or works. */
export function Wires() {
  const pulses = useRef<Points>(null);
  const curves = useMemo(() => {
    const neck = new Vector3(0, -0.72, 0.1), heart = new Vector3(LAYOUT.heart.x, LAYOUT.heart.y, 0.1), orb = new Vector3(LAYOUT.orb.x, LAYOUT.orb.y, 0.1);
    const list: CatmullRomCurve3[] = [];
    for (let i = 0; i < WIRES; i++) {
      const k = (i - (WIRES - 1) / 2) / ((WIRES - 1) / 2);
      list.push(new CatmullRomCurve3([
        neck.clone().add(new Vector3(k * 0.22, 0, 0)),
        new Vector3(heart.x * 0.55 + k * 0.1, -0.78 - Math.abs(k) * 0.05, 0.1),
        heart.clone().add(new Vector3(k * 0.05, 0.05, 0)),
        new Vector3((heart.x + orb.x) / 2 + k * 0.1, (heart.y + orb.y) / 2 - 0.12, 0.1),
        orb.clone().add(new Vector3(k * 0.12, 0.2, 0)),
      ]));
    }
    return list;
  }, []);
  const lineGeos = useMemo(() => curves.map((c) => new BufferGeometry().setFromPoints(c.getPoints(60))), [curves]);
  const pulseGeo = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(new Float32Array(WIRES * 2 * 3), 3));
    return g;
  }, []);
  useFrame((s) => {
    const ui = useUi.getState(), t = s.clock.elapsedTime;
    const active = ui.assistant === 'speaking' || ui.assistant === 'thinking' || ui.assistant === 'executing' || ui.assistant === 'searching';
    const mat = pulses.current?.material as { opacity: number } | undefined;
    if (mat) mat.opacity += ((active ? 0.95 : 0.35) - mat.opacity) * 0.1;
    const arr = pulseGeo.getAttribute('position').array as Float32Array;
    const speed = active ? 0.45 : 0.12;
    const p = new Vector3();
    for (let i = 0; i < WIRES; i++) for (let j = 0; j < 2; j++) {
      curves[i].getPoint((t * speed + i * 0.17 + j * 0.5) % 1, p);
      arr.set([p.x, p.y, p.z], (i * 2 + j) * 3);
    }
    pulseGeo.getAttribute('position').needsUpdate = true;
  });
  return (
    <group>
      {lineGeos.map((g, i) => (
        <line key={i}>
          <primitive object={g} attach="geometry" />
          <lineBasicMaterial color={COLORS.wire} transparent opacity={0.28} blending={AdditiveBlending} depthWrite={false} />
        </line>
      ))}
      <points ref={pulses} geometry={pulseGeo}>
        <pointsMaterial color={COLORS.orbCore} size={0.06} sizeAttenuation transparent opacity={0.4} blending={AdditiveBlending} depthWrite={false} />
      </points>
    </group>
  );
}
