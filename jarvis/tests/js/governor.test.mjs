// Run with: node --test tests/js/   (dev only; the client needs no Node at runtime)
import { test } from "node:test";
import assert from "node:assert/strict";
import { THEME } from "../../client/theme.js";
import { Governor } from "../../client/governor.js";

function feed(g, fps, renderMs, seconds) {
  const step = 1000 / fps;
  for (let t = 0; t <= seconds * 1000; t += step) g.frame(g._t = (g._t || 0) + step, renderMs);
}

test("slow frames step the tier down, never below minimal", () => {
  const changes = [];
  const g = new Governor(THEME, { initialTier: "full", onChange: (t) => changes.push(t) });
  feed(g, 20, 30, 10);
  assert.equal(g.tier, "minimal");
  assert.deepEqual(changes, ["reduced", "minimal"]);
});

test("cheap frames step back up after sustained headroom", () => {
  // A fast device renders at whatever cap the current tier sets.
  const g = new Governor(THEME, { initialTier: "minimal" });
  let t = 0;
  while (t < 40000) { t += 1000 / g.params().maxFps; g.frame(t, 1); }
  assert.equal(g.tier, "full");
});

test("a capped but expensive tier does not climb", () => {
  const g = new Governor(THEME, { initialTier: "reduced" });
  feed(g, 45, 12, 30);         // holds the cap but costs 12 ms per frame
  assert.equal(g.tier, "reduced");
});

test("manual override pins the tier", () => {
  const g = new Governor(THEME, { initialTier: "full", override: "minimal" });
  feed(g, 10, 50, 10);
  assert.equal(g.tier, "minimal");
  g.setOverride("full");
  feed(g, 10, 50, 10);
  assert.equal(g.tier, "full");
});

test("budget devices start reduced or minimal", () => {
  assert.equal(Governor.initialTierFor({ hardwareConcurrency: 4, deviceMemory: 2 }), "minimal");
  assert.equal(Governor.initialTierFor({ hardwareConcurrency: 4, deviceMemory: 4 }), "reduced");
  assert.equal(Governor.initialTierFor({ hardwareConcurrency: 8, deviceMemory: 8 }), "full");
});
