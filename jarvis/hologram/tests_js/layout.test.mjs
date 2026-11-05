import test from 'node:test';
import assert from 'node:assert/strict';
import { LAYOUT } from '../core/scene.js';
import { wireDefinitions } from '../entities/neural_connections.js';

test('face dominates; heart is left and smaller than the orb; orb is below the face and smaller than it', () => {
  const { face, heart, orb, bounds } = LAYOUT;
  const faceDiam = face.height, heartDiam = heart.radius * 2, orbDiam = orb.radius * 2;
  assert.ok(heartDiam < orbDiam, 'heart smaller than orb');
  assert.ok(orbDiam < faceDiam * 0.6, 'orb clearly smaller than the face');
  assert.ok(heart.x < -0.5 * heart.radius && heart.x < face.x, 'heart on the left');
  assert.ok(orb.y + orb.radius < face.y - face.height / 2 + 0.6, 'orb sits below the face');
  assert.ok(Math.abs(orb.x - face.x) < 0.01, 'orb centred under the face');
  for (const e of [heart, orb]) {
    assert.ok(e.x - e.radius >= -bounds.halfWidth && e.x + e.radius <= bounds.halfWidth, 'inside horizontal bounds');
    assert.ok(e.y - e.radius >= bounds.bottom && e.y + e.radius <= bounds.top, 'inside vertical bounds');
  }
});

test('every energy wire links two of the three entities and stays on screen', () => {
  const defs = wireDefinitions();
  const kinds = new Set(defs.map((d) => d.kind));
  assert.deepEqual([...kinds].sort(), [0, 1, 2], 'heart-face, face-orb and heart-orb are all present');
  const { bounds } = LAYOUT;
  for (const d of defs) {
    assert.equal(d.p.length, 4);
    for (const v of d.p) {
      assert.ok(Math.abs(v.x) <= bounds.halfWidth + 0.5 && v.y <= bounds.top + 0.5 && v.y >= bounds.bottom - 0.5, `control point in view (${v.x},${v.y})`);
    }
  }
});
