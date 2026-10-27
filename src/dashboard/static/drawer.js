// RomaDrawer — panneau de detail. Chaque element cliquable du dashboard
// ouvre ici une fiche REELLE (donnees du serveur + actions executables).
(function () {
  'use strict';

  let el = null, backdrop = null, lastFocus = null;

  function ensure() {
    if (el) return el;
    backdrop = document.createElement('div');
    backdrop.className = 'drawer-backdrop';
    backdrop.addEventListener('click', () => close());

    el = document.createElement('aside');
    el.className = 'drawer';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.innerHTML =
      '<div class="drawer-head">' +
        '<div><div class="drawer-kicker" id="drawer-kicker"></div>' +
        '<h3 id="drawer-title"></h3></div>' +
        '<button class="drawer-close" data-action="drawer-close" title="Fermer">✕</button>' +
      '</div>' +
      '<div class="drawer-body" id="drawer-body"></div>' +
      '<div class="drawer-actions" id="drawer-actions"></div>';
    document.body.appendChild(backdrop);
    document.body.appendChild(el);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
    return el;
  }

  function open(opts) {
    opts = opts || {};
    ensure();
    lastFocus = document.activeElement;
    const k = document.getElementById('drawer-kicker');
    const t = document.getElementById('drawer-title');
    const b = document.getElementById('drawer-body');
    const a = document.getElementById('drawer-actions');
    if (k) k.textContent = opts.kicker || '';
    if (t) t.textContent = opts.title || '';
    if (b) b.innerHTML = opts.body || '';
    if (a) {
      a.innerHTML = (opts.actions || []).map((x, i) => {
        const cls = x.kind === 'primary' ? 'btn primary' : (x.kind === 'danger' ? 'btn danger' : 'btn');
        const data = Object.entries(x.data || {}).map(([k2, v]) => `data-${k2}="${String(v).replace(/"/g, '&quot;')}"`).join(' ');
        return `<button class="${cls}" data-action="${x.action}" ${data}>${x.label}</button>`;
      }).join('');
    }
    document.body.classList.add('drawer-open');
    el.classList.add('open');
    backdrop.classList.add('open');
    const first = el.querySelector('button, .btn');
    if (first) first.focus();
    return el;
  }

  function close() {
    if (!el) return;
    el.classList.remove('open');
    backdrop.classList.remove('open');
    document.body.classList.remove('drawer-open');
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  // Petits blocs reutilisables dans le corps du drawer.
  const rows = (pairs) => '<div class="drawer-rows">' + pairs
    .filter(p => p && p[1] !== undefined && p[1] !== null && p[1] !== '')
    .map(p => `<div class="drawer-row"><span class="k">${p[0]}</span><span class="v">${p[1]}</span></div>`)
    .join('') + '</div>';

  const kv = (k, v) => rows([[k, v]]);

  window.RomaDrawer = { open, close, isOpen: () => !!(el && el.classList.contains('open')), rows, kv };
})();
