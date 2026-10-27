// ViaRoma Colisee — point d'entree unique.
//
// Le rendu 3D cinematique vit dans colosseum3d.js (Three.js + modele GLB
// reel). Ce fichier le charge et garantit un repli: si WebGL, three.js ou
// le GLB sont indisponibles, on dessine un Colisee 2D sobre plutot qu'un
// canvas vide.
(function () {
  'use strict';

  const SRC = '/dashboard/static/colosseum3d.js';
  let loaded = false;

  function fallback2D(canvas) {
    // Projection pinhole legere sur un cylindre elliptique: suffisament
    // lisible pour un header, et 100% local.
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    let raf = 0, t0 = Date.now();

    function draw() {
      raf = requestAnimationFrame(draw);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = canvas.clientWidth || 300, h = canvas.clientHeight || 160;
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr; canvas.height = h * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const cx = w / 2, cy = h * 0.66, rx = w * 0.42, ry = h * 0.16;
      const a = (Date.now() - t0) / 9000;

      // gradations
      for (let tier = 0; tier < 3; tier++) {
        const y = cy - tier * h * 0.20;
        const rr = rx * (1 - tier * 0.11);
        const yy = ry * (1 - tier * 0.16);
        ctx.fillStyle = tier === 0 ? '#e6d5b3' : (tier === 1 ? '#dcc7a0' : '#cdb488');
        ctx.beginPath();
        ctx.ellipse(cx, y, rr, yy, 0, Math.PI, Math.PI * 2);
        ctx.fill();
        // arcades
        const n = 26;
        for (let i = 0; i < n; i++) {
          const th = a * 0.25 + (i / n) * Math.PI * 2;
          const px = cx + Math.cos(th) * rr;
          const py = y - Math.abs(Math.sin(th)) * yy * 0.55;
          const depth = 0.35 + 0.65 * Math.abs(Math.sin(th));
          ctx.fillStyle = 'rgba(107,39,55,' + (0.16 + 0.26 * (1 - depth)) + ')';
          ctx.fillRect(px - w * 0.008, py - h * 0.10, w * 0.016, h * 0.10);
        }
      }
      // sol
      ctx.fillStyle = 'rgba(168,124,44,.16)';
      ctx.beginPath();
      ctx.ellipse(cx, cy + h * 0.02, rx * 1.06, ry * 1.1, 0, 0, Math.PI * 2);
      ctx.fill();
    }
    draw();
    return { dispose() { cancelAnimationFrame(raf); } };
  }

  function mountAll(opts) {
    const out = [];
    document.querySelectorAll('canvas.colosseum').forEach((c) => {
      if (c.__colosseum) return;
      const inst = window.ViaRomaColosseum.create(c, opts);
      if (inst) { c.__colosseum = inst; out.push(inst); }
    });
    return out;
  }

  function install3D() {
    if (loaded) return;
    loaded = true;
    const s = document.createElement('script');
    s.src = SRC + '?v=12';
    s.async = false;
    s.onerror = () => { console.warn('[colosseum] colosseum3d.js introuvable — repli 2D'); };
    document.head.appendChild(s);
  }

  // Attend le 3D, puis bascule. Si le 3D n'est pas pret (WebGL absent ou
  // echec de chargement), on installe le repli 2D.
  function ensure() {
    install3D();
    const deadline = Date.now() + 6000;
    const poll = setInterval(() => {
      if (window.ViaRomaColosseum && window.ViaRomaColosseum.create) {
        clearInterval(poll);
        return;
      }
      if (Date.now() > deadline) {
        clearInterval(poll);
        document.querySelectorAll('canvas.colosseum, canvas.colosseum-hero').forEach((c) => {
          if (c.__colosseum) return;
          const inst = fallback2D(c);
          if (inst) c.__colosseum = inst;
        });
      }
    }, 120);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ensure);
  } else {
    ensure();
  }
})();
