// ViaRoma Spoof — “IP spoofing” animation: the identity enters a Roman arch
// and comes out transformed. The real IP is NEVER displayed: it is
// hidden from the foreground. Rome palette: white + bright red.
(function () {
  'use strict';

  const PERIOD = 4200;       // slower cycle: we must not pluck the eye
  const WHITE = '#ffffff';
  const RED = '#C1121F';
  const DEEP = '#5E0B14';
  const CREAM = '#F6EEDF';

  function create(canvas, opts) {
    opts = opts || {};
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;

    const state = {
      running: true,
      t0: null,
      dpr: 1, w: 0, h: 0,
      egressIp: opts.egressIp || '—',
      country: opts.country || '',
      tls: opts.tls || 'chrome120',
      ja3: opts.ja3 || '—',
      account: opts.account || '',
      motes: []
    };

    // 14 deterministic words: no Math.random (flickering must be stable)
    for (let i = 0; i < 14; i++) {
      state.motes.push({ off: i / 14, sp: 0.9 + (i % 3) * 0.04, y: (i % 5) / 5 });
    }

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rect = canvas.getBoundingClientRect();
      const w = Math.max(240, rect.width || 480);
      const h = Math.max(160, rect.height || 220);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      state.w = w; state.h = h; state.dpr = dpr;
    }

    function roundRect(x, y, w, h, r) {
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.arcTo(x + w, y, x + w, y + h, r);
      ctx.arcTo(x + w, y + h, x, y + h, r);
      ctx.arcTo(x, y + h, x, y, r);
      ctx.arcTo(x, y, x + w, y, r);
      ctx.closePath();
    }

    function archPath(x, y, aw, ah) {
      const r = aw / 2;
      ctx.beginPath();
      ctx.moveTo(x, y + ah);
      ctx.lineTo(x, y + r);
      ctx.arc(x + r, y + r, r, Math.PI, 0);
      ctx.lineTo(x + aw, y + ah);
      ctx.closePath();
    }

    function masked(x, y, alpha) {
      // Real IP: only blocks. The value is never written.
      ctx.textAlign = 'center';
      ctx.font = '700 14px "Consolas",monospace';
      const chars = 11, cw = 8.2;
      const start = x - (chars * cw) / 2;
      for (let i = 0; i < chars; i++) {
        const ch = (i === 2 || i === 5 || i === 8) ? '.' : '█';
        ctx.fillStyle = ch === '.' ? 'rgba(193,18,31,' + alpha + ')' : 'rgba(193,18,31,' + (alpha * 0.85) + ')';
        ctx.fillText(ch, start + i * cw + cw / 2, y);
      }
    }

    function draw(ts) {
      if (!state.running) return;
      if (state.t0 === null) state.t0 = ts;
      const w = state.w, h = state.h;
      if (!w || !h) { requestAnimationFrame(draw); return; }
      const t = ((ts - state.t0) % PERIOD) / PERIOD;
      ctx.clearRect(0, 0, w, h);

      // fond: pourpre tyrien vers rouge
      const bg = ctx.createLinearGradient(0, 0, 0, h);
      bg.addColorStop(0, DEEP);
      bg.addColorStop(0.55, '#7A0F1C');
      bg.addColorStop(1, RED);
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, w, h);

      const railY = h * 0.45;
      const archW = Math.min(w * 0.24, 180);
      const archH = h * 0.54;
      const archX = w / 2 - archW / 2;
      const archY = railY - archH * 0.80;

      // --- the Roman arch (the transformation) ---
      archPath(archX, archY, archW, archH);
      ctx.fillStyle = 'rgba(30,8,12,0.55)';
      ctx.fill();
      ctx.strokeStyle = CREAM;
      ctx.lineWidth = 2.4;
      ctx.stroke();
      // claveaux
      ctx.strokeStyle = 'rgba(246,238,223,0.22)';
      ctx.lineWidth = 1;
      for (let i = 1; i < 5; i++) {
        const a = Math.PI + (i / 5) * Math.PI;
        const r = archW / 2;
        ctx.beginPath();
        ctx.moveTo(w / 2 + Math.cos(a) * r, archY + archW / 2 + Math.sin(a) * r);
        ctx.lineTo(w / 2, archY + archW / 2);
        ctx.stroke();
      }
      // soft glow, single slow pulsation
      const pulse = 0.5 + 0.5 * Math.sin(t * Math.PI * 2);
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      const gl = ctx.createRadialGradient(w / 2, railY, 2, w / 2, railY, archW * 0.72);
      gl.addColorStop(0, 'rgba(255,255,255,' + (0.05 + pulse * 0.07) + ')');
      gl.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = gl;
      ctx.fillRect(archX - 10, archY - 10, archW + 20, archH + 20);
      ctx.restore();

      // --- entry node: real IP hidden (white background) ---
      const nw = Math.min(w * 0.25, 158), nh = 68;
      const inX = Math.max(8, w * 0.03);
      const inY = railY - nh * 0.55;
      roundRect(inX, inY, nw, nh, 8);
      ctx.fillStyle = CREAM;
      ctx.fill();
      ctx.strokeStyle = WHITE;
      ctx.lineWidth = 1.4;
      ctx.stroke();
      ctx.textAlign = 'center';
      ctx.font = '700 10px "Segoe UI",system-ui,sans-serif';
      ctx.fillStyle = RED;
      ctx.fillText('REAL IP', inX + nw / 2, inY + 16);
      masked(inX + nw / 2, inY + 38, 0.95);
      ctx.font = '400 9px "Segoe UI",system-ui,sans-serif';
      ctx.fillStyle = 'rgba(94,11,20,0.85)';
      ctx.fillText('never transmitted', inX + nw / 2, inY + 58);

      // --- exit node: exit IP (red background) ---
      const outX = w - Math.max(8, w * 0.03) - nw;
      roundRect(outX, inY, nw, nh, 8);
      ctx.fillStyle = RED;
      ctx.fill();
      ctx.strokeStyle = CREAM;
      ctx.lineWidth = 1.6;
      ctx.stroke();
      ctx.textAlign = 'center';
      ctx.font = '700 10px "Segoe UI",system-ui,sans-serif';
      ctx.fillStyle = 'rgba(255,255,255,0.92)';
      ctx.fillText('OUTPUT IP', outX + nw / 2, inY + 16);
      ctx.font = '700 15px "Consolas",monospace';
      ctx.fillStyle = WHITE;
      ctx.fillText(state.egressIp, outX + nw / 2, inY + 38);
      ctx.font = '400 9px "Segoe UI",system-ui,sans-serif';
      ctx.fillStyle = 'rgba(255,255,255,0.80)';
      ctx.fillText((state.country ? state.country + ' · ' : '') + (state.account || 'lane'), outX + nw / 2, inY + 58);

      // --- rail ---
      const x0 = inX + nw, x1 = outX;
      ctx.strokeStyle = 'rgba(255,255,255,0.30)';
      ctx.lineWidth = 1.2;
      ctx.setLineDash([5, 6]);
      ctx.beginPath();
      ctx.moveTo(x0, railY);
      ctx.lineTo(x1, railY);
      ctx.stroke();
      ctx.setLineDash([]);

      // --- motes: 14, lentes, trajectoires deterministes ---
      for (const m of state.motes) {
        const p = (t * m.sp + m.off) % 1;
        let x, y, scrambled = false;
        if (p < 0.32) {
          x = x0 + (w / 2 - archW / 2 - x0) * (p / 0.32);
          y = railY;
        } else if (p < 0.64) {
          // in the arc: the data scrambles, on a fixed trajectory
          x = w / 2 + Math.sin(p * 22) * archW * 0.24;
          y = railY + Math.cos(p * 15) * archH * 0.16;
          scrambled = true;
        } else {
          x = (w / 2 + archW / 2) + (x1 - (w / 2 + archW / 2)) * ((p - 0.64) / 0.36);
          y = railY;
        }
        ctx.fillStyle = scrambled ? 'rgba(255,255,255,' + (0.55 + 0.35 * pulse) + ')' : 'rgba(246,238,223,0.85)';
        ctx.beginPath();
        ctx.arc(x, y, scrambled ? 3.2 : 2.4, 0, Math.PI * 2);
        ctx.fill();
      }

      // --- TLS fingerprint rail ---
      const fy = h * 0.80;
      ctx.textAlign = 'left';
      ctx.font = '700 10px "Segoe UI",system-ui,sans-serif';
      ctx.fillStyle = 'rgba(255,255,255,0.85)';
      ctx.fillText('TLS / BROWSER FINGERPRINT', 16, fy - 14);
      const fx0 = 16, fx1 = w - 16;
      ctx.strokeStyle = 'rgba(255,255,255,0.35)';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(fx0, fy + 2); ctx.lineTo(fx1, fy + 2); ctx.stroke();
      const ft = t;
      const mid = (fx0 + fx1) / 2;
      ctx.font = '700 11px "Consolas",monospace';
      ctx.fillStyle = 'rgba(255,255,255,0.92)';
      ctx.fillText('chrome120 / fr-CA', fx0, fy + 20);
      ctx.textAlign = 'right';
      ctx.fillText(state.tls + ' / ' + (state.ja3 || 'ja3'), fx1, fy + 20);
      const cx = fx0 + (fx1 - fx0) * (ft < 0.5 ? ft * 2 : (1 - ft) * 2);
      const inArc = Math.abs(cx - mid) < (fx1 - fx0) * 0.12;
      ctx.beginPath();
      ctx.arc(cx, fy + 2, inArc ? 6.5 : 4.2, 0, Math.PI * 2);
      ctx.fillStyle = inArc ? WHITE : 'rgba(246,238,223,0.9)';
      ctx.fill();

      // --- mention fail-closed ---
      ctx.textAlign = 'center';
      ctx.font = '600 9px "Segoe UI",system-ui,sans-serif';
      ctx.fillStyle = 'rgba(255,255,255,0.72)';
      ctx.fillText('fail-closed: without an output proxy, the request does not go out at all', w / 2, h - 8);

      requestAnimationFrame(draw);
    }

    resize();
    window.addEventListener('resize', resize);
    const onVis = () => {
      state.running = !document.hidden;
      if (state.running) requestAnimationFrame(draw);
    };
    document.addEventListener('visibilitychange', onVis);
    requestAnimationFrame((ts) => { state.t0 = ts; draw(ts); });

    return {
      canvas,
      setData(d) { Object.assign(state, d || {}); },
      destroy() {
        state.running = false;
        window.removeEventListener('resize', resize);
        document.removeEventListener('visibilitychange', onVis);
      }
    };
  }

  window.ViaRomaSpoof = {
    create,
    mount(el, opts) {
      if (!el) return null;
      if (el.__spoof) return el.__spoof;
      const inst = create(el, opts);
      if (inst) el.__spoof = inst;
      return inst;
    }
  };
})();
