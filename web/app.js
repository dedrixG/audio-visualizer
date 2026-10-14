(() => {
  "use strict";

  const canvas = document.getElementById("viz");
  const ctx = canvas.getContext("2d", { alpha: false });
  const statusEl = document.getElementById("status");
  const hintEl = document.getElementById("hint");
  const clockEl = document.getElementById("clock");
  const clockTime = document.getElementById("clockTime");
  const clockDate = document.getElementById("clockDate");
  const fileAudio = document.getElementById("fileAudio");
  const filePick = document.getElementById("filePick");
  const phoneUrlEl = document.getElementById("phoneUrl");
  const connectEl = document.getElementById("connect");
  const toastEl = document.getElementById("toast");

  const N_BARS = 96;
  const FFT_N = 1024;
  const THEMES = {
    ion: ["#5ce1ff", "#7a8bff", "#ff4dce"],
    magma: ["#ff7a33", "#ff4d6d", "#ffd36a"],
    aurora: ["#3dffb0", "#5ce1ff", "#d0ff66"],
    mono: ["#f4f7ff", "#9aa4b8", "#d0d6e2"],
  };
  const THEME_LABELS = { ion: "Ion", magma: "Magma", aurora: "Aurora", mono: "Mono" };
  const SHUFFLE_PRESETS = [0, 15, 30, 60, 120, 300, 600];
  const SHUFFLE_EVERY_KEY = "av.shuffleEvery";

  function savedShuffleEvery() {
    try {
      const n = Number(localStorage.getItem(SHUFFLE_EVERY_KEY));
      return SHUFFLE_PRESETS.includes(n) ? n : 0;
    } catch {
      return 0;
    }
  }

  const state = {
    running: false,
    source: "system",
    style: "bars",
    theme: "ion",
    palette: "",
    shuffleEvery: savedShuffleEvery(),
    timedPalette: "",
    shuffleAt: 0,
    gain: 1.35,
    glow: 0.65,
    dim: 1,
    bins: new Float32Array(N_BARS),
    peaks: new Float32Array(N_BARS),
    wave: new Float32Array(256),
    particles: [],
    audioCtx: null,
    analyser: null,
    micStream: null,
    mediaSource: null,
    ws: null,
    pcm: new Float32Array(FFT_N),
    pcmReady: false,
    wakeLock: null,
    lastUi: Date.now(),
    lastClock: 0,
    bassS: 0,
    midS: 0,
    motionLast: 0,
    yaw: 0,
    precess: 0,
    rotor: 0,
    helixSpin: 0,
    spokeSpin: 0,
  };
  if (state.shuffleEvery > 0) state.shuffleAt = Date.now() + state.shuffleEvery * 1000;

  const smoothBins = new Float32Array(N_BARS);

  const fftReal = new Float32Array(FFT_N);
  const fftImag = new Float32Array(FFT_N);
  const mag = new Float32Array(FFT_N / 2);
  const windowFn = new Float32Array(FFT_N);
  for (let i = 0; i < FFT_N; i++) windowFn[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (FFT_N - 1)));

  const params = new URLSearchParams(location.search);
  const isMobile = matchMedia("(pointer: coarse)").matches || innerWidth < 700;
  if (params.get("style")) {
    state.style = params.get("style");
    setSeg("styleSeg", "style", state.style);
    if (state.style === "aod") {
      state.glow = 0.15;
      state.dim = 0.55;
      document.getElementById("glow").value = "0.15";
      document.getElementById("dim").value = "0.55";
    }
  } else if (isMobile) {
    state.style = "aod";
    state.glow = 0.15;
    state.dim = 0.55;
    document.getElementById("glow").value = "0.15";
    document.getElementById("dim").value = "0.55";
    setSeg("styleSeg", "style", "aod");
  }

  function setStatus(text) {
    statusEl.textContent = text;
  }

  function toast(text) {
    toastEl.textContent = text;
    toastEl.classList.remove("hidden");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.add("hidden"), 2200);
  }

  function setSeg(id, attr, value) {
    document.querySelectorAll(`#${id} .seg-btn`).forEach((b) => {
      b.classList.toggle("on", b.dataset[attr] === value);
    });
  }

  function hexToRgb(hex) {
    const n = parseInt(hex.slice(1), 16);
    return [n >> 16, (n >> 8) & 255, n & 255];
  }

  const ACCENTS = {
    ion: ["#5ce1ff", "#ff4dce"],
    magma: ["#ff7a33", "#ffd36a"],
    aurora: ["#3dffb0", "#5ce1ff"],
    mono: ["#e8eef7", "#8b93a7"],
  };
  const FADE_MS = 1600;
  const colorFade = {
    from: THEMES.ion.map(hexToRgb),
    to: THEMES.ion.map(hexToRgb),
    accentFrom: ACCENTS.ion.map(hexToRgb),
    accentTo: ACCENTS.ion.map(hexToRgb),
    start: 0,
    dur: 0,
    name: "ion",
  };
  let frameStops = colorFade.to;

  function mixRgb(a, b, t) {
    return [
      a[0] + (b[0] - a[0]) * t,
      a[1] + (b[1] - a[1]) * t,
      a[2] + (b[2] - a[2]) * t,
    ];
  }

  function rgbCss(c) {
    return `rgb(${c[0] | 0},${c[1] | 0},${c[2] | 0})`;
  }

  function fadeProgress(now) {
    if (colorFade.dur <= 0) return 1;
    let t = (now - colorFade.start) / colorFade.dur;
    if (t >= 1) {
      colorFade.dur = 0;
      colorFade.from = colorFade.to;
      colorFade.accentFrom = colorFade.accentTo;
      return 1;
    }
    if (t < 0) t = 0;
    return t * t * (3 - 2 * t);
  }

  function blendStops(from, to, t) {
    if (t >= 1) return to;
    return from.map((a, i) => mixRgb(a, to[i], t));
  }

  function followPalette() {
    const next = paletteName();
    if (!THEMES[next] || next === colorFade.name) return;
    const now = performance.now();
    const t = fadeProgress(now);
    colorFade.from = blendStops(colorFade.from, colorFade.to, t).map((c) => c.slice());
    colorFade.accentFrom = blendStops(colorFade.accentFrom, colorFade.accentTo, t).map((c) => c.slice());
    colorFade.to = THEMES[next].map(hexToRgb);
    colorFade.accentTo = (ACCENTS[next] || ACCENTS.ion).map(hexToRgb);
    colorFade.start = now;
    colorFade.dur = FADE_MS;
    colorFade.name = next;
  }

  function presentColors(now) {
    const t = fadeProgress(now);
    frameStops = blendStops(colorFade.from, colorFade.to, t);
    const accents = blendStops(colorFade.accentFrom, colorFade.accentTo, t);
    document.body.style.setProperty("--accent", rgbCss(accents[0]));
    document.body.style.setProperty("--accent2", rgbCss(accents[1]));
  }

  function paletteName() {
    if (state.shuffleEvery > 0 && state.timedPalette && THEMES[state.timedPalette]) return state.timedPalette;
    if (state.theme === "shuffle") return state.palette && THEMES[state.palette] ? state.palette : "ion";
    return state.theme;
  }

  function themeStop(i) {
    return rgbCss(frameStops[i]);
  }

  function themeColor(t) {
    const c = frameStops;
    if (t < 0.5) return rgbCss(mixRgb(c[0], c[1], t * 2));
    return rgbCss(mixRgb(c[1], c[2], (t - 0.5) * 2));
  }

  function nextPalette() {
    const names = Object.keys(THEMES).filter((name) => name !== state.palette);
    return names[(Math.random() * names.length) | 0];
  }

  function timerOverrides() {
    return state.shuffleEvery > 0;
  }

  function applyTheme() {
    const live = paletteName();
    const overriding = timerOverrides();
    document.body.className = document.body.className.replace(/theme-\w+/g, "").trim();
    document.body.classList.add("theme-" + live);
    if (state.style === "aod") document.body.classList.add("aod-mode");
    document.querySelectorAll("#themeSeg .seg-btn").forEach((b) => {
      b.classList.toggle("on", b.dataset.theme === state.theme);
      b.classList.toggle("live", overriding && b.dataset.theme === live);
    });
    const themeSeg = document.getElementById("themeSeg");
    if (themeSeg) themeSeg.classList.toggle("overridden", overriding);
    const shuffleBtn = document.querySelector('#themeSeg [data-theme="shuffle"]');
    if (shuffleBtn) {
      if (overriding) shuffleBtn.title = "Timer is overriding color · " + (THEME_LABELS[live] || "Ion");
      else if (state.theme === "shuffle") shuffleBtn.title = "Shuffle · " + (THEME_LABELS[live] || "Ion");
      else shuffleBtn.title = "Shuffle by song";
    }
    const field = document.getElementById("shuffleTimer");
    const everyEl = document.getElementById("shuffleEvery");
    const label = document.getElementById("shuffleTimerLabel");
    if (field) field.classList.toggle("on", overriding);
    if (everyEl && everyEl.value !== String(state.shuffleEvery)) everyEl.value = String(state.shuffleEvery);
    if (label) label.textContent = overriding ? "Timer overrides" : "Shuffle every";
    followPalette();
  }

  function rememberShuffleEvery() {
    try {
      localStorage.setItem(SHUFFLE_EVERY_KEY, String(state.shuffleEvery));
    } catch {
      /* private mode */
    }
  }

  function seedPalette() {
    if (state.palette && THEMES[state.palette]) return;
    const shown = paletteName();
    state.palette = THEMES[shown] ? shown : "ion";
  }

  function shuffleColors(announce) {
    seedPalette();
    const next = nextPalette();
    state.palette = next;
    state.timedPalette = next;
    applyTheme();
    if (announce) toast(THEME_LABELS[next]);
  }

  function tickShuffle(now) {
    if (!timerOverrides() || !state.shuffleAt || now < state.shuffleAt) return;
    state.shuffleAt = now + state.shuffleEvery * 1000;
    shuffleColors(false);
  }

  function resize() {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.floor(innerWidth * dpr);
    canvas.height = Math.floor(innerHeight * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  addEventListener("resize", resize);
  resize();

  function fft(real, imag) {
    const n = real.length;
    let j = 0;
    for (let i = 0; i < n; i++) {
      if (i < j) {
        let tmp = real[i]; real[i] = real[j]; real[j] = tmp;
        tmp = imag[i]; imag[i] = imag[j]; imag[j] = tmp;
      }
      let m = n >> 1;
      while (m >= 1 && j >= m) {
        j -= m;
        m >>= 1;
      }
      j += m;
    }
    for (let size = 2; size <= n; size <<= 1) {
      const half = size >> 1;
      const step = (2 * Math.PI) / size;
      for (let i = 0; i < n; i += size) {
        for (let k = 0; k < half; k++) {
          const re = Math.cos(step * k);
          const im = -Math.sin(step * k);
          const evenR = real[i + k];
          const evenI = imag[i + k];
          const oddR = real[i + k + half];
          const oddI = imag[i + k + half];
          const tr = re * oddR - im * oddI;
          const ti = re * oddI + im * oddR;
          real[i + k] = evenR + tr;
          imag[i + k] = evenI + ti;
          real[i + k + half] = evenR - tr;
          imag[i + k + half] = evenI - ti;
        }
      }
    }
  }

  function pcmToBins(samples) {
    for (let i = 0; i < FFT_N; i++) {
      const s = i < samples.length ? samples[i] : 0;
      fftReal[i] = s * windowFn[i];
      fftImag[i] = 0;
    }
    fft(fftReal, fftImag);
    for (let i = 0; i < mag.length; i++) {
      const re = fftReal[i];
      const im = fftImag[i];
      mag[i] = Math.log10(1 + Math.sqrt(re * re + im * im) * state.gain * 8);
    }
    fillLogBins(mag);
    for (let i = 0; i < state.wave.length; i++) {
      const src = samples[(i * samples.length / state.wave.length) | 0] || 0;
      state.wave[i] = state.wave[i] * 0.7 + src * 0.3;
    }
  }

  function analyserToBins() {
    const a = state.analyser;
    if (!a) return;
    const spec = analyserToBins._spec || (analyserToBins._spec = new Uint8Array(a.frequencyBinCount));
    const td = analyserToBins._td || (analyserToBins._td = new Uint8Array(a.fftSize));
    a.getByteFrequencyData(spec);
    a.getByteTimeDomainData(td);
    for (let i = 0; i < mag.length && i < spec.length; i++) mag[i] = (spec[i] / 255) * state.gain;
    fillLogBins(mag);
    const step = Math.max(1, (td.length / state.wave.length) | 0);
    for (let i = 0; i < state.wave.length; i++) {
      state.wave[i] = (td[i * step] - 128) / 128;
    }
  }

  function fillLogBins(spectrum) {
    const n = state.bins.length;
    const maxIdx = Math.max(2, Math.min(spectrum.length - 1, spectrum.length * 0.72));
    for (let i = 0; i < n; i++) {
      const t0 = i / n;
      const t1 = (i + 1) / n;
      const i0 = Math.max(1, Math.floor(Math.pow(maxIdx, t0)));
      const i1 = Math.max(i0 + 1, Math.floor(Math.pow(maxIdx, t1)));
      let sum = 0;
      for (let k = i0; k < i1 && k < spectrum.length; k++) sum += spectrum[k];
      const v = Math.min(1, (sum / (i1 - i0)) * (0.55 + t0 * 0.9));
      const next = Math.max(v, state.bins[i] * 0.72 - 0.028);
      state.bins[i] = state.bins[i] * 0.45 + next * 0.55;
      state.peaks[i] = Math.max(state.bins[i], state.peaks[i] - 0.012);
    }
  }

  function energy() {
    let e = 0;
    for (let i = 0; i < 12; i++) e += state.bins[i];
    return e / 12;
  }

  // Integrate spin from smoothed speed. angle = time * liveSpeed jumps whenever the level changes.
  function advanceMotion() {
    const now = performance.now();
    const dt = state.motionLast ? Math.min(0.05, Math.max(0, (now - state.motionLast) / 1000)) : 0;
    state.motionLast = now;
    const bass = energy();
    let mid = 0;
    for (let i = 16; i < 48; i++) mid += state.bins[i];
    mid /= 32;
    const levelEase = 1 - Math.exp(-dt * 3.2);
    state.bassS += (bass - state.bassS) * levelEase;
    state.midS += (mid - state.midS) * levelEase;
    const binEase = 1 - Math.exp(-dt * 6);
    for (let i = 0; i < N_BARS; i++) {
      const prev = state.bins[i > 0 ? i - 1 : i];
      const next = state.bins[i + 1 < N_BARS ? i + 1 : i];
      const target = prev * 0.22 + state.bins[i] * 0.56 + next * 0.22;
      smoothBins[i] += (target - smoothBins[i]) * binEase;
    }
    const b = state.bassS;
    const m = state.midS;
    state.yaw += dt * (0.36 + b * 0.26);
    state.precess += dt * (0.95 + m * 0.35);
    state.rotor += dt * (1.1 + b * 0.5);
    state.helixSpin += dt * (0.62 + b * 0.32);
    state.spokeSpin += dt * (0.38 + b * 0.22);
  }

  function sampleSmooth(u) {
    const x = Math.max(0, Math.min(0.9999, u)) * (N_BARS - 1);
    const i = x | 0;
    const f = x - i;
    return smoothBins[i] * (1 - f) + smoothBins[Math.min(N_BARS - 1, i + 1)] * f;
  }

  function lerpPoint(pts, f) {
    const n = pts.length;
    let x = f % n;
    if (x < 0) x += n;
    const i = x | 0;
    const blend = x - i;
    const a = pts[i];
    const b = pts[(i + 1) % n];
    return {
      x: a.x + (b.x - a.x) * blend,
      y: a.y + (b.y - a.y) * blend,
      p: a.p + (b.p - a.p) * blend,
      bin: (a.bin || 0) + ((b.bin || 0) - (a.bin || 0)) * blend,
    };
  }

  function ensureParticles() {
    const count = isMobile ? 90 : 220;
    if (state.particles.length === count) return;
    state.particles = Array.from({ length: count }, () => ({
      a: Math.random() * Math.PI * 2,
      r: 40 + Math.random() * 220,
      s: 0.002 + Math.random() * 0.01,
      z: Math.random(),
    }));
  }

  function drawBars(w, h, mirror) {
    const n = state.bins.length;
    const mid = h * (mirror ? 0.5 : 0.78);
    const gap = 2;
    const bw = Math.max(2, (w - 80) / n - gap);
    const x0 = (w - n * (bw + gap)) / 2;
    const maxH = mirror ? h * 0.38 : h * 0.62;
    if (state.glow > 0.05) ctx.shadowBlur = 12 * state.glow;
    for (let i = 0; i < n; i++) {
      const v = state.bins[i];
      const bh = v * maxH;
      if (bh < 1) continue;
      const x = x0 + i * (bw + gap);
      ctx.fillStyle = themeColor(i / n);
      ctx.shadowColor = ctx.fillStyle;
      const rad = Math.min(6, bw / 2);
      roundRect(x, mid - bh, bw, bh, rad);
      if (mirror) roundRect(x, mid, bw, bh, rad);
      const ph = state.peaks[i] * maxH;
      if (ph > 2) {
        ctx.globalAlpha = 0.55;
        ctx.fillRect(x, mid - ph - 2, bw, 2);
        if (mirror) ctx.fillRect(x, mid + ph, bw, 2);
        ctx.globalAlpha = 1;
      }
    }
    ctx.shadowBlur = 0;
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.fill();
  }

  function drawRadial(w, h) {
    const cx = w / 2;
    const cy = h / 2;
    const n = state.bins.length;
    const inner = Math.min(w, h) * 0.16;
    const span = Math.min(w, h) * 0.34;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(performance.now() / 18000);
    if (state.glow > 0.05) ctx.shadowBlur = 16 * state.glow;
    for (let i = 0; i < n; i++) {
      const a0 = (i / n) * Math.PI * 2;
      const v = state.bins[i];
      ctx.strokeStyle = themeColor(i / n);
      ctx.shadowColor = ctx.strokeStyle;
      ctx.lineWidth = Math.max(2, (Math.PI * 2 * inner) / n * 0.7);
      ctx.beginPath();
      ctx.moveTo(Math.cos(a0) * inner, Math.sin(a0) * inner);
      const r = inner + v * span;
      ctx.lineTo(Math.cos(a0) * r, Math.sin(a0) * r);
      ctx.stroke();
    }
    ctx.restore();
    ctx.shadowBlur = 0;
    const bass = energy();
    ctx.beginPath();
    ctx.strokeStyle = themeStop(0);
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 2;
    ctx.arc(cx, cy, inner * (0.7 + bass * 0.5), 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  function drawWave(w, h) {
    const y = h * 0.5;
    const amp = h * 0.28;
    ctx.lineWidth = 2;
    ctx.strokeStyle = themeStop(0);
    if (state.glow > 0.05) {
      ctx.shadowBlur = 18 * state.glow;
      ctx.shadowColor = ctx.strokeStyle;
    }
    ctx.beginPath();
    for (let i = 0; i < state.wave.length; i++) {
      const x = (i / (state.wave.length - 1)) * w;
      const yy = y + state.wave[i] * amp * state.gain;
      if (i === 0) ctx.moveTo(x, yy);
      else ctx.lineTo(x, yy);
    }
    ctx.stroke();
    ctx.globalAlpha = 0.35;
    ctx.strokeStyle = themeStop(1);
    ctx.beginPath();
    for (let i = 0; i < state.wave.length; i++) {
      const x = (i / (state.wave.length - 1)) * w;
      const yy = y - state.wave[i] * amp * 0.55 * state.gain;
      if (i === 0) ctx.moveTo(x, yy);
      else ctx.lineTo(x, yy);
    }
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
  }

  function drawOrbit(w, h) {
    ensureParticles();
    const cx = w / 2;
    const cy = h / 2;
    const bass = energy();
    const t = performance.now();
    for (const p of state.particles) {
      const band = (p.z * (N_BARS - 1)) | 0;
      const v = state.bins[band];
      p.a += p.s * (0.6 + v * 3);
      const rr = p.r * (0.85 + bass * 0.5 + v * 0.4);
      const x = cx + Math.cos(p.a + t / 9000) * rr * (w / Math.min(w, h) * 0.55);
      const y = cy + Math.sin(p.a * 0.92) * rr * (h / Math.min(w, h) * 0.42);
      ctx.fillStyle = themeColor(p.z);
      ctx.globalAlpha = 0.25 + v * 0.75;
      const sz = 1.2 + v * 4;
      ctx.beginPath();
      ctx.arc(x, y, sz, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  // Radial spokes spinning inside three gimbal rings, with beads riding the rings.
  function drawGyro(w, h) {
    const cx = w / 2;
    const cy = h / 2;
    const base = Math.min(w, h) * 0.34;
    const t = performance.now() / 1000;
    const bass = state.bassS;
    const focal = base * 4.5;
    const yaw = state.yaw;
    const roll = Math.sin(t * 0.5) * 0.45;
    const precess = state.precess;
    const gimbals = [
      { r: base * (1.02 + bass * 0.05), ax: 0.42, ay: yaw, az: roll * 0.35, spin: yaw * 0.2, hue: 0.12 },
      { r: base * 0.74, ax: 1.05, ay: 0.35, az: precess, spin: 0, hue: 0.48 },
      { r: base * 0.46, ax: state.rotor, ay: 0.85, az: state.rotor * 0.37, spin: 0, hue: 0.86 },
    ];
    for (const g of gimbals) {
      g.cax = Math.cos(g.ax); g.sax = Math.sin(g.ax);
      g.cay = Math.cos(g.ay); g.say = Math.sin(g.ay);
      g.caz = Math.cos(g.az); g.saz = Math.sin(g.az);
    }

    function project(x, y, z, g) {
      let y1 = y * g.cax - z * g.sax;
      let z1 = y * g.sax + z * g.cax;
      y = y1; z = z1;
      const x1 = x * g.cay + z * g.say;
      z1 = -x * g.say + z * g.cay;
      x = x1; z = z1;
      const x2 = x * g.caz - y * g.saz;
      const y2 = x * g.saz + y * g.caz;
      const p = focal / (focal + z1);
      return { x: cx + x2 * p, y: cy + y2 * p, z: z1, p };
    }

    const SEGS = 84;
    const built = gimbals.map((g) => {
      const pts = new Array(SEGS);
      for (let i = 0; i < SEGS; i++) {
        const a = (i / SEGS) * Math.PI * 2 + g.spin;
        pts[i] = project(Math.cos(a) * g.r, Math.sin(a) * g.r, 0, g);
      }
      return { g, pts };
    });

    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    if (state.glow > 0.05) {
      ctx.shadowBlur = 20 * state.glow;
      for (const item of built) {
        ctx.strokeStyle = themeColor(item.g.hue);
        ctx.shadowColor = ctx.strokeStyle;
        ctx.globalAlpha = state.dim * 0.55;
        ctx.lineWidth = Math.max(1.6, base * 0.005);
        ctx.beginPath();
        ctx.moveTo(item.pts[0].x, item.pts[0].y);
        for (let i = 1; i < SEGS; i++) ctx.lineTo(item.pts[i].x, item.pts[i].y);
        ctx.closePath();
        ctx.stroke();
      }
      ctx.shadowBlur = 0;
    }

    const pieces = [];
    for (const item of built) {
      for (let i = 0; i < SEGS; i++) {
        const a = item.pts[i];
        const b = item.pts[(i + 1) % SEGS];
        pieces.push({ a, b, z: (a.z + b.z) / 2, hue: item.g.hue, r: item.g.r });
      }
    }
    pieces.sort((p, q) => q.z - p.z);
    const weight = Math.max(1.4, base * 0.0045);
    for (const s of pieces) {
      const near = Math.max(0, Math.min(1, 0.5 - s.z / (s.r * 2)));
      ctx.strokeStyle = themeColor(s.hue);
      ctx.globalAlpha = state.dim * (0.16 + near * 0.84);
      ctx.lineWidth = weight * (0.65 + near);
      ctx.beginPath();
      ctx.moveTo(s.a.x, s.a.y);
      ctx.lineTo(s.b.x, s.b.y);
      ctx.stroke();
    }

    const rotor = gimbals[2];
    const spokes = 72;
    const hub = Math.min(w, h) * 0.045;
    const reach = Math.min(w, h) * 0.2;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(state.spokeSpin);
    if (state.glow > 0.05) ctx.shadowBlur = 12 * state.glow;
    for (let i = 0; i < spokes; i++) {
      const v = sampleSmooth(i / spokes);
      const a = (i / spokes) * Math.PI * 2;
      const r1 = hub + 6 + v * reach;
      ctx.strokeStyle = themeColor(i / spokes);
      ctx.shadowColor = ctx.strokeStyle;
      ctx.globalAlpha = state.dim * (0.28 + v * 0.72);
      ctx.lineWidth = 1.5 + v * 2.4;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * hub, Math.sin(a) * hub);
      ctx.lineTo(Math.cos(a) * r1, Math.sin(a) * r1);
      ctx.stroke();
    }
    ctx.restore();
    ctx.shadowBlur = 0;

    for (const item of built) {
      const count = item.g === rotor ? 7 : 9;
      const speed = 8 + item.g.hue * 16;
      for (let k = 0; k < count; k++) {
        const p = lerpPoint(item.pts, k * SEGS / count + t * speed);
        const v = sampleSmooth(k / count);
        ctx.fillStyle = themeColor(item.g.hue);
        ctx.globalAlpha = state.dim * (0.4 + v * 0.6);
        ctx.beginPath();
        ctx.arc(p.x, p.y, (1.8 + v * 3.6) * p.p, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    ctx.globalAlpha = state.dim * (0.35 + bass * 0.55);
    ctx.strokeStyle = themeStop(0);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, hub * (0.85 + bass), 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  // Spectrum-thick double coil. Rungs between the strands are the radial half.
  function drawHelix(w, h) {
    const t = performance.now() / 1000;
    const bass = state.bassS;
    const cx = w / 2;
    const cy = h / 2;
    const portrait = h > w * 1.15;
    const span = portrait ? h * 0.72 : Math.min(w * 0.8, h * 1.4);
    const amp = Math.min(w, h) * (0.16 + bass * 0.04);
    const tilt = 0.7;
    const coils = portrait ? 5 : 4.2;
    const n = 260;
    const spin = state.helixSpin;
    const c = Math.cos(tilt);
    const s = Math.sin(tilt);
    const focal = Math.min(w, h) * 0.7;

    function strand(phase) {
      const pts = new Array(n);
      for (let i = 0; i < n; i++) {
        const u = i / (n - 1);
        const bin = sampleSmooth(u);
        const ang = u * coils * Math.PI * 2 + spin + phase;
        const rad = amp * (0.62 + bin * 0.7);
        const along = (u - 0.5) * span;
        const cyc = Math.cos(ang) * rad;
        const dep = Math.sin(ang) * rad;
        const across = cyc * c - dep * s;
        const z = cyc * s + dep * c;
        const p = focal / (focal + z);
        pts[i] = portrait
          ? { x: cx + across * p, y: cy + along, z, p, bin }
          : { x: cx + along, y: cy + across * p, z, p, bin };
      }
      return pts;
    }

    const a = strand(0);
    const b = strand(Math.PI);
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    const rungs = [];
    for (let i = 0; i < n; i += 8) {
      rungs.push({ i, z: (a[i].z + b[i].z) / 2 });
    }
    rungs.sort((p, q) => q.z - p.z);
    ctx.lineWidth = 1.3;
    for (const rung of rungs) {
      const i = rung.i;
      const v = Math.max(a[i].bin, b[i].bin);
      ctx.strokeStyle = themeColor(i / n);
      ctx.globalAlpha = state.dim * (0.12 + v * 0.62);
      ctx.beginPath();
      ctx.moveTo(a[i].x, a[i].y);
      ctx.lineTo(b[i].x, b[i].y);
      ctx.stroke();
    }

    function strokeStrand(pts, hue) {
      const parts = [];
      for (let i = 0; i < n - 1; i++) {
        parts.push({ a: pts[i], b: pts[i + 1], z: (pts[i].z + pts[i + 1].z) / 2 });
      }
      parts.sort((p, q) => q.z - p.z);
      const col = themeColor(hue);
      if (state.glow > 0.05) {
        ctx.shadowBlur = 16 * state.glow;
        ctx.shadowColor = col;
        ctx.strokeStyle = col;
        ctx.globalAlpha = state.dim * 0.45;
        ctx.lineWidth = 2.2;
        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        for (let i = 1; i < n; i++) ctx.lineTo(pts[i].x, pts[i].y);
        ctx.stroke();
        ctx.shadowBlur = 0;
      }
      ctx.strokeStyle = col;
      for (const seg of parts) {
        const near = Math.max(0, Math.min(1, 0.5 - seg.z / (amp * 2)));
        ctx.globalAlpha = state.dim * (0.28 + near * 0.72);
        ctx.lineWidth = 1.6 + near * 1.05;
        ctx.beginPath();
        ctx.moveTo(seg.a.x, seg.a.y);
        ctx.lineTo(seg.b.x, seg.b.y);
        ctx.stroke();
      }
    }

    strokeStrand(a, 0.18);
    strokeStrand(b, 0.78);

    for (let s = 0; s < 2; s++) {
      const pts = s === 0 ? a : b;
      const dir = s === 0 ? 1 : -1;
      for (let k = 0; k < 12; k++) {
        const p = lerpPoint(pts, k * n / 12 + t * 18 * dir);
        ctx.fillStyle = themeColor(s === 0 ? 0.18 : 0.78);
        ctx.globalAlpha = state.dim * (0.4 + p.bin * 0.6);
        ctx.beginPath();
        ctx.arc(p.x, p.y, (1.7 + p.bin * 3.4) * Math.max(0.4, p.p), 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.restore();
  }

  function drawAod(w, h) {
    const t = performance.now() / 1000;
    const driftX = Math.sin(t / 23) * Math.min(28, w * 0.04);
    const driftY = Math.cos(t / 19) * Math.min(22, h * 0.03);
    const cx = w / 2 + driftX;
    const cy = h / 2 + driftY + 8;
    const n = 48;
    const inner = Math.min(w, h) * 0.22;
    const bass = energy();
    ctx.save();
    ctx.translate(cx, cy);
    for (let i = 0; i < n; i++) {
      const src = state.bins[((i / n) * N_BARS) | 0];
      const a = (i / n) * Math.PI * 2 - Math.PI / 2;
      const len = 6 + src * Math.min(w, h) * 0.08;
      ctx.strokeStyle = themeColor(i / n);
      ctx.globalAlpha = 0.2 + src * 0.75;
      ctx.lineWidth = 2;
      ctx.beginPath();
      const r0 = inner;
      const r1 = inner + len;
      ctx.moveTo(Math.cos(a) * r0, Math.sin(a) * r0);
      ctx.lineTo(Math.cos(a) * r1, Math.sin(a) * r1);
      ctx.stroke();
    }
    ctx.globalAlpha = 0.45 + bass * 0.4;
    ctx.strokeStyle = themeStop(0);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(0, 0, inner * (0.86 + bass * 0.08), 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
    ctx.globalAlpha = 1;
    clockEl.style.transform = `translate(${driftX}px, ${driftY}px)`;
  }

  function drawFrame() {
    const w = innerWidth;
    const h = innerHeight;
    ctx.globalAlpha = 1;
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, w, h);
    ctx.globalAlpha = state.dim;

    if (state.analyser && (state.source === "mic" || state.source === "file")) analyserToBins();
    else if (state.pcmReady) {
      pcmToBins(state.pcm);
      state.pcmReady = false;
    } else {
      for (let i = 0; i < state.bins.length; i++) {
        state.bins[i] *= 0.94;
        state.peaks[i] = Math.max(state.bins[i], state.peaks[i] - 0.01);
      }
    }

    advanceMotion();
    tickShuffle(Date.now());
    presentColors(performance.now());

    if (state.style === "bars") drawBars(w, h, false);
    else if (state.style === "mirror") drawBars(w, h, true);
    else if (state.style === "radial") drawRadial(w, h);
    else if (state.style === "wave") drawWave(w, h);
    else if (state.style === "orbit") drawOrbit(w, h);
    else if (state.style === "gyro") drawGyro(w, h);
    else if (state.style === "helix") drawHelix(w, h);
    else drawAod(w, h);

    ctx.globalAlpha = 1;
    const now = Date.now();
    if (now - state.lastClock > 250) {
      updateClock();
      state.lastClock = now;
    }
    requestAnimationFrame(drawFrame);
  }

  function updateClock() {
    const d = new Date();
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    clockTime.textContent = `${hh}:${mm}`;
    clockDate.textContent = d.toLocaleDateString(undefined, {
      weekday: "long",
      month: "short",
      day: "numeric",
    });
  }

  function applyStyle() {
    const aod = state.style === "aod";
    document.body.classList.toggle("aod-mode", aod);
    clockEl.classList.toggle("hidden", !aod);
    if (aod) {
      document.body.classList.add("ui-hidden");
      requestWakeLock();
    }
  }

  async function requestWakeLock() {
    try {
      if (!("wakeLock" in navigator)) return;
      state.wakeLock = await navigator.wakeLock.request("screen");
      state.wakeLock.addEventListener("release", () => {
        if (state.style === "aod" && document.visibilityState === "visible") requestWakeLock();
      });
    } catch {
      /* battery saver / unsupported */
    }
  }

  async function ensureAudio() {
    if (state.audioCtx) return;
    state.audioCtx = new AudioContext();
    state.analyser = state.audioCtx.createAnalyser();
    state.analyser.fftSize = 2048;
    state.analyser.smoothingTimeConstant = 0.72;
    if (state.audioCtx.state === "suspended") await state.audioCtx.resume();
  }

  function stopMic() {
    if (state.micStream) {
      state.micStream.getTracks().forEach((t) => t.stop());
      state.micStream = null;
    }
    if (state.mediaSource) {
      try { state.mediaSource.disconnect(); } catch { /* already disconnected */ }
      state.mediaSource = null;
    }
  }

  function stopWs() {
    if (state.ws) {
      try { state.ws.close(); } catch { /* ignore */ }
      state.ws = null;
    }
  }

  function connectSystem() {
    stopWs();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/pcm`);
    ws.binaryType = "arraybuffer";
    state.ws = ws;
    ws.onopen = () => setStatus("System audio");
    ws.onclose = () => {
      if (state.source === "system" && state.running) {
        setStatus("Reconnecting…");
        setTimeout(connectSystem, 800);
      }
    };
    ws.onerror = () => setStatus("System audio unavailable");
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.error) setStatus(msg.error);
          else if (msg.device) setStatus("System · " + shortDevice(msg.device));
        } catch { /* ignore */ }
        return;
      }
      const src = new Float32Array(ev.data);
      const n = Math.min(FFT_N, src.length);
      state.pcm.set(src.subarray(0, n));
      state.pcmReady = true;
    };
  }

  function shortDevice(name) {
    return name
      .replace(/^alsa_(output|input)\./, "")
      .replace(/\.monitor$/, "")
      .replace(/_/g, " ")
      .slice(0, 48);
  }

  async function startMic() {
    await ensureAudio();
    stopMic();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    state.micStream = stream;
    state.mediaSource = state.audioCtx.createMediaStreamSource(stream);
    state.mediaSource.connect(state.analyser);
    setStatus("Microphone");
  }

  async function startFile(file) {
    await ensureAudio();
    stopMic();
    const url = URL.createObjectURL(file);
    fileAudio.src = url;
    fileAudio.onloadedmetadata = async () => {
      if (!state.mediaSource) {
        state.mediaSource = state.audioCtx.createMediaElementSource(fileAudio);
        state.mediaSource.connect(state.analyser);
        state.analyser.connect(state.audioCtx.destination);
      }
      await fileAudio.play();
      setStatus(file.name);
      if (state.theme === "shuffle" && !timerOverrides()) {
        state.palette = nextPalette();
        applyTheme();
        toast(THEME_LABELS[state.palette]);
      }
    };
  }

  async function start() {
    state.running = true;
    document.getElementById("btnStart").textContent = "Running";
    try {
      if (state.source === "system") {
        if (location.protocol === "file:") {
          setStatus("Open via Start script for system audio");
          toast("System audio needs the local server");
          return;
        }
        connectSystem();
      } else if (state.source === "mic") {
        await startMic();
      } else {
        filePick.click();
        return;
      }
    } catch (err) {
      setStatus("Permission denied");
      toast(String(err.message || err));
      return;
    }
    requestWakeLock();
    if (isMobile && state.style === "aod") state.lastUi = Date.now() - 4000;
  }

  document.getElementById("btnStart").addEventListener("click", start);

  document.getElementById("sourceSeg").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-source]");
    if (!btn) return;
    state.source = btn.dataset.source;
    setSeg("sourceSeg", "source", state.source);
    stopWs();
    stopMic();
    if (state.source === "file") {
      filePick.click();
      return;
    }
    if (state.running) start();
  });

  filePick.addEventListener("change", () => {
    const file = filePick.files && filePick.files[0];
    if (file) startFile(file);
  });

  document.getElementById("styleSeg").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-style]");
    if (!btn) return;
    state.style = btn.dataset.style;
    setSeg("styleSeg", "style", state.style);
    applyStyle();
    state.lastUi = Date.now();
    document.body.classList.remove("ui-hidden");
  });

  document.getElementById("themeSeg").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-theme]");
    if (!btn) return;
    state.theme = btn.dataset.theme;
    applyTheme();
    syncShuffle();
  });

  document.getElementById("shuffleEvery").addEventListener("change", (e) => {
    const seconds = Number(e.target.value);
    const next = SHUFFLE_PRESETS.includes(seconds) ? seconds : 0;
    const wasOn = timerOverrides();
    state.shuffleEvery = next;
    rememberShuffleEvery();
    if (next <= 0) {
      state.timedPalette = "";
      state.shuffleAt = 0;
      applyTheme();
      return;
    }
    state.shuffleAt = Date.now() + next * 1000;
    if (!wasOn) shuffleColors(true);
    else applyTheme();
  });
  applyTheme();

  async function syncShuffle() {
    if (timerOverrides()) return;
    if (state.theme !== "shuffle" || state.source !== "system") return;
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      const palette = data.track && data.track.palette;
      if (!palette || !THEMES[palette] || palette === state.palette) return;
      state.palette = palette;
      applyTheme();
      toast(THEME_LABELS[palette]);
    } catch {
      /* opened as a file, or the server is still starting */
    }
  }
  setInterval(syncShuffle, 1200);

  document.getElementById("gain").addEventListener("input", (e) => { state.gain = +e.target.value; });
  document.getElementById("glow").addEventListener("input", (e) => { state.glow = +e.target.value; });
  document.getElementById("dim").addEventListener("input", (e) => { state.dim = +e.target.value; });

  document.getElementById("btnFull").addEventListener("click", () => {
    if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
    else document.exitFullscreen().catch(() => {});
  });

  document.getElementById("btnHide").addEventListener("click", () => {
    document.body.classList.add("ui-hidden");
  });

  canvas.addEventListener("pointerdown", () => {
    document.body.classList.remove("ui-hidden");
    state.lastUi = Date.now();
  });
  document.getElementById("dock").addEventListener("pointerdown", () => {
    state.lastUi = Date.now();
  });

  setInterval(() => {
    if (state.style === "aod" && Date.now() - state.lastUi > 3500) {
      document.body.classList.add("ui-hidden");
    }
  }, 500);

  document.getElementById("copyUrl").addEventListener("click", async () => {
    const url = phoneUrlEl.textContent;
    try {
      await navigator.clipboard.writeText(url);
      toast("Copied");
    } catch {
      toast(url);
    }
  });

  addEventListener("keydown", (e) => {
    if (e.key === "f") document.getElementById("btnFull").click();
    if (e.key === "h") document.body.classList.toggle("ui-hidden");
    if (e.key === " ") {
      e.preventDefault();
      if (fileAudio.src) fileAudio.paused ? fileAudio.play() : fileAudio.pause();
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && state.style === "aod") requestWakeLock();
  });

  async function loadStatus() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      const lan = (data.urls && data.urls.lan) || [];
      const prefer = lan.find((u) => u.includes("192.168.")) || lan[0];
      if (prefer && !isMobile) {
        phoneUrlEl.textContent = prefer;
        connectEl.classList.remove("hidden");
      }
      if (data.device) hintEl.textContent =
        "Playing through: " + shortDevice(data.device) +
        ". Phone: open the URL, Add to Home screen, Always-On. True Samsung AOD cannot run this — this is the nightstand / keep-awake mode.";
    } catch {
      /* opened as a file */
    }
  }

  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    const swUrl = "sw.js?v=5";
    navigator.serviceWorker.register(swUrl).then(() => navigator.serviceWorker.getRegistrations()).then((regs) => {
      for (const reg of regs) {
        const worker = reg.active || reg.waiting || reg.installing;
        if (worker && !worker.scriptURL.includes(swUrl)) reg.unregister();
      }
    }).catch(() => {});
  }

  applyStyle();
  updateClock();
  loadStatus();
  requestAnimationFrame(drawFrame);
  if (location.protocol !== "file:") {
    start().catch(() => {});
  }
})();
