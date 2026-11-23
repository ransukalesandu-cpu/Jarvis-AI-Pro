/**
 * Aperture iris: N curved blades pivoting on a ring (radius 1 in eye space), like a camera iris.
 * Each blade's inner edge is a straight line from its pivot; swinging it by phi leaves a central
 * opening of radius sin(phi), so the opening follows the aperture directly. Pure, unit-tested.
 */
export const BLADES = 9;
export const BLADE_LEN = 1.15;     // past the centre, so a shut iris has no hole
export const BLADE_W = 0.8;        // crescent width, enough for neighbours to overlap
export const MASK_INNER = 0.85;    // the socket ring covers the blades' roots outside this radius
const OPEN_MAX = 0.95;

/** Blade outline in its own frame: pivot at the origin, inner edge along +x, body toward -y. */
export function bladeOutline(steps = 14): [number, number][] {
  const pts: [number, number][] = [];
  for (let i = 0; i <= steps; i++) pts.push([(BLADE_LEN * i) / steps, 0]);
  for (let i = steps; i >= 0; i--) {
    const s = (BLADE_LEN * i) / steps;
    pts.push([s, -BLADE_W * Math.min(1, 2 * Math.sin((Math.PI * s) / BLADE_LEN))]);
  }
  return pts;
}

/** Pivot and rotation of blade i at an aperture 0..1. */
export function bladePose(i: number, aperture: number, n = BLADES): { x: number; y: number; angle: number } {
  const theta = (i / n) * Math.PI * 2;
  const phi = Math.asin(Math.min(1, Math.max(0, aperture)) * OPEN_MAX);
  return { x: Math.cos(theta), y: Math.sin(theta), angle: theta + Math.PI - phi };
}

/** Radius of the central opening (smallest distance from the centre to any blade). */
export function openingRadius(aperture: number, n = BLADES): number {
  const outline = bladeOutline(40);
  let best = Infinity;
  for (let i = 0; i < n; i++) {
    const p = bladePose(i, aperture, n), c = Math.cos(p.angle), s = Math.sin(p.angle);
    for (let k = 0; k < outline.length; k++) {
      const [ax, ay] = outline[k], [bx, by] = outline[(k + 1) % outline.length];
      const A = [p.x + ax * c - ay * s, p.y + ax * s + ay * c], B = [p.x + bx * c - by * s, p.y + bx * s + by * c];
      const dx = B[0] - A[0], dy = B[1] - A[1], L2 = dx * dx + dy * dy || 1;
      const u = Math.min(1, Math.max(0, -(A[0] * dx + A[1] * dy) / L2));
      best = Math.min(best, Math.hypot(A[0] + dx * u, A[1] + dy * u));
    }
  }
  return best;
}
