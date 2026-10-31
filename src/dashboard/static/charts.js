/* ViaRoma — Canvas 2D charts. Roma Aeterna.
   Palette: or romain, pourpre tyrien, travertin, laurier, terre cuite.
   No external dependencies. */

/* ── Palette of the Empire ───────────────────── ────────────────────── */
const ROMA = {
  gold:     '#c69b4a',   // or romain
  goldHi:   '#e8cd8a',
  goldDk:   '#8f6a26',
  leaf:     '#8f9b52',   // laurier
  leafDk:   '#5f6b34',
  tyrian:   '#6b2737',   // pourpre tyrien
  tyrianLt: '#9c3a4e',
  trav:     '#fbf7ee',   // travertin
  travDk:   '#e8dcc8',
  marble:   '#d8cdb8',
  terra:    '#b85c38',   // terre cuite
  ink:      '#3a2a1a',
};

const Charts = {
  _dpi() { return Math.min(window.devicePixelRatio || 1, 2); },

  _ctx(id) {
    const c = document.getElementById(id);
    if (!c) return null;
    const dpr = this._dpi();
    const r = c.getBoundingClientRect();
    // Canvas mask (right panel in display:none) => rect 0x0. We come out here:
    // this is the source of the negative ray which broke the entire panel.
    if (!(r.width > 0) || !(r.height > 0)) return null;
    c.width  = Math.round(r.width  * dpr);
    c.height = Math.round(r.height * dpr);
    const ctx = c.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w: r.width, h: r.height };
  },

  /* Laurel wreath: two branches of foliage around the ring.
     The leaves point inwards, like on a real crown. */
  _laurel(ctx, cx, cy, radius, n, spread) {
    for (let i = 0; i < n; i++) {
      const t = (i / (n - 1)) * spread;
      const side = (i % 2 === 0) ? 1 : -1;
      // slightly variable radius: the crown is not perfectly regular
      const rr = radius * (0.955 + (i % 3) * 0.022);
      const x = cx + Math.cos(t) * rr;
      const y = cy + Math.sin(t) * rr;
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(t + side * 0.70);   // points towards the center
      ctx.beginPath();
      ctx.ellipse(0, 0, radius * 0.155, radius * 0.042, 0, 0, Math.PI * 2);
      const g = ctx.createLinearGradient(0, -radius * 0.045, 0, radius * 0.045);
      g.addColorStop(0, ROMA.leaf);
      g.addColorStop(1, ROMA.leafDk);
      ctx.fillStyle = g;
      ctx.fill();
      ctx.strokeStyle = 'rgba(58,42,26,.25)';
      ctx.lineWidth = 0.6;
      ctx.stroke();
      ctx.restore();
    }
  },

  /* ── Medaillon: anneau dePourpre + laurier + centre en travertin ── */
  donut(id, segments, opts = {}) {
    const cv = this._ctx(id); if (!cv) return;
    const { ctx, w, h } = cv;
    const cx = w / 2, cy = h / 2;
    const R = Math.min(w, h) / 2 - 3;
    if (!(R > 0)) return;

    const total = segments.reduce((s, x) => s + (x.val || 0), 0) || 1;
    const rOut = R * 0.78, rIn = R * 0.50;

    ctx.clearRect(0, 0, w, h);

    // Background medallion (travertine, gold glow in the center)
    const bg = ctx.createRadialGradient(cx - R * 0.25, cy - R * 0.3, R * 0.05, cx, cy, rIn);
    bg.addColorStop(0, '#fffdf7');
    bg.addColorStop(1, ROMA.travDk);
    ctx.beginPath(); ctx.arc(cx, cy, rIn - 0.5, 0, Math.PI * 2);
    ctx.fillStyle = bg; ctx.fill();

    // Laurel wreath (two branches, space at top)
    const laurelR = R * 0.92;
    this._laurel(ctx, cx, cy, laurelR, 26, Math.PI * 1.82);

    // Data Ring
    const gap = 0.014;
    let a = -Math.PI / 2;
    segments.forEach(seg => {
      const span = ((seg.val || 0) / total) * Math.PI * 2;
      if (span <= 0) return;
      const g = ctx.createLinearGradient(cx - rOut, cy - rOut, cx + rOut, cy + rOut);
      g.addColorStop(0, seg.color || ROMA.gold);
      g.addColorStop(0.5, seg.colorHi || ROMA.goldHi);
      g.addColorStop(1, seg.colorDark || ROMA.goldDk);
      ctx.beginPath();
      ctx.arc(cx, cy, rOut, a + gap, a + span - gap);
      ctx.arc(cx, cy, rIn, a + span - gap, a + gap, true);
      ctx.closePath();
      ctx.fillStyle = g; ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,.8)';
      ctx.lineWidth = 1.2; ctx.stroke();
      a += span;
    });

    // Gold thread between the ring and the medallion
    ctx.beginPath(); ctx.arc(cx, cy, rIn - 0.5, 0, Math.PI * 2);
    ctx.strokeStyle = ROMA.goldDk; ctx.lineWidth = 2; ctx.stroke();
    ctx.beginPath(); ctx.arc(cx, cy, rIn - 3.5, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(198,155,74,.45)'; ctx.lineWidth = 1; ctx.stroke();

    // Number in the center, in Tyrian purple
    const pct = opts.pct !== undefined ? opts.pct + '%' : '';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = ROMA.tyrian;
    ctx.font = 'bold ' + Math.max(10, Math.floor(R * 0.40)) + 'px "Segoe UI", Georgia, serif';
    ctx.fillText(pct, cx, cy - R * 0.04);
    // petit souplement or
    ctx.beginPath();
    ctx.moveTo(cx - R * 0.22, cy + R * 0.19);
    ctx.lineTo(cx + R * 0.22, cy + R * 0.19);
    ctx.strokeStyle = ROMA.gold; ctx.lineWidth = 1.4; ctx.stroke();
    ctx.fillStyle = ROMA.goldDk;
    ctx.font = Math.max(7, Math.floor(R * 0.13)) + 'px "Segoe UI", Georgia, serif';
    ctx.fillText(String(opts.label || '').toUpperCase(), cx, cy + R * 0.31);
  },

  /* ── Roman columns: base, fluted shaft, capital ──────────── */
  bar3d(id, bars, opts = {}) {
    const cv = this._ctx(id); if (!cv) return;
    const { ctx, w, h } = cv;
    ctx.clearRect(0, 0, w, h);
    if (!bars.length) {
      ctx.fillStyle = ROMA.ink; ctx.font = '11px "Segoe UI", Georgia, serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('No data', w / 2, h / 2);
      return;
    }

    const padL = 66, padR = 14, padT = 20, padB = 30;
    const slot = (w - padL - padR) / bars.length;
    const maxVal = Math.max(...bars.map(b => b.val), 1);
    const colW = Math.max(6, Math.min(32, slot * 0.5));

    // mosaic floor
    ctx.fillStyle = 'rgba(216,205,184,.35)';
    ctx.fillRect(0, h - padB + 6, w, padB - 6);

    bars.forEach((bar, i) => {
      const x = padL + i * slot + (slot - colW) / 2;
      const colH = Math.max(5, (bar.val / maxVal) * (h - padT - padB));
      const y = h - padB - colH;

      // ombre portee
      ctx.fillStyle = 'rgba(58,42,26,.10)';
      ctx.fillRect(x + 3, y + 2, colW, colH);

      // barrel: travertine grade
      const g = ctx.createLinearGradient(x, 0, x + colW, 0);
      g.addColorStop(0,    bar.colorDk || ROMA.marble);
      g.addColorStop(0.42, bar.colorHi || ROMA.trav);
      g.addColorStop(1,    bar.color || ROMA.travDk);
      ctx.fillStyle = g;
      ctx.fillRect(x, y, colW, colH);

      // cannelures
      ctx.strokeStyle = 'rgba(58,42,26,.16)';
      ctx.lineWidth = 1;
      for (let f = 1; f < 4; f++) {
        const fx = Math.round(x + (colW * f) / 4) + 0.5;
        ctx.beginPath(); ctx.moveTo(fx, y + 3); ctx.lineTo(fx, h - padB); ctx.stroke();
      }

      // chapiteau (abaque + echine)
      ctx.beginPath();
      ctx.moveTo(x - 2, y); ctx.lineTo(x + colW + 2, y);
      ctx.lineTo(x + colW - 3, y - 7); ctx.lineTo(x + 3, y - 7);
      ctx.closePath();
      const cg = ctx.createLinearGradient(x, y - 8, x + colW, y);
      cg.addColorStop(0, ROMA.goldHi); cg.addColorStop(1, ROMA.goldDk);
      ctx.fillStyle = cg; ctx.fill();
      ctx.fillStyle = ROMA.gold;
      ctx.fillRect(x - 4, y - 10, colW + 8, 3);

      // socle (plinthe + base mouluree)
      ctx.fillStyle = ROMA.travDk;
      ctx.fillRect(x - 3, h - padB, colW + 6, 4);
      ctx.fillStyle = ROMA.marble;
      ctx.fillRect(x - 5, h - padB + 4, colW + 10, 5);

      // label, inclined, anchored to ITS column so as not to pile up
      ctx.save();
      ctx.translate(x - 2, h - padB + 3);
      ctx.rotate(-Math.PI / 5);
      ctx.fillStyle = ROMA.ink;
      ctx.font = '10px "Segoe UI", Georgia, serif';
      ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      ctx.fillText(String(bar.label || '').slice(0, 12), 0, 0);
      ctx.restore();

      // value, on the marquee
      ctx.fillStyle = ROMA.tyrian;
      ctx.font = 'bold 10px "Segoe UI", Georgia, serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
      ctx.fillText(String(bar.val), x + colW / 2, y - 13);
    });
  },

  /* ── Aqueduct: the curve rests on a stone arcade ─────────── */
  line(id, points, opts = {}) {
    const cv = this._ctx(id); if (!cv) return;
    const { ctx, w, h } = cv;
    ctx.clearRect(0, 0, w, h);
    if (!points.length) {
      ctx.fillStyle = ROMA.ink; ctx.font = '11px "Segoe UI", Georgia, serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('No data', w / 2, h / 2);
      return;
    }

    const pad = 10;
    const maxVal = Math.max(...points, 1);
    const stepX = (w - pad * 2) / Math.max(points.length - 1, 1);
    const base = h - pad;
    const P = points.map((p, i) => ({
      x: pad + i * stepX,
      y: base - (p / maxVal) * (h - pad * 2),
    }));

    // arches under the curve
    for (let i = 0; i < P.length - 1; i++) {
      const a = P[i], b = P[i + 1];
      const midY = Math.min(a.y, b.y);
      ctx.beginPath();
      ctx.moveTo(a.x, base);
      ctx.lineTo(a.x, a.y);
      ctx.quadraticCurveTo((a.x + b.x) / 2, midY - (a.x === b.x ? 0 : 4), b.x, b.y);
      ctx.lineTo(b.x, base);
      ctx.closePath();
      const ag = ctx.createLinearGradient(0, midY, 0, base);
      ag.addColorStop(0, 'rgba(216,205,184,.55)');
      ag.addColorStop(1, 'rgba(251,247,238,.15)');
      ctx.fillStyle = ag; ctx.fill();
      ctx.strokeStyle = 'rgba(143,106,38,.28)';
      ctx.lineWidth = 1; ctx.stroke();
    }

    // rampart of the line
    ctx.beginPath();
    ctx.moveTo(pad, base);
    P.forEach(p => ctx.lineTo(p.x, p.y));
    ctx.lineTo(pad + (points.length - 1) * stepX, base);
    ctx.closePath();
    const fg = ctx.createLinearGradient(0, 0, 0, h);
    fg.addColorStop(0, 'rgba(198,155,74,.40)');
    fg.addColorStop(1, 'rgba(198,155,74,.03)');
    ctx.fillStyle = fg; ctx.fill();

    // courbe d'or
    ctx.beginPath();
    P.forEach((p, i) => { if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y); });
    ctx.strokeStyle = ROMA.gold;
    ctx.lineWidth = 2.2;
    ctx.stroke();
    ctx.strokeStyle = 'rgba(255,255,255,.55)';
    ctx.lineWidth = 0.8;
    ctx.stroke();

    // bornes (bornes romaines)
    P.forEach(p => {
      ctx.beginPath();
      ctx.moveTo(p.x, p.y - 4); ctx.lineTo(p.x + 3, p.y);
      ctx.lineTo(p.x, p.y + 4); ctx.lineTo(p.x - 3, p.y);
      ctx.closePath();
      ctx.fillStyle = ROMA.tyrian; ctx.fill();
      ctx.strokeStyle = ROMA.goldHi; ctx.lineWidth = 0.8; ctx.stroke();
    });
  },
};
