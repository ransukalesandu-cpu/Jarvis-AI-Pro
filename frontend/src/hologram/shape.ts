/**
 * The head's shape, re-proportioned to the owner's reference face (a bald, domed skull; features
 * sitting lower in a taller head; a strong, angular jaw; the back of the head narrowing into a long
 * cylindrical neck). The MediaPipe mesh is reshaped once here; everything that draws on the head
 * uses these vertices, so traces, contours and chips land on the new shape.
 */
import mesh from './headMesh.json';

export const EYE_LINE = 0.08;
const CRANIUM = 1.14;      // the skull above the eyes is this much taller
const JAW = 1.07;          // the lower face is this much wider
const NECK_TOP = -1.0;
const NECK_LEN = 1.6;      // the neck is this much longer
const NECK_W = 0.8;        // and this much narrower

const smooth = (a: number, b: number, v: number) => { const t = Math.min(1, Math.max(0, (v - a) / (b - a))); return t * t * (3 - 2 * t); };

/** Reshape one point of the original mesh (x, y, z) into the reference's proportions. */
export function reshape(x: number, y: number, z: number): [number, number, number] {
  let nx = x, ny = y;
  if (y > EYE_LINE) ny = EYE_LINE + (y - EYE_LINE) * CRANIUM;              // taller dome
  // An angular jaw: the front of the lower face widens, most at the jaw angle.
  if (y < -0.3 && z > 0.05) nx *= 1 + (JAW - 1) * smooth(-0.3, -0.75, y) * (1 - smooth(-0.95, -1.05, y));
  // The back and sides of the lower head narrow into the neck (no hood).
  const back = smooth(0.3, -0.1, z);
  nx *= 1 - (1 - NECK_W) * smooth(0.05, -0.75, y) * back;
  if (y < NECK_TOP) {                                                        // the neck: longer, narrower
    ny = NECK_TOP + (y - NECK_TOP) * NECK_LEN;
    nx = x * NECK_W;
  }
  return [nx, ny, z];
}

export const SHAPED: Float32Array = (() => {
  const v = mesh.verts, out = new Float32Array(v.length);
  for (let i = 0; i < v.length; i += 3) out.set(reshape(v[i], v[i + 1], v[i + 2]), i);
  return out;
})();

/** Lowest point of the reshaped neck (where the strands leave for the orb), in head space. */
export const NECK_BOTTOM = (() => { let m = 0; for (let i = 1; i < SHAPED.length; i += 3) m = Math.min(m, SHAPED[i]); return m; })();
export const CROWN = (() => { let m = 0; for (let i = 1; i < SHAPED.length; i += 3) m = Math.max(m, SHAPED[i]); return m; })();
