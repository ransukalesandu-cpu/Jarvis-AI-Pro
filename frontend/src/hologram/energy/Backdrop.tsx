import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { AdditiveBlending, BufferGeometry, type Color, Float32BufferAttribute, type Group } from 'three';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { useUi } from '../../store';
import { rng, twinkleMaterial } from '../glass';
import { COLORS } from '../palette';
import { LAYOUT } from './paths';

const add = (color: Color, opacity: number) => ({ color, transparent: true, opacity, blending: AdditiveBlending, depthWrite: false } as const);

/** Behind the head, as in the reference: blue circuit traces running out from faint HUD rings, orange sparks among them, drifting dust. */
export function Backdrop({ halo = true, dust: showDust = true }: { halo?: boolean; dust?: boolean }) {
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
      {traces.map((l, i) => (i === 0 && !halo ? null : <primitive key={i} object={l} />))}
      <points geometry={sparkGeo} material={sparkMat} />
      {showDust && <points geometry={dustGeo} material={dustMat} />}
    </group>
  );
}
