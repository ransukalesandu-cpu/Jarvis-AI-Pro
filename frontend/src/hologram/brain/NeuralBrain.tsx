import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { BufferGeometry, Float32BufferAttribute, type Group, Vector3 } from 'three';
import { useUi } from '../../store';
import { LAYOUT } from '../energy/paths';
import { COLORS } from '../palette';
import { brainCloud, synapses } from './brainShape';
import { haloMaterial, nodeMaterial, synapseMaterial } from './brainMaterials';
import { brainMood } from './lobes';
import { LINK_STEPS, linkPoint, orbLinks } from './orbLinks';
import { assign, type ShapeName, shapePoints, textPoints } from './shapes';
import { textMask } from './textMask';
import { visualState } from '../visualState';

/** Seconds a shape is held before the brain flows back. */
export const SHAPE_HOLD_S = 12;

const SCALE = 1.3;
const BRAIN_Y = LAYOUT.head.y - 0.08;
/** The long neurons into the orb: brighter than the brain's own synapses so the link reads. */
function linkMaterial() {
    const m = synapseMaterial(COLORS.wire, COLORS.orbCore);
    m.uniforms.boost.value = 0.3;
    return m;
}

const ease = (a: number, b: number, rate: number, dt: number) => a + (b - a) * (1 - Math.exp(-rate * dt));

/** Builds the node and synapse geometries (with a `target` per vertex for morphing). */
export function buildBrainGeometry(nodes: number) {
    const cloud = brainCloud(nodes);
    const syn = synapses(cloud);
    const nodeGeo = new BufferGeometry();
    nodeGeo.setAttribute('position', new Float32BufferAttribute(cloud.pos, 3));
    nodeGeo.setAttribute('target', new Float32BufferAttribute(cloud.pos.slice(), 3));
    nodeGeo.setAttribute('lobe', new Float32BufferAttribute(Float32Array.from(cloud.lobe), 1));
    nodeGeo.setAttribute('phase', new Float32BufferAttribute(cloud.phase, 1));
    nodeGeo.setAttribute('wander', new Float32BufferAttribute(cloud.wander, 1));
    const n = syn.count * 2;
    const pos = new Float32Array(n * 3),
        along = new Float32Array(n),
        phase = new Float32Array(n),
        rate = new Float32Array(n),
        lobe = new Float32Array(n),
        span = new Float32Array(n);
    const nphase = new Float32Array(n),
        wander = new Float32Array(n),
        synNode = new Uint32Array(n);
    for (let e = 0; e < syn.count; e++) {
        for (const [k, v] of [
            [0, syn.a[e]],
            [1, syn.b[e]],
        ] as const) {
            const o = e * 2 + k;
            pos.set(cloud.pos.subarray(v * 3, v * 3 + 3), o * 3);
            along[o] = k;
            phase[o] = syn.phase[e];
            rate[o] = syn.rate[e];
            lobe[o] = cloud.lobe[syn.a[e]];
            nphase[o] = cloud.phase[v];
            wander[o] = cloud.wander[v]; // each end drifts with its neuron
            synNode[o] = v;
        }
    }
    const synGeo = new BufferGeometry();
    synGeo.setAttribute('position', new Float32BufferAttribute(pos, 3));
    synGeo.setAttribute('target', new Float32BufferAttribute(pos.slice(), 3));
    synGeo.setAttribute('along', new Float32BufferAttribute(along, 1));
    synGeo.setAttribute('phase', new Float32BufferAttribute(phase, 1));
    synGeo.setAttribute('rate', new Float32BufferAttribute(rate, 1));
    synGeo.setAttribute('lobe', new Float32BufferAttribute(lobe, 1));
    synGeo.setAttribute('span', new Float32BufferAttribute(span, 1)); // target-space length, set when morphing
    synGeo.setAttribute('nphase', new Float32BufferAttribute(nphase, 1));
    synGeo.setAttribute('wander', new Float32BufferAttribute(wander, 1));
    return { cloud, syn, nodeGeo, synGeo, synNode };
}

/**
 * The centre of the stage: a living neural brain. Thousands of nodes fire on their own clocks;
 * synapses grow, carry signals and dissolve while new ones form, so the network never looks the
 * same twice; lobes glow with what JARVIS is doing (listening: temporal, thinking: frontal,
 * executing: motor/cerebellum, speaking: with the voice). Three draws in all, all motion on the GPU.
 */
export function NeuralBrain({ nodes, links: linkCount = 36 }: { nodes: number; links?: number }) {
    const group = useRef<Group>(null);
    const height = useThree((s) => s.size.height);
    const built = useMemo(() => {
        const g = buildBrainGeometry(nodes);
        // Links live in the outer group's space; the orb is fixed there, the brain sways inside it.
        const orb = { x: LAYOUT.orb.x, y: LAYOUT.orb.y - BRAIN_Y, z: 0.1, r: LAYOUT.orb.r };
        const links = orbLinks(g.cloud, linkCount, orb);
        const n = links.length * LINK_STEPS * 2;
        const linkGeo = new BufferGeometry();
        const along = new Float32Array(n),
            phase = new Float32Array(n),
            rate = new Float32Array(n);
        links.forEach((l, i) => {
            for (let k = 0; k < LINK_STEPS; k++)
                for (const j of [0, 1]) {
                    const o = (i * LINK_STEPS + k) * 2 + j;
                    along[o] = (k + j) / LINK_STEPS;
                    phase[o] = l.phase;
                    rate[o] = l.rate;
                }
        });
        linkGeo.setAttribute('position', new Float32BufferAttribute(new Float32Array(n * 3), 3));
        linkGeo.setAttribute('target', new Float32BufferAttribute(new Float32Array(n * 3), 3));
        linkGeo.setAttribute('along', new Float32BufferAttribute(along, 1));
        linkGeo.setAttribute('phase', new Float32BufferAttribute(phase, 1));
        linkGeo.setAttribute('rate', new Float32BufferAttribute(rate, 1));
        linkGeo.setAttribute('lobe', new Float32BufferAttribute(new Float32Array(n).fill(5), 1)); // they glow with the stem
        for (const name of ['span', 'nphase', 'wander']) linkGeo.setAttribute(name, new Float32BufferAttribute(new Float32Array(n), 1));
        return {
            ...g,
            links,
            linkGeo,
            nodeMat: nodeMaterial(COLORS.circuit, COLORS.node),
            synMat: synapseMaterial(COLORS.edge, COLORS.node),
            linkMat: linkMaterial(),
            halo: haloMaterial(COLORS.rim),
        };
    }, [nodes, linkCount]);
    const { nodeGeo, synGeo, linkGeo, links, cloud, synNode, nodeMat, synMat, linkMat, halo } = built;
    useEffect(
        () => () => {
            [nodeGeo, synGeo, linkGeo, nodeMat, synMat, linkMat, halo].forEach((r) => r.dispose());
        },
        [nodeGeo, synGeo, linkGeo, nodeMat, synMat, linkMat, halo],
    );
    const tmp = useMemo(() => new Vector3(), []);
    // Shape morphing: a request is applied once the brain is (back) at rest, then held, then released.
    const shapeReq = useUi((s) => s.brainShape);
    const morph = useRef<{ value: number; goal: number; until: number; pending: null | { shape: ShapeName; text: string }; target: Float32Array }>({
        value: 0,
        goal: 0,
        until: 0,
        pending: null,
        target: Float32Array.from(cloud.pos),
    });
    // A new quality profile rebuilds the brain: start that one at rest.
    useEffect(() => {
        morph.current = { value: 0, goal: 0, until: 0, pending: null, target: Float32Array.from(cloud.pos) };
    }, [cloud]);
    useEffect(() => {
        if (!shapeReq) return;
        const m = morph.current;
        if (shapeReq.shape === 'brain') {
            m.pending = null;
            m.goal = 0;
            return;
        }
        m.pending = { shape: shapeReq.shape, text: shapeReq.text };
        m.goal = 0; // flow back first if another shape is showing
    }, [shapeReq]);
    const applyShape = (shape: ShapeName, text: string) => {
        const n = cloud.count;
        const pts = shape === 'text' ? textPoints(textMask(text, 512, 160), 512, 160, n) : shapePoints(shape as Exclude<ShapeName, 'brain' | 'text'>, n);
        const tgt = assign(cloud.pos, pts);
        morph.current.target = tgt;
        (nodeGeo.getAttribute('target').array as Float32Array).set(tgt);
        nodeGeo.getAttribute('target').needsUpdate = true;
        const st = synGeo.getAttribute('target'),
            sp = synGeo.getAttribute('span');
        const sa = st.array as Float32Array,
            spa = sp.array as Float32Array;
        for (let o = 0; o < synNode.length; o++) sa.set(tgt.subarray(synNode[o] * 3, synNode[o] * 3 + 3), o * 3);
        for (let o = 0; o < synNode.length; o += 2) {
            const d = Math.hypot(sa[o * 3] - sa[o * 3 + 3], sa[o * 3 + 1] - sa[o * 3 + 4], sa[o * 3 + 2] - sa[o * 3 + 5]);
            spa[o] = spa[o + 1] = d; // long in the shape = hidden while morphed
        }
        st.needsUpdate = true;
        sp.needsUpdate = true;
    };
    useEffect(() => {
        nodeMat.uniforms.scale.value = height * 2;
    }, [nodeMat, height]);
    const mood = useRef(brainMood('idle'));
    useFrame((s, dt) => {
        const ui = useUi.getState(),
            red = ui.reducedMotion ? 0.3 : 1;
        const vs = visualState(ui); // real state only: 'offline' when the backend link is down, never 'listening' with the mic muted
        const level = vs === 'speaking' ? ui.outputLevel : vs === 'listening' ? ui.inputLevel : 0;
        const mo = morph.current,
            now = s.clock.elapsedTime;
        if (mo.pending && mo.value < 0.02) {
            applyShape(mo.pending.shape, mo.pending.text);
            mo.pending = null;
            mo.goal = 1;
            mo.until = now + SHAPE_HOLD_S;
        }
        if (mo.goal === 1 && now > mo.until) mo.goal = 0;
        mo.value = ease(mo.value, mo.goal, ui.reducedMotion ? 6 : 2.2, dt);
        nodeMat.uniforms.morph.value = synMat.uniforms.morph.value = mo.value;
        const goal = brainMood(vs, level),
            m = mood.current;
        m.lobes = m.lobes.map((v, i) => ease(v, goal.lobes[i], 4, dt)) as typeof m.lobes;
        m.firing = ease(m.firing, goal.firing, 3, dt);
        m.growth = ease(m.growth, goal.growth, 1.5, dt);
        m.flow = ease(m.flow, goal.flow, 2, dt);
        m.tint = m.tint.map((v, i) => ease(v, goal.tint[i], 4, dt)) as typeof m.tint;
        for (const mat of [nodeMat, synMat, linkMat]) {
            mat.uniforms.time.value += dt * red;
            mat.uniforms.lobeLevel.value = m.lobes;
            mat.uniforms.tint.value.setRGB(...m.tint);
        }
        nodeMat.uniforms.firing.value = m.firing;
        synMat.uniforms.growth.value = m.growth;
        synMat.uniforms.flow.value = m.flow;
        linkMat.uniforms.growth.value = Math.min(0.92, m.growth + 0.3); // the links to the orb are mostly alive
        linkMat.uniforms.flow.value = 0.6 + m.flow * 0.6;
        // Re-draw the links from where the anchor neurons are now (the brain sways; the orb does not).
        const inner = group.current;
        if (inner) {
            inner.updateMatrix();
            const pos = linkGeo.getAttribute('position'),
                tgt = linkGeo.getAttribute('target');
            const arr = pos.array as Float32Array;
            links.forEach((l, i) => {
                const o = l.anchor * 3,
                    k = mo.value;
                tmp.set(
                    cloud.pos[o] + (mo.target[o] - cloud.pos[o]) * k,
                    cloud.pos[o + 1] + (mo.target[o + 1] - cloud.pos[o + 1]) * k,
                    cloud.pos[o + 2] + (mo.target[o + 2] - cloud.pos[o + 2]) * k,
                ).applyMatrix4(inner.matrix);
                const a: [number, number, number] = [tmp.x, tmp.y, tmp.z];
                let prev = a;
                for (let k = 0; k < LINK_STEPS; k++) {
                    const next = linkPoint(a, l, (k + 1) / LINK_STEPS),
                        o = (i * LINK_STEPS + k) * 6;
                    arr.set(prev, o);
                    arr.set(next, o + 3);
                    prev = next;
                }
            });
            (tgt.array as Float32Array).set(arr);
            pos.needsUpdate = true;
            tgt.needsUpdate = true;
        }
        halo.uniforms.strength.value = 0.14 + 0.25 * Math.max(...m.lobes) * (0.85 + 0.15 * Math.sin(s.clock.elapsedTime * 1.3));
        halo.uniforms.tint.value.setRGB(...m.tint);
        if (group.current) {
            // A three-quarter view that sways slowly: the lobes, the cerebellum and the stem all stay readable.
            // A shape faces the viewer; the brain keeps its three-quarter sway.
            const sway = -0.75 + Math.sin(s.clock.elapsedTime * 0.15) * 0.55 * red;
            group.current.rotation.y = sway * (1 - mo.value) + Math.sin(s.clock.elapsedTime * 0.4) * 0.12 * red * mo.value;
            group.current.rotation.x = (-0.08 + Math.sin(s.clock.elapsedTime * 0.25) * 0.04 * red) * (1 - mo.value);
        }
    });
    return (
        <group position={[LAYOUT.head.x, BRAIN_Y, 0]}>
            <mesh material={halo} position={[0, 0.05, -0.6]} renderOrder={0}>
                <planeGeometry args={[3.6, 3.2]} />
            </mesh>
            <lineSegments geometry={linkGeo} material={linkMat} frustumCulled={false} renderOrder={2} />
            <group ref={group} scale={SCALE}>
                <lineSegments geometry={synGeo} material={synMat} frustumCulled={false} renderOrder={2} />
                <points geometry={nodeGeo} material={nodeMat} frustumCulled={false} renderOrder={3} />
            </group>
        </group>
    );
}
