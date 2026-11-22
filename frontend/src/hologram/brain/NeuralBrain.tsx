import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { BufferGeometry, Float32BufferAttribute, type Group } from 'three';
import { useUi } from '../../store';
import { LAYOUT } from '../energy/paths';
import { COLORS } from '../palette';
import { brainCloud, synapses } from './brainShape';
import { haloMaterial, nodeMaterial, synapseMaterial } from './brainMaterials';
import { brainMood } from './lobes';

const SCALE = 1.3;
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
  const n = syn.count * 2;
  const pos = new Float32Array(n * 3), along = new Float32Array(n), phase = new Float32Array(n), rate = new Float32Array(n), lobe = new Float32Array(n), span = new Float32Array(n);
  for (let e = 0; e < syn.count; e++) {
    for (const [k, v] of [[0, syn.a[e]], [1, syn.b[e]]] as const) {
      const o = e * 2 + k;
      pos.set(cloud.pos.subarray(v * 3, v * 3 + 3), o * 3);
      along[o] = k; phase[o] = syn.phase[e]; rate[o] = syn.rate[e]; lobe[o] = cloud.lobe[syn.a[e]];
    }
  }
  const synGeo = new BufferGeometry();
  synGeo.setAttribute('position', new Float32BufferAttribute(pos, 3));
  synGeo.setAttribute('target', new Float32BufferAttribute(pos.slice(), 3));
  synGeo.setAttribute('along', new Float32BufferAttribute(along, 1));
  synGeo.setAttribute('phase', new Float32BufferAttribute(phase, 1));
  synGeo.setAttribute('rate', new Float32BufferAttribute(rate, 1));
  synGeo.setAttribute('lobe', new Float32BufferAttribute(lobe, 1));
  synGeo.setAttribute('span', new Float32BufferAttribute(span, 1));       // target-space length, set when morphing
  return { cloud, syn, nodeGeo, synGeo };
}

/**
 * The centre of the stage: a living neural brain. Thousands of nodes fire on their own clocks;
 * synapses grow, carry signals and dissolve while new ones form, so the network never looks the
 * same twice; lobes glow with what JARVIS is doing (listening: temporal, thinking: frontal,
 * executing: motor/cerebellum, speaking: with the voice). Three draws in all, all motion on the GPU.
 */
export function NeuralBrain({ nodes }: { nodes: number }) {
  const group = useRef<Group>(null);
  const height = useThree((s) => s.size.height);
  const built = useMemo(() => {
    const g = buildBrainGeometry(nodes);
    return { ...g, nodeMat: nodeMaterial(COLORS.circuit, COLORS.node), synMat: synapseMaterial(COLORS.edge, COLORS.node), halo: haloMaterial(COLORS.rim) };
  }, [nodes]);
  const { nodeGeo, synGeo, nodeMat, synMat, halo } = built;
  useEffect(() => () => { nodeGeo.dispose(); synGeo.dispose(); nodeMat.dispose(); synMat.dispose(); halo.dispose(); }, [nodeGeo, synGeo, nodeMat, synMat, halo]);
  useEffect(() => { nodeMat.uniforms.scale.value = height * 2; }, [nodeMat, height]);
  const mood = useRef(brainMood('idle'));
  useFrame((s, dt) => {
    const ui = useUi.getState(), red = ui.reducedMotion ? 0.3 : 1;
    const level = ui.assistant === 'speaking' ? ui.outputLevel : ui.assistant === 'listening' ? ui.inputLevel : 0;
    const goal = brainMood(ui.assistant, level), m = mood.current;
    m.lobes = m.lobes.map((v, i) => ease(v, goal.lobes[i], 4, dt)) as typeof m.lobes;
    m.firing = ease(m.firing, goal.firing, 3, dt);
    m.growth = ease(m.growth, goal.growth, 1.5, dt);
    m.flow = ease(m.flow, goal.flow, 2, dt);
    m.tint = m.tint.map((v, i) => ease(v, goal.tint[i], 4, dt)) as typeof m.tint;
    for (const mat of [nodeMat, synMat]) {
      mat.uniforms.time.value += dt * red;
      mat.uniforms.lobeLevel.value = m.lobes;
      mat.uniforms.tint.value.setRGB(...m.tint);
    }
    nodeMat.uniforms.firing.value = m.firing;
    synMat.uniforms.growth.value = m.growth;
    synMat.uniforms.flow.value = m.flow;
    halo.uniforms.strength.value = 0.14 + 0.25 * Math.max(...m.lobes) * (0.85 + 0.15 * Math.sin(s.clock.elapsedTime * 1.3));
    halo.uniforms.tint.value.setRGB(...m.tint);
    if (group.current) {
      // A three-quarter view that sways slowly: the lobes, the cerebellum and the stem all stay readable.
      group.current.rotation.y = -0.75 + Math.sin(s.clock.elapsedTime * 0.15) * 0.55 * red;
      group.current.rotation.x = -0.08 + Math.sin(s.clock.elapsedTime * 0.25) * 0.04 * red;
    }
  });
  return (
    <group position={[LAYOUT.head.x, LAYOUT.head.y - 0.08, 0]}>
      <mesh material={halo} position={[0, 0.05, -0.6]} renderOrder={0}><planeGeometry args={[3.6, 3.2]} /></mesh>
      <group ref={group} scale={SCALE}>
        <lineSegments geometry={synGeo} material={synMat} frustumCulled={false} renderOrder={2} />
        <points geometry={nodeGeo} material={nodeMat} frustumCulled={false} renderOrder={3} />
      </group>
    </group>
  );
}
