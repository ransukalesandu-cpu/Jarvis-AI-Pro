import { useThree } from '@react-three/fiber';
import { useEffect, useMemo } from 'react';
import { AdditiveBlending, DoubleSide, Shape, ShapeGeometry } from 'three';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { glassMaterial } from './glass';
import { COLORS } from './palette';

/** Ear outline in its own plane (u forward, v up), as in the reference: a tall C with a lobe. */
function earOutline(n = 28): [number, number][] {
    const pts: [number, number][] = [];
    for (let i = 0; i <= n; i++) {
        const a = Math.PI * 0.42 + (i / n) * Math.PI * 1.3; // from the front top, round the back, to the lobe
        const r = 1 + 0.12 * Math.sin(a * 2);
        pts.push([Math.cos(a) * 0.085 * r - 0.01, Math.sin(a) * 0.17 * r + 0.02]);
    }
    pts.push([0.03, -0.14], [0.045, -0.05]); // lobe back up to the tragus
    return pts;
}
const ANTIHELIX: [number, number][] = Array.from({ length: 14 }, (_, i) => {
    const a = Math.PI * 0.55 + (i / 13) * Math.PI * 1.0;
    return [Math.cos(a) * 0.05 - 0.005, Math.sin(a) * 0.1 + 0.02];
});

const toSegs = (pts: [number, number][]) => {
    const s: number[] = [];
    for (let i = 0; i < pts.length - 1; i++) s.push(pts[i][0], pts[i][1], 0, pts[i + 1][0], pts[i + 1][1], 0);
    return s;
};

/** Two ears on the sides of the head: glass shells with glowing orange rims, like the reference. */
export function Ears() {
    const size = useThree((s) => s.size);
    const built = useMemo(() => {
        const outline = earOutline();
        const shape = new Shape(outline.map(([u, v]) => ({ x: u, y: v }) as never));
        const geo = new ShapeGeometry(shape);
        const glass = glassMaterial(COLORS.rim, COLORS.skin, { bodyAlpha: 0.12, power: 1.2, shade: 0.4 });
        glass.side = DoubleSide; // one shape serves both ears (the left one is mirrored)
        glass.depthTest = false; // the ears sit on the skull's edge; its depth must not clip them (the head only sways a little)
        const lg = new LineSegmentsGeometry();
        lg.setPositions([...toSegs(outline), ...toSegs(ANTIHELIX)]);
        const mk = (w: number, o: number) =>
            new LineMaterial({
                color: COLORS.contour.getHex(),
                linewidth: w,
                transparent: true,
                opacity: o,
                blending: AdditiveBlending,
                depthWrite: false,
                depthTest: false,
                side: DoubleSide,
            }); // the mirrored ear flips the quads' winding
        const lines = [mk(7, 0.2), mk(2, 0.9)];
        const objs = [0, 1].map(() => lines.map((m) => new LineSegments2(lg, m)));
        return { geo, glass, lg, lines, objs };
    }, []);
    useEffect(() => {
        built.lines.forEach((m) => m.resolution.set(size.width, size.height));
    }, [built, size]);
    useEffect(
        () => () => {
            built.geo.dispose();
            built.glass.dispose();
            built.lg.dispose();
            built.lines.forEach((m) => m.dispose());
        },
        [built],
    );
    return (
        <>
            {[-1, 1].map((side, k) => (
                // Mounted on the side of the skull (landmarks 234/454), turned to face out and a little forward.
                <group key={side} position={[side * 0.71, -0.09, -0.08]} rotation={[0, side * (Math.PI / 2 - 0.95), 0]} scale={[side * 1.25, 1.25, 1.25]}>
                    <mesh geometry={built.geo} material={built.glass} renderOrder={3} />
                    {built.objs[k].map((o, i) => (
                        <primitive key={i} object={o} />
                    ))}
                </group>
            ))}
        </>
    );
}
