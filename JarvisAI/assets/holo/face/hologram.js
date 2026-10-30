/* ═══════════════════════════════════════════════════════════════════════════
   BIHANSA — Neural Hologram (pure geometry build)

   There is not a single bitmap in this scene. Everything on screen is drawn
   from one source of truth: the 478 Face-Mesh landmarks measured on her face,
   each carrying a real depth value (z). The 1322 mesh edges become the
   tessellation, the landmark rings become the eyes / lips / jaw, the oval
   becomes the hairline that the floating filaments grow out of.

   The head is a solid 3D object: every landmark is rotated (yaw → pitch),
   perspective-divided, then drawn back-to-front as additive light. Turning
   the pointer rotates the *mesh*, it does not skew a picture.

   Sections
     1. data + model space
     2. surfaces (canvas, DPR, glow buffers)
     3. projection
     4. painter (bucketed additive strokes)
     5. hair filaments
     6. interaction / mic / telemetry / boot
     7. main loop
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const F = window.HOLO_FACE;

  const $ = (id) => document.getElementById(id);
  const stage = $('stage');
  const figure = $('figure');
  const canvas = $('face');
  const waveC = $('wave');

  const REDUCED = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  const S = {
    t: 0, elapsed: 0, last: 0, booted: false, paused: false,
    px: 0, py: 0, tx: 0, ty: 0,          // eased pointer (-1..1)
    yaw: 0, pitch: 0,                     // current head rotation (radians)
    energy: 0.12, targetEnergy: 0.12,
    blink: 0, nextBlink: 3.2,
    mesh: true, hair: true, mic: false,
    sparks: [], pulses: [],
    frameAvg: 0.016, degraded: 0,
  };

  const live = $('live');
  const announce = (msg) => { if (live) live.textContent = msg; };

  /* ═══ 1. data → model space ════════════════════════════════════════════ */
  /* MediaPipe normalises x,y to 0..1 of the photo and z to roughly the same
     scale as x (negative = towards the camera). To get an undistorted head we
     must undo the photo aspect on y, otherwise the face stretches. y already
     points down in image space, so there is deliberately NO flip here. */

  const MODEL = (function () {
    if (!F || !Array.isArray(F.points) || !F.points.length) return null;

    const aspect = F.aspect || 1;
    const P = F.points;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    let minZ = Infinity, maxZ = -Infinity;

    const flat = [];
    for (let i = 0; i < P.length; i++) {
      const x = P[i][0];
      const y = P[i][1] / aspect;
      const z = P[i][2];
      flat.push(x, y, z);
      if (x < minX) minX = x; if (x > maxX) maxX = x;
      if (y < minY) minY = y; if (y > maxY) maxY = y;
      if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
    }

    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    const cz = (minZ + maxZ) / 2;
    const n = P.length;
    const X = new Float32Array(n), Y = new Float32Array(n), Z = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      X[i] = flat[i * 3] - cx;
      Y[i] = flat[i * 3 + 1] - cy;
      Z[i] = flat[i * 3 + 2] - cz;
    }

    const edges = [];
    for (let i = 0; i < (F.edges || []).length; i++) edges.push(F.edges[i][0], F.edges[i][1]);

    return {
      X, Y, Z, n,
      edges: Int16Array.from(edges),
      height: maxY - minY,
      faceOval: F.faceOval || [],
      leftEye: F.leftEye || [],
      rightEye: F.rightEye || [],
      lips: F.lips || [],
      irisL: (F.iris && F.iris.left) | 0,
      irisR: (F.iris && F.iris.right) | 0,
      stats: F.stats || {},
    };
  })();

  /* ═══ 2. surfaces ══════════════════════════════════════════════════════ */

  const mainCtx = canvas ? canvas.getContext('2d', { alpha: true }) : null;

  let scene = null, sctx = null;        // offscreen: the geometry pass
  let glow = null, gctx = null;         // quarter-res blurred copy (bloom)
  let W = 1, H = 1, DPR = 1;
  let supportFilter = true;

  function makeCanvas() {
    const c = document.createElement('canvas');
    return c;
  }

  function resize() {
    if (!canvas || !mainCtx) return;
    const rect = canvas.getBoundingClientRect ? canvas.getBoundingClientRect() : { width: 0, height: 0 };
    W = Math.max(1, Math.round(rect.width || canvas.clientWidth || 900));
    H = Math.max(1, Math.round(rect.height || canvas.clientHeight || 720));
    DPR = Math.min(window.devicePixelRatio || 1, 2);

    canvas.width = Math.round(W * DPR);
    canvas.height = Math.round(H * DPR);

    if (!scene) { scene = makeCanvas(); sctx = scene.getContext('2d'); }
    if (!glow) { glow = makeCanvas(); gctx = glow.getContext('2d'); }
    if (!sctx || !gctx) return;

    scene.width = canvas.width;
    scene.height = canvas.height;
    // bloom buffer at 45% linear resolution — a blur of a small image is cheap
    glow.width = Math.max(2, Math.round(W * DPR * 0.45));
    glow.height = Math.max(2, Math.round(H * DPR * 0.45));

    sctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    sctx.lineCap = 'round';
    sctx.lineJoin = 'round';
    try { gctx.filter = 'blur(' + Math.max(1.5, 2.6 * DPR) + 'px)'; } catch (err) { supportFilter = false; }
  }

  /* ═══ 3. projection ════════════════════════════════════════════════════ */

  const PX = new Float32Array(MODEL ? MODEL.n : 0);
  const PY = new Float32Array(MODEL ? MODEL.n : 0);
  const PS = new Float32Array(MODEL ? MODEL.n : 0);   // perspective factor, 1 near
  const AP = new Float32Array(MODEL ? MODEL.n : 0);   // aspect correction per point

  const PERSPECTIVE = 1.35;

  // scratch for a projected 3D point
  const _p = { x: 0, y: 0, s: 1 };

  /**
   * Rotate + project one model-space point.
   * yaw turns around the vertical axis, pitch around the horizontal one, then
   * a plain perspective divide makes the near cheek swell and the far cheek
   * fall away — that is what sells the rotation as a solid head.
   */
  function projectPoint(x, y, z, cy, sy, cp, sp, scale, ox, oy) {
    const x1 = x * cy + z * sy;
    const z1 = -x * sy + z * cy;
    const y1 = y * cp - z1 * sp;
    const z2 = y * sp + z1 * cp;
    const s = PERSPECTIVE / (PERSPECTIVE + z2);
    _p.x = ox + x1 * s * scale;
    _p.y = oy + y1 * s * scale;
    _p.s = s;
    return _p;
  }

  function projectAll(cy, sy, cp, sp, scale, ox, oy) {
    const { X, Y, Z, n } = MODEL;
    let smin = Infinity, smax = -Infinity;
    for (let i = 0; i < n; i++) {
      const p = projectPoint(X[i], Y[i], Z[i], cy, sy, cp, sp, scale, ox, oy);
      PX[i] = p.x; PY[i] = p.y; PS[i] = p.s;
      if (p.s < smin) smin = p.s;
      if (p.s > smax) smax = p.s;
    }
    // 0 = far, 1 = near. Used for brightness, node size and colour.
    const span = (smax - smin) || 1;
    for (let i = 0; i < n; i++) AP[i] = (PS[i] - smin) / span;
  }

  /* ═══ 4. painter ═══════════════════════════════════════════════════════ */

  const LEVELS = 14;
  const PALETTE = [];   // far → near
  (function buildPalette() {
    const far = [255, 86, 214];     // #ff56d6
    const mid = [255, 140, 234];
    const near = [255, 226, 252];   // near-white pink
    for (let i = 0; i < LEVELS; i++) {
      const k = i / (LEVELS - 1);
      const a = 0.030 + 0.92 * Math.pow(k, 2.05);
      const c = k < 0.5
        ? far.map((v, j) => Math.round(v + (mid[j] - v) * (k / 0.5)))
        : mid.map((v, j) => Math.round(v + (near[j] - v) * ((k - 0.5) / 0.5)));
      PALETTE.push({ css: `rgba(${c[0]},${c[1]},${c[2]},${a.toFixed(3)})`, a, rgb: c });
    }
  })();

  const BUCKETS = new Map();   // palette level → flat [x1,y1,x2,y2, …]

  function line(lvl, x1, y1, x2, y2) {
    let b = BUCKETS.get(lvl);
    if (!b) { b = []; BUCKETS.set(lvl, b); }
    b.push(x1, y1, x2, y2);
  }

  function flushLines(ctx) {
    if (!BUCKETS.size) return;
    const levels = Array.from(BUCKETS.keys()).sort((a, b) => a - b);
    for (let li = 0; li < levels.length; li++) {
      const lvl = levels[li];
      const b = BUCKETS.get(lvl);
      ctx.beginPath();
      for (let i = 0; i < b.length; i += 4) {
        ctx.moveTo(b[i], b[i + 1]);
        ctx.lineTo(b[i + 2], b[i + 3]);
      }
      ctx.strokeStyle = PALETTE[lvl].css;
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    BUCKETS.clear();
  }

  const NODE_BUCKETS = new Map();

  function node(lvl, x, y, r) {
    let b = NODE_BUCKETS.get(lvl);
    if (!b) { b = []; NODE_BUCKETS.set(lvl, b); }
    b.push(x, y, r);
  }

  function flushNodes(ctx) {
    if (!NODE_BUCKETS.size) return;
    const levels = Array.from(NODE_BUCKETS.keys()).sort((a, b) => a - b);
    for (let li = 0; li < levels.length; li++) {
      const lvl = levels[li];
      const b = NODE_BUCKETS.get(lvl);
      ctx.beginPath();
      for (let i = 0; i < b.length; i += 3) {
        ctx.moveTo(b[i] + b[i + 2], b[i + 1]);
        ctx.arc(b[i], b[i + 1], b[i + 2], 0, Math.PI * 2);
      }
      ctx.fillStyle = PALETTE[lvl].css;
      ctx.fill();
    }
    NODE_BUCKETS.clear();
  }

  const lvlOf = (dn) => Math.max(0, Math.min(LEVELS - 1, (dn * LEVELS) | 0));

  /* feature rings are few enough to stroke individually */
  function ringPath(ctx, indices, colour, width, blinkAmount) {
    if (!indices.length) return;
    let cxs = 0, cys = 0;
    for (let i = 0; i < indices.length; i++) { cxs += PX[indices[i]]; cys += PY[indices[i]]; }
    cxs /= indices.length; cys /= indices.length;
    const squash = 1 - 0.88 * (blinkAmount || 0);

    ctx.beginPath();
    for (let i = 0; i < indices.length; i++) {
      const k = indices[i];
      const x = PX[k];
      const y = cys + (PY[k] - cys) * squash;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.strokeStyle = colour;
    ctx.lineWidth = width;
    ctx.stroke();
  }

  /* ═══ 5. hair filaments ════════════════════════════════════════════════ */

  const HAIR = (function () {
    if (!MODEL) return [];
    const oval = MODEL.faceOval;
    if (!oval.length) return [];

    let fx = 0, fy = 0;
    for (let i = 0; i < oval.length; i++) { fx += MODEL.X[oval[i]]; fy += MODEL.Y[oval[i]]; }
    fx /= oval.length; fy /= oval.length;

    // deterministic pseudo-random so every reload grows the same head of hair
    let seed = 20261031;
    const rnd = () => {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    };

    const seeds = [];
    const N = 176;
    for (let i = 0; i < N; i++) {
      const t = i / N;
      // the hairline runs from one temple, over the crown, to the other.
      // Below the cheekbones there is no hair growing out of her face.
      if (t > 0.46 && t < 0.86) continue;

      const idx = oval[Math.floor(t * oval.length) % oval.length];
      const bx = MODEL.X[idx], by = MODEL.Y[idx], bz = MODEL.Z[idx];
      let ox = bx - fx, oy = by - fy;
      const norm = Math.hypot(ox, oy) || 1;
      ox /= norm; oy /= norm;

      const crown = Math.max(0, Math.min(1, (fy - by) / 0.30));   // 1 at the parting

      // a lock on top of the head has no sideways normal — fan it out to the
      // side it belongs to, otherwise it grows straight up like an antenna
      const sideSign = bx >= fx ? 1 : -1;
      let nx = ox * 0.72 + sideSign * 0.50;
      let ny = oy * 0.72;
      const nn = Math.hypot(nx, ny) || 1;
      nx /= nn; ny /= nn;

      const r = rnd();
      seeds.push({
        bx, by, bz, ox: nx, oy: ny, crown,
        // long locks: about a third of the face height, longest off the crown
        len: 0.17 + 0.26 * crown + 0.12 * r,
        lift: 0.008 + 0.035 * r,               // how far the tip floats up again
        drift: (r - 0.5) * 0.18,               // sideways lean of the lock
        ph: i * 2.399963 + r * 3.1,
        speed: 0.55 + r * 0.5,
        alpha: 0.40 + 0.36 * crown + 0.12 * r,
        sway: 0.010 + 0.014 * r,
        back: 0.05 + 0.20 * r,                 // falls behind the jaw
        fine: false,
      });

      // every anchor sprouts short fine hairs: they soften the hard mesh
      // boundary at the hairline and give the head a fuzzy crown. Anchor
      // points on top of the head also grow longer, lifted hairs, which is
      // what gives the silhouette the volume her hair actually has.
      {
        const extra = crown > 0.5 ? 4 : 2;
        for (let k = 0; k < extra; k++) {
          const r2 = rnd();
          const lifted = k >= 2;                    // the long, upwards hairs
          seeds.push({
            bx, by, bz,
            ox: ox * (lifted ? 0.75 : 0.55) + sideSign * (0.25 + r2 * 0.55),
            oy: lifted ? oy * 1.0 - 0.55 * r2 : oy * 0.9 - 0.18 * r2,
            crown,
            len: lifted ? 0.10 + 0.11 * r2 : 0.05 + 0.075 * r2 + 0.03 * crown,
            lift: lifted ? 0.05 + 0.07 * r2 : 0.004 + 0.02 * r2,
            drift: (r2 - 0.5) * (lifted ? 0.18 : 0.10),
            ph: i * 1.7 + k * 2.1,
            speed: 0.85 + r2 * 0.7,
            alpha: lifted ? 0.26 + 0.20 * r2 : 0.34 + 0.30 * crown,
            sway: 0.012 + 0.010 * r2,
            back: 0.02 + 0.06 * r2,
            fine: true,
          });
        }
      }
    }
    return seeds;
  })();

  const HAIR_STEPS = 7;

  /**
   * One lock = a small chain of segments. It leaves the hairline along the
   * surface normal, gravity takes over (u²), a sine term makes it float, and
   * the tip is pushed back in z so the mass reads as hair behind the jaw.
   */
  function drawHair(ctx, cy, sy, cp, sp, scale, ox, oy, energy) {
    const boost = 1 + energy * 1.1;
    for (let i = 0; i < HAIR.length; i++) {
      const s = HAIR[i];
      const wob = REDUCED ? 0 : Math.sin(S.t * 0.75 * s.speed + s.ph);
      const len = s.len * (s.fine ? 1 + energy * 0.5 : boost);
      const steps = s.fine ? 3 : HAIR_STEPS;
      const baseX = s.bx, baseY = s.by, baseZ = s.bz;

      let p0 = projectPoint(baseX, baseY, baseZ, cy, sy, cp, sp, scale, ox, oy);
      let px = p0.x, py = p0.y;

      for (let k = 1; k <= steps; k++) {
        const u = k / steps;
        const sway = (s.drift + wob * s.sway * 3.0) * u * u;
        const fall = len * (0.12 * u + 0.88 * u * u);          // gravity curve
        const out = len * u * 0.42;

        const x = baseX + s.ox * out + sway;
        const y = baseY + s.oy * out + fall - s.lift * Math.pow(u, 2.4);
        const z = baseZ + s.back * u;

        const p = projectPoint(x, y, z, cy, sy, cp, sp, scale, ox, oy);
        const fade = Math.pow(1 - u, 1.25) * (0.35 + 0.65 * Math.min(1, u * 6));
        const a = s.alpha * fade * (s.fine ? 1 : boost);
        const lvl = Math.max(0, Math.min(LEVELS - 1, Math.round(a * (LEVELS - 1) / 1.1)));
        line(lvl, px, py, p.x, p.y);
        px = p.x; py = p.y;
      }
    }
  }

  /* ═══ 6. scene ═════════════════════════════════════════════════════════ */

  function drawScene() {
    if (!sctx) return;
    sctx.clearRect(0, 0, W, H);
    sctx.globalCompositeOperation = 'lighter';

    if (!MODEL) return;

    const scale = (H * 0.68) / (MODEL.height || 1);
    const ox = W * 0.5;
    const bob = REDUCED ? 0 : Math.sin(S.t * 0.9) * H * 0.006;
    const oy = H * 0.45 + bob;

    // idle sway + pointer parallax, damped
    const idleYaw = REDUCED ? 0 : Math.sin(S.t * 0.31) * 0.10 + Math.sin(S.t * 0.77) * 0.028;
    const idlePitch = REDUCED ? 0 : Math.sin(S.t * 0.43) * 0.02;
    const targetYaw = idleYaw + S.px * 0.30;
    const targetPitch = idlePitch - S.py * 0.16;
    S.yaw += (targetYaw - S.yaw) * 0.09;
    S.pitch += (targetPitch - S.pitch) * 0.09;

    const cy = Math.cos(S.yaw), sy = Math.sin(S.yaw);
    const cp = Math.cos(S.pitch), sp = Math.sin(S.pitch);

    projectAll(cy, sy, cp, sp, scale, ox, oy);

    // ── the light behind the head ─────────────────────────────────────────
    const halo = sctx.createRadialGradient(ox, oy - H * 0.02, 0, ox, oy - H * 0.02, H * 0.62);
    const heat = 0.20 + S.energy * 0.24;
    halo.addColorStop(0, `rgba(150, 6, 118, ${heat.toFixed(3)})`);
    halo.addColorStop(0.42, `rgba(96, 2, 84, ${(heat * 0.42).toFixed(3)})`);
    halo.addColorStop(1, 'rgba(0, 0, 0, 0)');
    sctx.fillStyle = halo;
    sctx.fillRect(0, 0, W, H);

    // ── skull shells: three rings pushed behind the face, plus spokes ─────
    const oval = MODEL.faceOval;
    if (oval.length) {
      let fx = 0, fy = 0;
      for (let i = 0; i < oval.length; i++) { fx += MODEL.X[oval[i]]; fy += MODEL.Y[oval[i]]; }
      fx /= oval.length; fy /= oval.length;

      const shells = [[1.05, 0.07, 0.13], [1.10, 0.14, 0.09], [1.16, 0.215, 0.055]];
      for (let k = 0; k < shells.length; k++) {
        const grow = shells[k][0], back = shells[k][1], alpha = shells[k][2];
        sctx.beginPath();
        for (let i = 0; i <= oval.length; i++) {
          const idx = oval[i % oval.length];
          const p = projectPoint(
            fx + (MODEL.X[idx] - fx) * grow,
            fy + (MODEL.Y[idx] - fy) * grow + 0.01 * k,
            MODEL.Z[idx] + back, cy, sy, cp, sp, scale, ox, oy);
          if (i === 0) sctx.moveTo(p.x, p.y); else sctx.lineTo(p.x, p.y);
        }
        sctx.strokeStyle = `rgba(255, 92, 222, ${alpha})`;
        sctx.lineWidth = 1;
        sctx.stroke();

        if (k === shells.length - 1) {
          const step = Math.max(1, Math.round(oval.length / 18));
          sctx.beginPath();
          for (let i = 0; i < oval.length; i += step) {
            const idx = oval[i];
            const p = projectPoint(
              fx + (MODEL.X[idx] - fx) * grow,
              fy + (MODEL.Y[idx] - fy) * grow + 0.01 * k,
              MODEL.Z[idx] + back, cy, sy, cp, sp, scale, ox, oy);
            sctx.moveTo(p.x, p.y);
            sctx.lineTo(PX[idx], PY[idx]);
          }
          sctx.strokeStyle = 'rgba(255, 100, 226, 0.055)';
          sctx.lineWidth = 1;
          sctx.stroke();
        }
      }
    }

    // ── floating hair ─────────────────────────────────────────────────────
    if (S.hair) drawHair(sctx, cy, sy, cp, sp, scale, ox, oy, S.energy);

    // ── the volume behind the wires: a whisper of light inside her oval ───
    if (S.mesh && oval.length) {
      sctx.beginPath();
      for (let i = 0; i < oval.length; i++) {
        if (i === 0) sctx.moveTo(PX[oval[i]], PY[oval[i]]);
        else sctx.lineTo(PX[oval[i]], PY[oval[i]]);
      }
      sctx.closePath();
      const cheek = sctx.createRadialGradient(ox, oy + H * 0.03, 0, ox, oy + H * 0.03, H * 0.30);
      cheek.addColorStop(0, `rgba(255, 60, 205, ${(0.085 + S.energy * 0.09).toFixed(3)})`);
      cheek.addColorStop(0.55, 'rgba(210, 10, 165, 0.045)');
      cheek.addColorStop(1, 'rgba(150, 0, 120, 0.012)');
      sctx.fillStyle = cheek;
      sctx.fill();
    }

    // ── the mesh itself: the whole lattice, brightness from real depth ────
    if (S.mesh) {
      const E = MODEL.edges;
      const energyLift = S.energy * 0.12;
      for (let e = 0; e < E.length; e += 2) {
        const a = E[e], b = E[e + 1];
        // cull wires that both ends fall outside the canvas
        const ax = PX[a], ay = PY[a], bx2 = PX[b], by2 = PY[b];
        if ((ax < -40 && bx2 < -40) || (ax > W + 40 && bx2 > W + 40)
         || (ay < -40 && by2 < -40) || (ay > H + 40 && by2 > H + 40)) continue;
        const dn = (AP[a] + AP[b]) * 0.5;
        const lvl = lvlOf(Math.min(1, dn * 0.95 + energyLift));
        line(lvl, ax, ay, bx2, by2);
      }
    }

    flushLines(sctx);

    // ── feature rings ─────────────────────────────────────────────────────
    if (S.mesh) {
      const ringW = Math.max(1, 1.15 * Math.min(DPR, 1.6));
      ringPath(sctx, oval, 'rgba(255, 168, 244, 0.55)', ringW, 0);

      // blink squashes each ring towards its own centre
      const eyeA = 0.62 + S.energy * 0.3;
      ringPath(sctx, MODEL.leftEye, `rgba(255, 236, 253, ${eyeA.toFixed(2)})`, ringW, S.blink);
      ringPath(sctx, MODEL.rightEye, `rgba(255, 236, 253, ${eyeA.toFixed(2)})`, ringW, S.blink);
      ringPath(sctx, MODEL.lips, `rgba(255, 132, 232, ${(0.62 + S.energy * 0.3).toFixed(2)})`, ringW * 1.4, 0);
      if (MODEL.innerLips && MODEL.innerLips.length) {
        ringPath(sctx, MODEL.innerLips, `rgba(255, 190, 246, ${(0.45 + S.energy * 0.25).toFixed(2)})`, ringW, 0);
      }

      // brows: canonical brow chains, lifted over each eye
      const brows = MODEL.brows || [];
      sctx.strokeStyle = `rgba(255, 208, 250, ${(0.42 + S.energy * 0.22).toFixed(2)})`;
      sctx.lineWidth = ringW * 2.1;
      sctx.lineCap = 'round';
      sctx.lineJoin = 'round';
      for (let b = 0; b < brows.length; b++) {
        const chain = brows[b];
        sctx.beginPath();
        for (let i = 0; i < chain.length; i++) {
          const p = chain[i];
          if (i === 0) sctx.moveTo(PX[p], PY[p]); else sctx.lineTo(PX[p], PY[p]);
        }
        sctx.stroke();
      }

      // ── nodes ───────────────────────────────────────────────────────────
      const baseR = Math.max(0.55, Math.min(1.5, H / 760)) * (1 + S.energy * 0.35) * (S.degraded === 2 ? 0.8 : 1);
      for (let i = 0; i < MODEL.n; i++) {
        const dn = AP[i];
        const hot = (i % 37) === 0;
        const lvl = lvlOf(Math.min(1, dn * 0.95 + (hot ? 0.22 : 0)));
        node(lvl, PX[i], PY[i], (hot ? 1.9 : 0.75) * baseR * (0.65 + 0.6 * dn));
      }
      flushNodes(sctx);

      // ── iris: two burning points, closed by the blink ────────────────────
      const irisOpen = 1 - S.blink;
      for (const idx of [MODEL.irisL, MODEL.irisR]) {
        if (!idx) continue;
        const x = PX[idx], y = PY[idx];
        const r = H * 0.016 * (1 + S.energy * 0.35) * irisOpen;
        if (r < 0.6) continue;
        const g = sctx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0, `rgba(255, 250, 255, ${(0.55 + S.energy * 0.35).toFixed(2)})`);
        g.addColorStop(0.45, `rgba(255, 150, 240, ${(0.22 + S.energy * 0.2).toFixed(2)})`);
        g.addColorStop(1, 'rgba(255, 90, 220, 0)');
        sctx.fillStyle = g;
        sctx.beginPath();
        sctx.arc(x, y, r, 0, Math.PI * 2);
        sctx.fill();

        const rr = r * 0.46;
        if (rr > 1.2) {
          sctx.beginPath();
          sctx.arc(x, y, rr, 0, Math.PI * 2);
          sctx.strokeStyle = `rgba(255, 246, 255, ${(0.5 * irisOpen).toFixed(2)})`;
          sctx.lineWidth = Math.max(0.8, ringW * 0.8);
          sctx.stroke();
        }
      }
    }

    // ── resonance rings raised by a pulse ─────────────────────────────────
    for (let i = S.pulses.length - 1; i >= 0; i--) {
      const p = S.pulses[i];
      p.age += 1 / 60;
      if (p.age > p.duration) { S.pulses.splice(i, 1); continue; }
      const k = p.age / p.duration;
      const r = (0.08 + k * 0.55) * H;
      sctx.beginPath();
      sctx.ellipse(ox, oy + H * 0.02, r, r * 0.92, 0, 0, Math.PI * 2);
      sctx.strokeStyle = `rgba(255, 120, 232, ${(0.30 * (1 - k)).toFixed(3)})`;
      sctx.lineWidth = 1.2;
      sctx.stroke();
    }

    sctx.globalCompositeOperation = 'source-over';
  }

  function present() {
    if (!mainCtx) return;
    mainCtx.setTransform(1, 0, 0, 1, 0, 0);
    mainCtx.clearRect(0, 0, canvas.width, canvas.height);
    mainCtx.globalCompositeOperation = 'source-over';
    mainCtx.globalAlpha = 1;

    if (scene) mainCtx.drawImage(scene, 0, 0);

    if (glow && supportFilter && scene) {
      gctx.clearRect(0, 0, glow.width, glow.height);
      gctx.globalCompositeOperation = 'source-over';
      gctx.drawImage(scene, 0, 0, glow.width, glow.height);
      mainCtx.globalCompositeOperation = 'lighter';
      mainCtx.globalAlpha = 0.62;
      mainCtx.drawImage(glow, 0, 0, canvas.width, canvas.height);
      mainCtx.globalAlpha = 1;
      mainCtx.globalCompositeOperation = 'source-over';
    }
  }

  /* ═══ 7. telemetry / clock / wave ══════════════════════════════════════ */

  const stats = {
    sync: { el: $('stat-sync'), bar: $('bar-sync'), v: 0.982, jitter: 0.003, fmt: (v) => (v * 100).toFixed(1) + '%' },
    coherence: { el: $('stat-coherence'), bar: $('bar-coherence'), v: 0.946, jitter: 0.012, fmt: (v) => (v * 100).toFixed(1) + '%' },
    gain: { el: $('stat-gain'), bar: $('bar-gain'), v: 0.72, jitter: 0.05, fmt: (v) => (1 + v * 0.6).toFixed(2) + '×' },
  };

  function updateTelemetry() {
    for (const key in stats) {
      const s = stats[key];
      s.v = Math.max(0.35, Math.min(1, s.v + (Math.random() - 0.5) * s.jitter + S.energy * 0.02));
      if (s.el) s.el.textContent = s.fmt(s.v);
      if (s.bar) s.bar.style.setProperty('--v', s.v.toFixed(3));
    }
    const locks = $('kv-locks');
    if (locks) locks.textContent = HAIR.length + ' FILAMENTS';
    if (MODEL) {
      const gp = $('gv-points'); if (gp) gp.textContent = String(F.landmarks || 478);
      const gl = $('gv-lattice'); if (gl) gl.textContent = MODEL.n + ' PTS';
      const ge = $('gv-edges'); if (ge) ge.textContent = String(MODEL.edges.length / 2);
      const gd = $('gv-depth');
      if (gd && MODEL.stats && MODEL.stats.depth) gd.textContent = MODEL.stats.depth.toFixed(3);
    }
    const meshKv = $('kv-mesh');
    if (meshKv && MODEL) meshKv.textContent = (F.landmarks || 478) + ' → ' + MODEL.n + ' PTS';
  }

  function tickClock() {
    const el = $('clock');
    if (!el) return;
    const d = new Date();
    const p = (n) => String(n).padStart(2, '0');
    el.textContent = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }

  function drawWave() {
    if (!waveC || !waveC.getContext) return;
    const ctx = waveC.getContext('2d');
    if (!ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cw = waveC.clientWidth || 220;
    const ch = waveC.clientHeight || 46;
    if (waveC.width !== Math.round(cw * dpr) || waveC.height !== Math.round(ch * dpr)) {
      waveC.width = Math.round(cw * dpr);
      waveC.height = Math.round(ch * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cw, ch);

    const mid = ch / 2;
    const amp = (0.14 + S.energy * 0.9) * mid * 0.95;
    ctx.beginPath();
    for (let i = 0; i <= 64; i++) {
      const k = i / 64;
      const x = k * cw;
      const env = Math.sin(k * Math.PI);
      const y = mid + Math.sin(k * 22 + S.t * 5.2) * amp * env * 0.62
                    + Math.sin(k * 47 - S.t * 2.1) * amp * env * 0.22;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    const grad = ctx.createLinearGradient(0, 0, cw, 0);
    grad.addColorStop(0, 'rgba(255, 90, 220, 0.15)');
    grad.addColorStop(0.5, `rgba(255, 190, 250, ${(0.55 + S.energy * 0.4).toFixed(2)})`);
    grad.addColorStop(1, 'rgba(255, 90, 220, 0.15)');
    ctx.strokeStyle = grad;
    ctx.lineWidth = 1.2;
    ctx.stroke();
  }

  /* ═══ 8. voice ═════════════════════════════════════════════════════════ */

  let audioCtx = null, analyser = null, micStream = null, audioBuf = null;

  async function startMic() {
    if (S.mic || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setMicState(false, 'VOICE N/A');
      announce('Microphone is not available in this browser.');
      return;
    }
    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) throw new Error('no AudioContext');
      audioCtx = new AC();
      const source = audioCtx.createMediaStreamSource(micStream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.75;
      audioBuf = new Uint8Array(analyser.fftSize);
      source.connect(analyser);            // deliberately not routed to destination
      S.mic = true;
      setMicState(true, 'VOICE LIVE');
      announce('Voice link live. The lattice reacts to your voice.');
    } catch (err) {
      S.mic = false;
      setMicState(false, 'VOICE BLOCKED');
      announce('Microphone permission was refused.');
    }
  }

  function stopMic() {
    if (micStream) micStream.getTracks().forEach((t) => t.stop());
    if (audioCtx && audioCtx.close) audioCtx.close().catch(() => {});
    micStream = null; audioCtx = null; analyser = null; audioBuf = null;
    S.mic = false;
    setMicState(false, 'VOICE OFF');
    announce('Voice link closed.');
  }

  function readMicLevel() {
    if (!analyser || !audioBuf) return 0;
    analyser.getByteTimeDomainData(audioBuf);
    let sum = 0;
    for (let i = 0; i < audioBuf.length; i++) {
      const v = (audioBuf[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / audioBuf.length);
    return Math.min(1, rms * 4.2);
  }

  function setMicState(on, label) {
    const btn = $('btn-mic');
    const chip = $('chip-mic');
    if (btn) {
      btn.setAttribute('aria-pressed', String(on));
      btn.classList.toggle('is-live', on);
    }
    if (chip) {
      chip.classList.toggle('dim', !on);
      const text = chip.lastChild;
      if (text && text.nodeType === 3) text.nodeValue = label;
      else chip.append(label);
    }
    setStateLabel(on ? 'LISTENING' : 'IDLE / AMBIENT');
  }

  function setStateLabel(text) {
    const el = $('kv-state');
    if (el) el.textContent = text;
  }

  /* ═══ 9. interaction ═══════════════════════════════════════════════════ */

  function onPointerMove(e) {
    const x = ((e.clientX || 0) / (window.innerWidth || 1)) * 2 - 1;
    const y = ((e.clientY || 0) / (window.innerHeight || 1)) * 2 - 1;
    S.tx = Math.max(-1, Math.min(1, x));
    S.ty = Math.max(-1, Math.min(1, y));
  }

  function figureRect() {
    return figure && figure.getBoundingClientRect
      ? figure.getBoundingClientRect()
      : { left: 0, top: 0, width: 900, height: 700 };
  }

  function addPulse(clientX, clientY) {
    const r = figureRect();
    let x = 0.5, y = 0.4;
    if (r.width > 0) {
      x = (clientX - r.left) / r.width;
      y = (clientY - r.top) / r.height;
    }
    if (!isFinite(x) || !isFinite(y)) { x = 0.5; y = 0.42; }
    S.pulses.push({ age: 0, duration: 1.6 });
    S.pulses.push({ age: 0, duration: 2.4 });
    S.targetEnergy = Math.min(1, S.targetEnergy + 0.45);
    setStateLabel('RESONATING');
    window.setTimeout(() => setStateLabel(S.mic ? 'LISTENING' : 'IDLE / AMBIENT'), 1400);
    if (stage) {
      stage.classList.add('is-pulsing');
      window.setTimeout(() => stage.classList.remove('is-pulsing'), 420);
    }
  }

  const onButton = (e) => !!(e.target && typeof e.target.closest === 'function' && e.target.closest('button'));

  function bind() {
    window.addEventListener('pointermove', onPointerMove, { passive: true });

    window.addEventListener('pointerdown', (e) => {
      if (onButton(e)) return;
      addPulse(e.clientX, e.clientY);
    });

    window.addEventListener('resize', resize);

    const micBtn = $('btn-mic');
    if (micBtn) micBtn.addEventListener('click', () => (S.mic ? stopMic() : startMic()));

    const meshBtn = $('btn-mesh');
    if (meshBtn) {
      meshBtn.addEventListener('click', () => {
        S.mesh = !S.mesh;
        meshBtn.setAttribute('aria-pressed', String(S.mesh));
        announce(S.mesh ? 'Neural mesh shown.' : 'Neural mesh hidden. Only the hair remains.');
      });
    }

    const hairBtn = $('btn-hair');
    if (hairBtn) {
      hairBtn.addEventListener('click', () => {
        S.hair = !S.hair;
        hairBtn.setAttribute('aria-pressed', String(S.hair));
        announce(S.hair ? 'Floating filaments shown.' : 'Floating filaments hidden.');
      });
    }

    const pulseBtn = $('btn-pulse');
    if (pulseBtn) {
      pulseBtn.addEventListener('click', () => {
        const r = figureRect();
        addPulse(r.left + r.width * 0.5, r.top + r.height * 0.35);
      });
    }

    const spinBtn = $('btn-spin');
    if (spinBtn) {
      spinBtn.addEventListener('click', () => {
        S.paused = !S.paused;
        spinBtn.classList.toggle('is-live', S.paused);
        spinBtn.textContent = S.paused ? 'RESUME' : 'PAUSE';
        announce(S.paused ? 'Rotation held.' : 'Rotation running.');
      });
    }

    window.addEventListener('keydown', (e) => {
      if (e.target && /input|textarea/i.test(e.target.tagName || '')) return;
      const k = (e.key || '').toLowerCase();
      if (k === 'v') { S.mic ? stopMic() : startMic(); }
      else if (k === 'm') { meshBtn && meshBtn.click(); }
      else if (k === 'h') { hairBtn && hairBtn.click(); }
      else if (k === 'r') { S.tx = 0; S.ty = 0; announce('View recentred.'); }
      else if (k === 'p' || k === ' ') {
        e.preventDefault();
        const r = figureRect();
        addPulse(r.left + r.width * 0.5, r.top + r.height * 0.35);
      }
    });

    document.addEventListener('visibilitychange', () => { S.last = performance.now(); });
  }

  /* ═══ 10. main loop ════════════════════════════════════════════════════ */

  function frame(now) {
    const rawDt = (now - S.last) / 1000;
    S.last = now;
    const dt = Math.min(0.05, Math.max(0.001, rawDt));
    S.t += dt;
    S.elapsed += dt;

    const ease = 1 - Math.pow(0.0025, dt);
    S.px += (S.tx - S.px) * ease;
    S.py += (S.ty - S.py) * ease;

    const micLevel = S.mic ? readMicLevel() : 0;
    const idle = 0.10 + 0.05 * Math.sin(S.t * 0.9);
    S.targetEnergy = Math.max(micLevel, S.targetEnergy * (1 - dt * 1.8), idle * 0.7);
    S.energy += (S.targetEnergy - S.energy) * Math.min(1, dt * 8);

    // blink: a short squash of the eye rings every few seconds
    if (!REDUCED) {
      S.nextBlink -= dt;
      if (S.nextBlink <= 0) {
        S.nextBlink = 3.4 + Math.random() * 4.2;
        S.blinkStart = S.t;
      }
      if (S.blinkStart !== undefined) {
        const b = (S.t - S.blinkStart) / 0.17;
        S.blink = b >= 1 ? 0 : Math.sin(Math.min(1, b) * Math.PI);
      }
    }

    // adaptive quality: the lattice is ~7k strokes, so on a slow machine give
    // up the bloom pass (and then the landmark dots) rather than the frame rate
    S.frameAvg += (Math.min(rawDt, 0.25) - S.frameAvg) * 0.06;
    if (S.frameAvg > 0.030 && !S.degraded) { S.degraded = 1; supportFilter = false; }
    else if (S.frameAvg > 0.055 && S.degraded === 1) { S.degraded = 2; }

    if (!S.paused) {
      drawScene();
      present();
    }
    drawWave();

    requestAnimationFrame(frame);
  }

  /* ═══ 11. boot ═════════════════════════════════════════════════════════ */

  const BOOT_LINES = [
    'reading 478 face-mesh landmarks…',
    'solving depth field…',
    'welding 1322 synapses…',
    'growing floating filaments…',
    'profile online',
  ];

  function boot() {
    const bar = $('boot-bar');
    const line = $('boot-line');
    const overlay = $('boot');
    let i = 0;

    const setProgress = (v) => {
      if (bar) bar.style.width = Math.round(Math.min(1, v) * 100) + '%';
    };

    const step = window.setInterval(() => {
      if (line && BOOT_LINES[i]) line.textContent = BOOT_LINES[i];
      i++;
      setProgress(0.12 + (i / BOOT_LINES.length) * 0.72);
      if (i >= BOOT_LINES.length) window.clearInterval(step);
    }, 220);

    if (!MODEL && line) line.textContent = 'face_data.js missing — run build_holo_face.py';

    window.setTimeout(() => {
      window.clearInterval(step);
      setProgress(1);
      if (stage) stage.dataset.boot = '0';
      window.setTimeout(() => {
        if (overlay) overlay.classList.add('is-done');
        S.booted = true;
        S.last = performance.now();
        requestAnimationFrame(frame);
        tickClock();
        window.setInterval(tickClock, 1000);
        updateTelemetry();
        window.setInterval(updateTelemetry, 900);
      }, 380);
    }, 1150);
  }

  /* ═══ start ════════════════════════════════════════════════════════════ */

  resize();
  bind();
  if (MODEL) {
    updateTelemetry();
  }
  boot();
})();
