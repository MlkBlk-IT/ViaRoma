// Intro ViaRoma — you enter via a Roman street, you arrive in front of the Coliseum.
// 2D canvas, forward camera, central vanishing point.
// Sautable (clic / Echap / touche). Respecte prefers-reduced-motion.
(function () {
  'use strict';

  const BASE_DUR = 5200;      // duree totale (ms)
  const BASE_WALK = 3400;     // walking duration (ms)
  const BASE_FADE = 900;      // final fade duration
  const BASE_HOLD = 900;      // landing in front of the Coliseum

  // ?intro=long multiplies the duration (verification / screenshot).
  function params() {
    try { return new URLSearchParams(window.location.search); } catch (e) { return new URLSearchParams(); }
  }
  const P = params();
  const SCALE = P.get('intro') === 'long' ? 3 : (parseFloat(P.get('intro')) || 1);
  const DUR = BASE_DUR * SCALE;
  const WALK = BASE_WALK * SCALE;
  const FADE = BASE_FADE * SCALE;
  const HOLD = BASE_HOLD * SCALE;

  function start() {
    const overlay = document.getElementById('roma-intro');
    if (!overlay) return;
    const canvas = overlay.querySelector('canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) { overlay.remove(); return; }

    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) { overlay.remove(); return; }

    let w = 0, h = 0, dpr = 1, raf = 0, done = false, t0 = 0;

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth; h = window.innerHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();
    window.addEventListener('resize', resize);

    const horizon = () => h * 0.40;
    const eye = 1.55;

    // Projection 1 vanishing point: x lateral, y height, z depth.
    // Convention: y monte -> l'ecran monte (sy decroit).
    function proj(x, y, z, camZ, f) {
      const d = Math.max(z - camZ, 0.35);
      const s = f / d;
      return [w / 2 + x * s, horizon() - (y - eye) * s, s];
    }

    function cobbles(camZ, f) {
      // paving stones: transverse ground lines + radii
      ctx.lineWidth = 1;
      for (let z = 1; z < 120; z *= 1.16) {
        if (z - camZ < 0.6) continue;
        const [, sy] = proj(0, 0, z, camZ, f);
        if (sy < -50 || sy > h + 50) continue;
        const fade = Math.max(0, 1 - (z - camZ) / 60);
        ctx.strokeStyle = 'rgba(120,96,58,' + (0.34 * fade) + ')';
        ctx.beginPath();
        ctx.moveTo(0, sy);
        ctx.lineTo(w, sy);
        ctx.stroke();
      }
      // joints rayonnants
      for (let i = -9; i <= 9; i++) {
        if (i === 0) continue;
        const [, sy] = proj(i, 0, 1.2, camZ, f);
        ctx.strokeStyle = 'rgba(120,96,58,0.10)';
        ctx.beginPath();
        ctx.moveTo(w / 2, horizon());
        ctx.lineTo(w / 2 + i * f * 0.09, sy);
        ctx.stroke();
      }
    }

    function column(x, z, camZ, f, hcol) {
      const [sx, syBase] = proj(x, 0, z, camZ, f);
      const [, syTop] = proj(x, hcol, z, camZ, f);
      const wcol = Math.max(2, 0.30 * f / Math.max(z - camZ, 0.35));
      const depth = 0.5 + 0.5 * Math.cos(x * 1.2 + z * 0.3);
      // was
      const grad = ctx.createLinearGradient(sx - wcol, 0, sx + wcol, 0);
      grad.addColorStop(0, 'rgba(226,214,190,' + (0.55 + depth * 0.30) + ')');
      grad.addColorStop(0.45, 'rgba(250,244,230,' + (0.80 + depth * 0.18) + ')');
      grad.addColorStop(1, 'rgba(176,150,110,' + (0.50 + depth * 0.28) + ')');
      ctx.fillStyle = grad;
      ctx.fillRect(sx - wcol / 2, syTop, wcol, syBase - syTop);
      // chapiteau
      ctx.fillStyle = 'rgba(255,250,238,' + (0.70 + depth * 0.25) + ')';
      ctx.fillRect(sx - wcol * 0.78, syTop - wcol * 0.32, wcol * 1.56, wcol * 0.32);
      // base
      ctx.fillStyle = 'rgba(198,178,148,' + (0.55 + depth * 0.25) + ')';
      ctx.fillRect(sx - wcol * 0.68, syBase - wcol * 0.22, wcol * 1.36, wcol * 0.22);
      return { sx, syTop, syBase, wcol, depth };
    }

    function torch(x, y, z, camZ, f, phase) {
      const [sx, sy] = proj(x, y, z, camZ, f);
      const flick = 0.7 + 0.3 * Math.sin(phase);
      const r = Math.max(3, 26 * flick * f / Math.max(z - camZ, 0.35) * 0.05);
      const g = ctx.createRadialGradient(sx, sy, 0, sx, sy, r);
      g.addColorStop(0, 'rgba(255,214,130,0.85)');
      g.addColorStop(0.35, 'rgba(214,120,40,0.32)');
      g.addColorStop(1, 'rgba(214,120,40,0)');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(sx, sy, r, 0, Math.PI * 2);
      ctx.fill();
    }

    function banner(x, y, z, camZ, f, phase) {
      const [sx, sy] = proj(x, y, z, camZ, f);
      const bw = Math.max(4, 0.55 * f / Math.max(z - camZ, 0.35));
      const bh = bw * 1.7;
      const flap = Math.sin(phase) * bw * 0.10;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(sx + bw, sy + flap);
      ctx.lineTo(sx + bw, sy + bh + flap);
      ctx.lineTo(sx, sy + bh);
      ctx.closePath();
      ctx.fillStyle = 'rgba(158,36,48,0.72)';
      ctx.fill();
      ctx.fillStyle = 'rgba(216,175,96,0.65)';
      ctx.fillRect(sx + bw * 0.30, sy + bh * 0.22, bw * 0.40, bh * 0.20);
    }

    function coliseum(z, camZ, f) {
      // The Coliseum at the end of the street: ellipse silhouette with 3 floors.
      const R = 8.5, H = 6.6;
      const [cx, cyBase] = proj(0, 0, z, camZ, f);
      const [ , cyTop] = proj(0, H, z, camZ, f);
      const rr = R * f / Math.max(z - camZ, 0.35);
      const hh = cyBase - cyTop;
      if (rr < 2) return;
      const depth = Math.max(0, 1 - (z - camZ) / 70);
      ctx.save();
      ctx.globalAlpha = Math.min(1, 0.55 + depth * 0.45);
      // corps
      ctx.beginPath();
      ctx.ellipse(cx, cyBase - hh * 0.10, rr, hh * 0.46, 0, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(238,226,204,0.92)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(168,124,44,0.70)';
      ctx.lineWidth = Math.max(1, rr * 0.012);
      ctx.stroke();
      // etages d'arcs
      for (let t = 0; t < 3; t++) {
        const yy = cyBase - hh * (0.22 + t * 0.24);
        const rw = rr * (1 - t * 0.06);
        for (let i = 0; i < 26; i++) {
          const a = (i / 26) * Math.PI * 2;
          const x = cx + Math.cos(a) * rw;
          const yy2 = yy + Math.sin(a) * hh * 0.17;
          if (Math.sin(a) < -0.25) continue;   // face cachee
          // the breach: the upper floor has collapsed
          if (t === 2 && i > 3 && i < 11) continue;
          ctx.beginPath();
          ctx.ellipse(x, yy2, rr * 0.030, hh * 0.055, 0, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(107,39,55,' + (0.18 + 0.22 * (0.5 + 0.5 * Math.cos(a))) + ')';
          ctx.fill();
        }
      }
      // couronne
      ctx.beginPath();
      ctx.ellipse(cx, cyBase - hh * 0.74, rr * 0.70, hh * 0.16, 0, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,250,238,0.55)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(168,124,44,0.75)';
      ctx.stroke();
      // halo
      const g = ctx.createRadialGradient(cx, cyBase - hh * 0.4, 4, cx, cyBase - hh * 0.4, rr * 1.5);
      g.addColorStop(0, 'rgba(255,226,150,0.30)');
      g.addColorStop(1, 'rgba(255,226,150,0)');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(cx, cyBase - hh * 0.4, rr * 1.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    function draw(ts) {
      if (done) return;
      if (!t0) t0 = ts;
      const el = ts - t0;
      const t = Math.min(1, el / DUR);
      ctx.clearRect(0, 0, w, h);

      // evening sky
      const sky = ctx.createLinearGradient(0, 0, 0, h);
      sky.addColorStop(0, '#3b2130');
      sky.addColorStop(0.42, '#7d3a3f');
      sky.addColorStop(0.58, '#c98549');
      sky.addColorStop(1, '#e8c489');
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, w, h);

      // soleil bas
      const sunY = horizon() + h * 0.02;
      const sg = ctx.createRadialGradient(w / 2, sunY, 4, w / 2, sunY, h * 0.42);
      sg.addColorStop(0, 'rgba(255,238,190,0.85)');
      sg.addColorStop(0.18, 'rgba(255,190,110,0.35)');
      sg.addColorStop(1, 'rgba(255,150,80,0)');
      ctx.fillStyle = sg;
      ctx.fillRect(0, 0, w, h);

      // forward: camZ from -2 to 44 (the street, then the Colosseum)
      const walkT = Math.min(1, el / WALK);
      const eased = walkT < 0.5 ? 2 * walkT * walkT : 1 - Math.pow(-2 * walkT + 2, 2) / 2;
      const camZ = -2 + eased * 46;
      const f = Math.max(220, w * 0.30);

      // sol
      const grd = ctx.createLinearGradient(0, horizon(), 0, h);
      grd.addColorStop(0, 'rgba(120,96,62,0.55)');
      grd.addColorStop(1, 'rgba(70,54,36,0.85)');
      ctx.fillStyle = grd;
      ctx.fillRect(0, horizon(), w, h - horizon());
      cobbles(camZ, f);

      // the Coliseum in the background, visible bigger and bigger
      coliseum(48, camZ, f);

      // street columns, on both sides
      const colH = 3.4;
      for (let z = 4; z < 44; z += 3.4) {
        if (z - camZ < 1.2) continue;
        const l = column(-1.62, z, camZ, f, colH);
        const r = column(1.62, z, camZ, f, colH);
        // arch crossing the street
        const [ax, ay] = proj(0, colH, z, camZ, f);
        const wArc = Math.abs(l.sx - r.sx);
        ctx.beginPath();
        ctx.moveTo(l.sx, l.syTop);
        ctx.quadraticCurveTo(ax, ay - wArc * 0.42, r.sx, r.syTop);
        ctx.strokeStyle = 'rgba(236,222,196,0.55)';
        ctx.lineWidth = Math.max(2, wArc * 0.035);
        ctx.stroke();
        // torches et bannieres
        torch(-1.22, 2.1, z - 0.2, camZ, f, ts * 0.01 + z);
        torch(1.22, 2.1, z - 0.2, camZ, f, ts * 0.01 + z + 1.7);
        if (Math.round(z) % 2 === 0) banner(-0.78, colH - 0.15, z, camZ, f, ts * 0.003 + z);
      }

      // vignette
      const vg = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.28, w / 2, h / 2, Math.max(w, h) * 0.78);
      vg.addColorStop(0, 'rgba(0,0,0,0)');
      vg.addColorStop(1, 'rgba(20,10,16,0.55)');
      ctx.fillStyle = vg;
      ctx.fillRect(0, 0, w, h);

      // titre
      const titleT = Math.max(0, Math.min(1, (el - WALK * 0.62) / 700));
      const titleEase = 1 - Math.pow(1 - titleT, 3);
      if (titleT > 0) {
        ctx.save();
        ctx.globalAlpha = titleEase;
        ctx.textAlign = 'center';
        ctx.font = '700 ' + Math.round(Math.min(w * 0.12, 86)) + "px 'Segoe UI',system-ui,sans-serif";
        ctx.fillStyle = 'rgba(255,247,228,0.96)';
        ctx.shadowColor = 'rgba(0,0,0,0.45)';
        ctx.shadowBlur = 24;
        ctx.letterSpacing = '14px';
        ctx.fillText('VIAROMA', w / 2, horizon() - h * 0.04 + (1 - titleEase) * 26);
        ctx.letterSpacing = '4px';
        ctx.font = '400 ' + Math.round(Math.min(w * 0.028, 20)) + "px 'Segoe UI',system-ui,sans-serif";
        ctx.fillStyle = 'rgba(255,232,190,0.90)';
        ctx.fillText('FREE FRONTIER ROUTER · ROMA AETERNA', w / 2, horizon() + h * 0.02);
        ctx.restore();
      }

      // final fade to dashboard
      const fadeT = Math.max(0, Math.min(1, (el - (DUR - FADE)) / FADE));
      if (fadeT > 0) {
        ctx.fillStyle = 'rgba(251,247,238,' + fadeT + ')';
        ctx.fillRect(0, 0, w, h);
      }
      overlay.style.opacity = String(1 - fadeT);

      if (el >= DUR) { finish(); return; }
      raf = requestAnimationFrame(draw);
    }

    function finish() {
      if (done) return;
      done = true;
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      overlay.classList.add('gone');
      setTimeout(() => overlay.remove(), 700);
      document.body.classList.add('intro-done');
    }

    const skip = (e) => { if (e) e.preventDefault(); finish(); };
    overlay.addEventListener('click', skip);
    window.addEventListener('keydown', skip, { once: true });
    const skipBtn = overlay.querySelector('[data-intro-skip]');
    if (skipBtn) skipBtn.addEventListener('click', skip);

    raf = requestAnimationFrame(draw);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
