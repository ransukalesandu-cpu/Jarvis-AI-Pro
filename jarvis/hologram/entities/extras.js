// Everything around the face, assembled in one place: heart, orb, connections, aura.
import * as THREE from '../vendor/three.module.min.js';
import { QuantumHeart } from './quantum_heart.js';
import { EnergyOrb } from './energy_orb.js';
import { NeuralConnections } from './neural_connections.js';
import { Aura } from './aura.js';

export function createExtras(q, uniforms) {
  const group = new THREE.Group();
  const parts = [new Aura(q, uniforms), new NeuralConnections(q, uniforms), new QuantumHeart(q, uniforms), new EnergyOrb(q, uniforms)];
  for (const p of parts) group.add(p.group);
  return {
    group,
    parts,
    update(dt, now, params, prof) { for (const p of parts) p.update(dt, now, params, prof); },
    dispose() { for (const p of parts) p.dispose(); group.clear(); },
  };
}
