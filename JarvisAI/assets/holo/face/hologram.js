/* ═══════════════════════════════════════════════════════════════════════════
   BIHANSA — neural hologram engine
   ---------------------------------------------------------------------------
   The face is not drawn from scratch: `face_data.js` holds the 478 Face Mesh
   landmarks measured on her real photo, so the wireframe locks onto her eyes,
   nose and mouth exactly. This file animates everything *around* that plate —
   filaments, eye tracking, projector base, telemetry, voice reaction.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const F = window.HOLO_FACE;
  if (!F || !F.points) {
    console.error('[holo] face_data.js is missing or empty');
    return;
  }

  const $ = (id) => document.getElementById(id);
  const stage = $('stage');
  const figure = $('figure');
  const meshC = $('mesh');
  const strandC = $('strands');
  const fxC = $('fx');
  const bgC = $('bg');
  const waveC = $('wave');

  const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ── state ─────────────────────────────────────────────────────────────── */
  const S = {
    t: 0,
    last: performance.now(),
    px: 0, py: 0,            // eased parallax (-1..1)
    tx: 0, ty: 0,            // target parallax
    energy: 0,               // smoothed voice/pulse energy (0..1)
    targetEnergy: 0,
    mic: false,
    mesh: true,
    hair: true,
    pulses: [],
    sparks: [],
    motes: [],
    lastIdlePulse: 0,
    booted: false,
    elapsed: 0,
  };

  const MESH_SCALE = 1;
  const FX_SCALE = 0.55;
  const MAX_SPARKS = 90;

  const portraitImg = $('portrait');
  const hairEls = [$('hair-left'), $('hair-right')];

  // One 32px radial sprite reused for every spark and dust mote. Building a
  // CanvasGradient per particle per frame cost more than the drawing itself.
  const SPRITE = (() => {
    const c = document.createElement('canvas');
    c.width = c.height = 32;
    const g = c.getContext('2d');
    const grad = g.createRadialGradient(16, 16, 0, 16, 16, 16);
    grad.addColorStop(0, 'rgba(255, 244, 253, 1)');
    grad.addColorStop(0.34, 'rgba(255, 122, 234, 0.55)');
    grad.addColorStop(1, 'rgba(255, 40, 190, 0)');
    g.fillStyle = grad;
    g.fillRect(0, 0, 32, 32);
    return c;
  })();

  const live = $('live');
  const announce = (msg) => { if (live) live.textContent = msg; };

  /* ── canvas helpers ────────────────────────────────────────────────────── */
  function sizeCanvas(canvas, scale) {
    if (!canvas) return null;
    canvas.width = Math.max(2, Math.round(F.width * scale));
    canvas.height = Math.max(2, Math.round(F.height * scale));
    return canvas.getContext('2d');
  }

  const ctxMesh = sizeCanvas(meshC, MESH_SCALE);
  const ctxStrands = sizeCanvas(strandC, FX_SCALE);
  const ctxFx = sizeCanvas(fxC, FX_SCALE);

  /* ═══ 1. static face mesh (drawn once, animated by CSS) ═════════════════ */
  function drawMesh() {
    const ctx = ctxMesh;
    if (!ctx) return;
    const w = meshC.width;
    const h = meshC.height;
    const P = F.points.map(([x, y]) => [x * w, y * h]);
    const unit = w / 1298;                      // keeps strokes visually even

    ctx.clearRect(0, 0, w, h);
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';

    // tessellation — one path, one stroke
    ctx.beginPath();
    for (let k = 0; k < F.edges.length; k++) {
      const a = P[F.edges[k][0]];
      const b = P[F.edges[k][1]];
      if (!a || !b) continue;
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
    }
    ctx.strokeStyle = 'rgba(255, 96, 220, 0.115)';
    ctx.lineWidth = 0.9 * unit;
    ctx.stroke();

    // feature rings read brighter than the tesselation
    const ring = (indices, colour, width) => {
      if (!indices || !indices.length) return;
      ctx.beginPath();
      for (let k = 0; k < indices.length; k++) {
        const p = P[indices[k]];
        if (!p) continue;
        if (k === 0) ctx.moveTo(p[0], p[1]);
        else ctx.lineTo(p[0], p[1]);
      }
      ctx.closePath();
      ctx.strokeStyle = colour;
      ctx.lineWidth = width * unit;
      ctx.stroke();
    };
    ring(F.faceOval, 'rgba(255, 150, 238, 0.34)', 1.4);
    ring(F.leftEye, 'rgba(255, 200, 250, 0.75)', 1.2);
    ring(F.rightEye, 'rgba(255, 200, 250, 0.75)', 1.2);
    ring(F.lips, 'rgba(255, 120, 228, 0.60)', 1.2);

    // nodes with a few hotter ones
    for (let i = 0; i < P.length; i++) {
      const p = P[i];
      if (!p) continue;
      const hot = i % 37 === 0;
      ctx.beginPath();
      ctx.arc(p[0], p[1], (hot ? 2.1 : 0.9) * unit, 0, Math.PI * 2);
      ctx.fillStyle = hot ? 'rgba(255, 225, 252, 0.6)' : 'rgba(255, 140, 232, 0.28)';
      ctx.fill();
    }
    ctx.globalCompositeOperation = 'source-over';
  }

  /* ═══ 2. hair filaments ════════════════════════════════════════════════ */
  const seeds = (F.hairSeeds || []).map((s, i) => ({
    ...s,
    ph: (i * 2.399963) % (Math.PI * 2),
    sp: 0.55 + (i % 9) * 0.075,
    bucket: i % 3,
  }));

  function drawStrands(dt) {
    const ctx = ctxStrands;
    if (!ctx || !S.hair) return;
    const w = strandC.width;
    const h = strandC.height;
    ctx.clearRect(0, 0, w, h);
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineCap = 'round';

    const unit = w / 1298;
    const breathe = 1 + S.energy * 1.15;
    const sway = 0.55 + S.energy * 0.9;

    for (let b = 0; b < 3; b++) {
      ctx.beginPath();
      for (let i = b; i < seeds.length; i += 3) {
        const s = seeds[i];
        const x0 = s.x * w;
        const y0 = s.y * h;
        const len = s.l * h * 1.15 * breathe;
        const wave = Math.sin(S.t * s.sp + s.ph) * sway;
        const cos = Math.cos(wave * 0.55);
        const sin = Math.sin(wave * 0.55);
        const nx = (s.dx * cos - s.dy * sin) || 0;
        const ny = (s.dx * sin + s.dy * cos) || 0;

        const midX = x0 + nx * len * 0.42 + Math.sin(S.t * 1.15 + s.ph) * len * 0.20;
        const midY = y0 + ny * len * 0.42;
        const endX = x0 + nx * len + Math.sin(S.t * 0.85 + s.ph * 1.7) * len * 0.34;
        const endY = y0 + ny * len + Math.cos(S.t * 1.35 + s.ph) * len * 0.16;

        ctx.moveTo(x0, y0);
        ctx.quadraticCurveTo(midX, midY, endX, endY);
      }
      ctx.strokeStyle = ['rgba(255, 70, 214, 0.16)', 'rgba(255, 130, 236, 0.22)', 'rgba(255, 190, 248, 0.15)'][b];
      ctx.lineWidth = [3.2, 2.0, 1.2][b] * unit * (1 + S.energy * 0.6);
      ctx.stroke();
    }
    ctx.globalCompositeOperation = 'source-over';
  }

  /* ═══ 3. eyes, sparks, pulses ══════════════════════════════════════════ */
  function spawnSpark(fromHair) {
    if (S.sparks.length >= MAX_SPARKS) return;
    let x, y;
    if (fromHair && seeds.length) {
      const s = seeds[(Math.random() * seeds.length) | 0];
      x = s.x;
      y = s.y;
    } else {
      x = 0.2 + Math.random() * 0.6;
      y = 0.55 + Math.random() * 0.4;
    }
    S.sparks.push({
      x, y,
      vx: (Math.random() - 0.5) * 0.012,
      vy: -0.015 - Math.random() * 0.035,
      life: 1,
      decay: 0.16 + Math.random() * 0.35,
      size: 0.6 + Math.random() * 1.5,
    });
  }

  function drawFx(dt) {
    const ctx = ctxFx;
    if (!ctx) return;
    const w = fxC.width;
    const h = fxC.height;
    const unit = w / 1298;
    ctx.clearRect(0, 0, w, h);
    ctx.globalCompositeOperation = 'lighter';

    /* eyes follow the cursor */
    const iris = F.iris || {};
    const lookX = S.px * 0.010;
    const lookY = S.py * 0.008;
    [iris.left, iris.right].forEach((idx, n) => {
      const p = F.points[idx];
      if (!p) return;
      // the left/right iris drift together, with a whisper of independent life
      const drift = Math.sin(S.t * 0.7 + n * 2.1) * 0.0016;
      const ex = (p[0] + lookX + drift) * w;
      const ey = (p[1] + lookY + drift * 0.6) * h;
      const r = 0.016 * h * (1 + S.energy * 0.35);

      const g = ctx.createRadialGradient(ex, ey, 0, ex, ey, r);
      const a = 0.34 + S.energy * 0.42;
      g.addColorStop(0, `rgba(255, 236, 253, ${a})`);
      g.addColorStop(0.32, `rgba(255, 120, 232, ${a * 0.55})`);
      g.addColorStop(1, 'rgba(255, 40, 190, 0)');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(ex, ey, r, 0, Math.PI * 2);
      ctx.fill();

      ctx.beginPath();
      ctx.arc(ex, ey, 1.6 * unit, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255, 255, 255, 0.75)';
      ctx.fill();
    });

    /* filaments that break away and float upward */
    if (S.hair && !REDUCED) {
      if (Math.random() < dt * 9) spawnSpark(true);
      for (let i = S.sparks.length - 1; i >= 0; i--) {
        const s = S.sparks[i];
        s.x += s.vx * dt;
        s.y += s.vy * dt;
        s.vy -= 0.004 * dt;
        s.life -= s.decay * dt;
        if (s.life <= 0) { S.sparks.splice(i, 1); continue; }
        const px = s.x * w;
        const py = s.y * h;
        const r = s.size * unit * 3.2;
        ctx.globalAlpha = 0.55 * s.life;
        ctx.drawImage(SPRITE, px - r, py - r, r * 2, r * 2);
        ctx.globalAlpha = 1;
      }
    }

    /* click pulses expand out from wherever you touched her */
    for (let i = S.pulses.length - 1; i >= 0; i--) {
      const p = S.pulses[i];
      p.age += dt;
      const life = 1 - p.age / p.duration;
      if (life <= 0) { S.pulses.splice(i, 1); continue; }
      const r = (0.06 + p.age / p.duration * 0.62) * h * (p.scale || 1);
      ctx.beginPath();
      ctx.ellipse(p.x * w, p.y * h, r * 0.62, r, 0, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(255, ${Math.round(120 + 90 * life)}, 240, ${0.55 * life})`;
      ctx.lineWidth = (2.4 * life + 0.4) * unit;
      ctx.stroke();

      ctx.beginPath();
      ctx.ellipse(p.x * w, p.y * h, r * 0.42, r * 0.68, 0, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(255, 200, 250, ${0.28 * life})`;
      ctx.lineWidth = 1 * unit;
      ctx.stroke();
    }
    ctx.globalCompositeOperation = 'source-over';
  }

  /* ═══ 4. background dust ═══════════════════════════════════════════════ */
  let bgCtx = null;
  function sizeBackground() {
    if (!bgC) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    bgC.width = Math.round(window.innerWidth * dpr * 0.75);
    bgC.height = Math.round(window.innerHeight * dpr * 0.75);
    bgCtx = bgC.getContext('2d');
    if (!S.motes.length) {
      for (let i = 0; i < 110; i++) {
        S.motes.push({
          x: Math.random(),
          y: Math.random(),
          r: 0.4 + Math.random() * 1.8,
          sp: 0.004 + Math.random() * 0.016,
          ph: Math.random() * Math.PI * 2,
          a: 0.15 + Math.random() * 0.5,
        });
      }
    }
  }

  function drawBackground(dt) {
    if (!bgCtx) return;
    const w = bgC.width;
    const h = bgC.height;
    bgCtx.clearRect(0, 0, w, h);
    bgCtx.globalCompositeOperation = 'lighter';
    for (const m of S.motes) {
      m.y -= m.sp * dt * 0.18;
      if (m.y < -0.02) { m.y = 1.02; m.x = Math.random(); }
      const x = (m.x + Math.sin(S.t * 0.25 + m.ph) * 0.012 - S.px * 0.02) * w;
      const y = m.y * h;
      const r = m.r * (w / 900) * 4;
      const a = m.a * (0.5 + 0.5 * Math.sin(S.t * 0.9 + m.ph));
      bgCtx.globalAlpha = a * 0.55;
      bgCtx.drawImage(SPRITE, x - r, y - r, r * 2, r * 2);
    }
    bgCtx.globalAlpha = 1;
    bgCtx.globalCompositeOperation = 'source-over';
  }

  /* ═══ 5. voice carrier ═════════════════════════════════════════════════ */
  function drawWave() {
    if (!waveC || !waveC.getContext) return;
    const ctx = waveC.getContext('2d');
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = waveC.clientWidth || 220;
    const h = 46;
    if (waveC.width !== Math.round(w * dpr)) {
      waveC.width = Math.round(w * dpr);
      waveC.height = Math.round(h * dpr);
    }
    const W = waveC.width;
    const H = waveC.height;
    ctx.clearRect(0, 0, W, H);

    const mid = H / 2;
    const amp = (0.12 + S.energy * 0.85) * mid * 0.9;
    ctx.beginPath();
    for (let i = 0; i <= 64; i++) {
      const x = (i / 64) * W;
      const k = i / 64;
      const env = Math.sin(k * Math.PI);
      const y = mid + Math.sin(k * 26 + S.t * 5.5) * amp * env * 0.6
                    + Math.sin(k * 11 - S.t * 2.2) * amp * env * 0.4;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = 'rgba(255, 140, 236, 0.9)';
    ctx.lineWidth = 1.6 * dpr;
    ctx.shadowColor = 'rgba(255, 60, 210, 0.9)';
    ctx.shadowBlur = 8 * dpr;
    ctx.stroke();
    ctx.shadowBlur = 0;

    ctx.beginPath();
    ctx.moveTo(0, mid);
    ctx.lineTo(W, mid);
    ctx.strokeStyle = 'rgba(255, 100, 226, 0.14)';
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  /* ═══ 6. audio ═════════════════════════════════════════════════════════ */
  let audioCtx = null;
  let analyser = null;
  let audioBuf = null;
  let audioStream = null;

  async function startMic() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setMicState(false, 'NO MIC API');
      return;
    }
    try {
      audioStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === 'suspended') await audioCtx.resume();
      const source = audioCtx.createMediaStreamSource(audioStream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.72;
      source.connect(analyser);
      audioBuf = new Uint8Array(analyser.fftSize);
      setMicState(true, 'VOICE LIVE');
      announce('Voice link active. The hologram reacts to your voice.');
    } catch (err) {
      setMicState(false, 'MIC BLOCKED');
      announce('Microphone access was refused. The hologram stays ambient.');
    }
  }

  function stopMic() {
    if (audioStream) audioStream.getTracks().forEach((t) => t.stop());
    audioStream = null;
    analyser = null;
    audioBuf = null;
    setMicState(false, 'VOICE OFF');
    announce('Voice link closed.');
  }

  function readMicLevel() {
    if (!analyser || !audioBuf) return 0;
    analyser.getByteTimeDomainData(audioBuf);
    let sum = 0;
    for (let i = 0; i < audioBuf.length; i += 4) {
      const v = (audioBuf[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / (audioBuf.length / 4));
    return Math.min(1, rms * 4.2);
  }

  function setMicState(on, label) {
    S.mic = on;
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

  /* ═══ 7. telemetry ═════════════════════════════════════════════════════ */
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
    if (locks) locks.textContent = seeds.length + ' LOCKS';
    const meshKv = $('kv-mesh');
    if (meshKv) meshKv.textContent = F.points.length + ' PTS';
  }

  function tickClock() {
    const el = $('clock');
    if (!el) return;
    const d = new Date();
    const p = (n) => String(n).padStart(2, '0');
    el.textContent = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }

  /* ═══ 8. interaction ═══════════════════════════════════════════════════ */
  function onPointerMove(e) {
    const x = (e.clientX / window.innerWidth) * 2 - 1;
    const y = (e.clientY / window.innerHeight) * 2 - 1;
    S.tx = Math.max(-1, Math.min(1, x));
    S.ty = Math.max(-1, Math.min(1, y));
  }

  function figureRect() {
    return figure.getBoundingClientRect();
  }

  function addPulse(clientX, clientY) {
    const r = figureRect();
    let x = 0.5, y = 0.4;
    if (r.width > 0) {
      x = (clientX - r.left) / r.width;
      y = (clientY - r.top) / r.height;
    }
    if (!isFinite(x) || !isFinite(y)) { x = 0.5; y = 0.42; }
    x = Math.max(-0.2, Math.min(1.2, x));
    y = Math.max(-0.2, Math.min(1.2, y));
    S.pulses.push({ x, y, age: 0, duration: 1.5 });
    S.pulses.push({ x, y, age: 0, duration: 2.3, scale: 1.5 });
    S.targetEnergy = Math.min(1, S.targetEnergy + 0.45);
    for (let i = 0; i < 14; i++) spawnSpark(false);
    setStateLabel('RESONATING');
    window.setTimeout(() => setStateLabel(S.mic ? 'LISTENING' : 'IDLE / AMBIENT'), 1400);
    stage.classList.add('is-pulsing');
    window.setTimeout(() => stage.classList.remove('is-pulsing'), 420);
  }

  // the event target is not always an Element (window, document, SVG nodes)
  const onButton = (e) => !!(e.target && typeof e.target.closest === 'function' && e.target.closest('button'));

  function bind() {
    window.addEventListener('pointermove', onPointerMove, { passive: true });
    window.addEventListener('pointerdown', (e) => {
      if (onButton(e)) return;
      addPulse(e.clientX, e.clientY);
    });
    window.addEventListener('dblclick', (e) => {
      if (onButton(e)) return;
      addPulse(e.clientX, e.clientY);
      S.targetEnergy = 1;
    });
    window.addEventListener('resize', sizeBackground);

    const micBtn = $('btn-mic');
    if (micBtn) micBtn.addEventListener('click', () => (S.mic ? stopMic() : startMic()));

    const meshBtn = $('btn-mesh');
    if (meshBtn) {
      meshBtn.addEventListener('click', () => {
        S.mesh = !S.mesh;
        meshBtn.setAttribute('aria-pressed', String(S.mesh));
        meshC.classList.toggle('is-off', !S.mesh);
        announce(S.mesh ? 'Face mesh shown.' : 'Face mesh hidden.');
      });
    }

    const hairBtn = $('btn-hair');
    if (hairBtn) {
      hairBtn.addEventListener('click', () => {
        S.hair = !S.hair;
        hairBtn.setAttribute('aria-pressed', String(S.hair));
        strandC.classList.toggle('is-off', !S.hair);
        hairEls.forEach((el) => el && el.classList.toggle('is-off', !S.hair));
        announce(S.hair ? 'Floating hair shown.' : 'Floating hair hidden.');
      });
    }

    const pulseBtn = $('btn-pulse');
    if (pulseBtn) {
      pulseBtn.addEventListener('click', () => {
        const r = figureRect();
        addPulse(r.left + r.width * 0.5, r.top + r.height * 0.3);
      });
    }

    window.addEventListener('keydown', (e) => {
      if (e.target && /input|textarea/i.test(e.target.tagName || '')) return;
      const k = e.key.toLowerCase();
      if (k === 'v') { S.mic ? stopMic() : startMic(); }
      else if (k === 'm') { meshBtn && meshBtn.click(); }
      else if (k === 'h') { hairBtn && hairBtn.click(); }
      else if (k === 'p' || k === ' ') {
        e.preventDefault();
        const r = figureRect();
        addPulse(r.left + r.width * 0.5, r.top + r.height * 0.3);
      }
    });

    document.addEventListener('visibilitychange', () => {
      S.last = performance.now();
    });
  }

  /* ═══ 9. main loop ═════════════════════════════════════════════════════ */
  let telemetryTimer = null;

  function frame(now) {
    const rawDt = (now - S.last) / 1000;
    S.last = now;
    const dt = Math.min(0.05, Math.max(0.001, rawDt));
    S.t += dt;
    S.elapsed += dt;

    // ease parallax
    const ease = 1 - Math.pow(0.0025, dt);
    S.px += (S.tx - S.px) * ease;
    S.py += (S.ty - S.py) * ease;

    // voice level (or a slow idle breath when the mic is off)
    const micLevel = S.mic ? readMicLevel() : 0;
    const idle = 0.10 + 0.05 * Math.sin(S.t * 0.9);
    S.targetEnergy = Math.max(micLevel, S.targetEnergy * (1 - dt * 1.8), idle * 0.7);
    S.energy += (S.targetEnergy - S.energy) * Math.min(1, dt * 8);

    // idle pulses keep the scene alive when nobody is touching it
    if (S.elapsed - S.lastIdlePulse > 17 && !REDUCED) {
      S.lastIdlePulse = S.elapsed;
      const r = figureRect();
      if (r.width) addPulse(r.left + r.width * (0.35 + Math.random() * 0.3), r.top + r.height * (0.2 + Math.random() * 0.2));
    }

    if (!REDUCED) {
      const idleX = Math.sin(S.t * 0.23) * 0.055;
      const idleY = Math.cos(S.t * 0.19) * 0.04;
      const px = S.px + idleX;
      const py = S.py + idleY;
      figure.style.transform =
        `rotateY(${(px * 6.5).toFixed(2)}deg) rotateX(${(-py * 4.4).toFixed(2)}deg) ` +
        `translate3d(${(px * 10).toFixed(2)}px, ${(py * 6).toFixed(2)}px, 0) ` +
        `scale(${(1 + S.energy * 0.012).toFixed(4)})`;
      stage.style.setProperty('--mx', px.toFixed(3));
      stage.style.setProperty('--my', py.toFixed(3));
    }

    drawStrands(dt);
    drawFx(dt);
    drawBackground(dt);
    drawWave();

    requestAnimationFrame(frame);
  }

  /* ═══ 10. boot ═════════════════════════════════════════════════════════ */
  const BOOT_LINES = [
    'mounting face mesh…',
    'verifying 478 landmarks…',
    'linking hair filaments…',
    'calibrating projector base…',
    'profile online',
  ];

  function preload() {
    const urls = ['portrait.webp', 'hair_left.webp', 'hair_right.webp'];
    return Promise.all(urls.map((u) => new Promise((resolve) => {
      const img = new Image();
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
      img.src = u;
    })));
  }

  async function boot() {
    const bar = $('boot-bar');
    const line = $('boot-line');
    const overlay = $('boot');
    let progress = 0;

    const setProgress = (v) => {
      progress = Math.min(1, v);
      if (bar) bar.style.width = Math.round(progress * 100) + '%';
    };

    let i = 0;
    const step = window.setInterval(() => {
      if (line && BOOT_LINES[i]) line.textContent = BOOT_LINES[i];
      i++;
      setProgress(0.15 + (i / BOOT_LINES.length) * 0.6);
      if (i >= BOOT_LINES.length) window.clearInterval(step);
    }, 240);

    const decoded = await Promise.race([
      preload(),
      new Promise((r) => window.setTimeout(() => r([]), 6000)),
    ]);

    const ok = decoded.filter(Boolean).length;
    if (line && ok === 0) line.textContent = 'portrait plate missing — run build_holo_face.py';
    setProgress(1);
    window.clearInterval(step);
    stage.dataset.boot = '0';

    window.setTimeout(() => {
      if (overlay) overlay.classList.add('is-done');
      S.booted = true;
      S.last = performance.now();
      requestAnimationFrame(frame);
      tickClock();
      window.setInterval(tickClock, 1000);
      updateTelemetry();
      telemetryTimer = window.setInterval(updateTelemetry, 700);
    }, 420);
  }

  /* ═══ start ════════════════════════════════════════════════════════════ */
  drawMesh();
  sizeBackground();
  bind();
  boot();
})();
