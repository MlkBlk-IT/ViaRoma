// ViaRoma Architecture — graphe d'orchestration LIVE.
//
// Ce graphe ne dessine PAS une ambition: il dessine ce qui existe et TOURNE.
// Chaque noeud est une brique reelle du code (CascadeManager, SessionManager,
// EgressLanes, adaptateurs, outils MCP) et chaque noeud est cliquable:
// il ouvre sa fiche avec ses donnees REELLS et ses actions executables.
//
// La direction des fleches est le sens du flux reel:
//   requete -> CascadeManager -> adaptateur -> egress (IP du compte)
//           -> reponse -> synthese -> reponse finale
(function () {
  'use strict';

  const esc = (s) => String(s == null ? '' : s).replace(/[<>&"]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));

  const ROMA = {
    ink: '#2A1F1A', red: '#C1121F', deep: '#5E0B14', gold: '#C69B4A',
    cream: '#FBF7EE', sand: '#EDE3D0', green: '#2F6B4F', teal: '#1F6F7A',
    violet: '#5B3A72', line: 'rgba(42,31,26,.22)'
  };

  // ── Helpers de dessin ────────────────────────────────────────────────
  const T = (x, y, txt, cls, anchor) =>
    `<text x="${x}" y="${y}" class="${cls || 'a-t'}" text-anchor="${anchor || 'start'}">${esc(txt)}</text>`;

  function node(o) {
    const { id, x, y, w, h, title, sub, lines, tone } = o;
    const stroke = ROMA[tone || 'red'];
    const body = (lines || []).map((l, i) =>
      `<text x="${x + 20}" y="${y + 74 + i * 19}" class="a-li">• ${esc(l)}</text>`).join('');
    return `<g class="a-node" data-arch="${esc(id)}" tabindex="0" role="button" aria-label="${esc(title)}">
      <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="14" class="a-box" style="stroke:${stroke}"/>
      <rect x="${x}" y="${y}" width="${w}" height="34" rx="14" class="a-head" style="fill:${stroke}"/>
      <rect x="${x}" y="${y + 22}" width="${w}" height="12" class="a-head" style="fill:${stroke}"/>
      ${T(x + 16, y + 23, title.toUpperCase(), 'a-h')}
      ${sub ? T(x + w - 14, y + 23, sub, 'a-sub', 'end') : ''}
      ${body}
      <text x="${x + w - 14}" y="${y + h - 12}" class="a-cta" text-anchor="end">voir le detail ›</text>
    </g>`;
  }

  function edge(d) {
    const { d: path, kind, label, lx, ly } = d;
    return `<g class="a-edge a-${kind}">
      <path d="${path}" class="a-line"/>
      ${label ? `<text x="${lx}" y="${ly}" class="a-el">${esc(label)}</text>` : ''}
    </g>`;
  }

  const arrow = (x1, y1, x2, y2, bend) => {
    const dy = bend || 0;
    return `M ${x1} ${y1} C ${x1} ${y1 + dy}, ${x2} ${y2 - dy}, ${x2} ${y2}`;
  };

  // ── Donnees reelles -> noeuds ─────────────────────────────────────────
  function build(data) {
    const cascade = data.cascade || {};
    const chain = cascade.fallback_chain || [];
    const provs = (data.providers && data.providers.providers) || [];
    const routing = (data.security && data.security.routing) || [];
    const lanes = (data.security && data.security.lanes) || [];
    const skipped = (data.security && data.security.skipped) || [];
    const sess = (data.sessions && data.sessions.stats) || {};
    const hun = (data.hunter && data.hunter.stats) || {};
    const eg = (data.egress && data.egress.stats) || {};

    // Les providers routables: d'abord la chaine de fallback (ce qui part
    // reellement), puis le routage securite. Jamais de provider invente.
    const routable = [];
    chain.forEach(c => {
      if (!routable.find(p => p.label === c.name)) {
        const r = routing.find(x => x.label === c.name) || {};
        routable.push({
          label: c.name, key: r.provider_key || '', state: c.state || 'unknown',
          success: c.success_rate, latency: c.avg_latency_ms, reqs: c.total_requests,
          account: r.account_id || '', egress: !!r.egress, tls: r.tls_profile || '',
          cookies: r.cookie_count || 0, score: r.score, locale: r.locale || ''
        });
      }
    });
    routing.forEach(r => {
      if (!routable.find(p => p.label === r.label)) {
        routable.push({
          label: r.label, key: r.provider_key || '', state: 'closed', success: null,
          latency: null, reqs: 0, account: r.account_id || '', egress: !!r.egress,
          tls: r.tls_profile || '', cookies: r.cookie_count || 0, score: r.score, locale: r.locale || ''
        });
      }
    });

    const shown = routable.slice(0, 3);
    const extra = routable.length - shown.length;

    const W = 1600, H = 1120;
    const px = [310, 650, 990];

    const parts = [];

    // ── Legende ────────────────────────────────────────────────────────
    parts.push(`<g class="a-legend">
      <rect x="34" y="30" width="250" height="212" rx="12" class="a-box" style="stroke:${ROMA.gold}"/>
      ${T(52, 56, 'LEGENDE', 'a-h', 'start')}
      ${[['Delegation', 'delegate'], ['Statut / resultats', 'status'], ['Memoire R/W', 'mem'],
         ['Acces outils', 'tool'], ['Egress (IP du compte)', 'egress'], ['Flux de reponse', 'result']]
        .map((l, i) => `<line x1="54" y1="${78 + i * 27}" x2="104" y2="${78 + i * 27}" class="a-line a-${l[1]}"/>
                        ${T(116, 83 + i * 27, l[0], 'a-li')}`).join('')}
    </g>`);

    // ── Manager / Superviseur ──────────────────────────────────────────
    const mgrX = 540, mgrY = 34, mgrW = 520, mgrH = 168;
    const mgrOk = !skipped.length || routable.length > 0;
    parts.push(node({
      id: 'manager', x: mgrX, y: mgrY, w: mgrW, h: mgrH, tone: 'red',
      title: 'Manager / Superviseur — CascadeManager',
      sub: `${Object.keys(cascade.providers || {}).length || 0} providers`,
      lines: [
        'Chaine de fallback: requete -> provider -> reponse',
        'Circuit breakers: open / half-open / closed',
        'Rotation multi-comptes sur 429 (rate limit)',
        'Fail-closed: aucun appel sans proxy de sortie'
      ]
    }));

    // ── Providers ──────────────────────────────────────────────────────
    shown.forEach((p, i) => {
      const x = px[i];
      const up = String(p.state).toUpperCase();
      const tone = p.state === 'closed' ? 'green' : (p.state === 'open' ? 'red' : 'gold');
      parts.push(node({
        id: 'provider:' + p.label, x: x, y: 300, w: 300, h: 168, tone: tone,
        title: p.label,
        sub: up,
        lines: [
          `Compte: ${p.account || '—'}`,
          `Egress: ${p.egress ? 'actif (IP dediee)' : 'ABSENT'}`,
          `TLS: ${p.tls || '—'} · cookies: ${p.cookies}`,
          `Latence: ${p.latency ? Math.round(p.latency) + ' ms' : '—'} · requetes: ${p.reqs || 0}`
        ]
      }));
    });
    if (extra > 0) {
      parts.push(`<g class="a-chip" data-arch="providers">
        <rect x="1330" y="352" width="150" height="46" rx="12" class="a-box" style="stroke:${ROMA.gold}"/>
        ${T(1405, 381, '+' + extra + ' autres', 'a-li', 'middle')}
      </g>`);
    }
    if (!shown.length) {
      parts.push(`<g class="a-chip" data-arch="providers">
        <rect x="650" y="330" width="300" height="60" rx="12" class="a-box" style="stroke:${ROMA.red}"/>
        ${T(800, 366, 'Aucun provider routable', 'a-li', 'middle')}
      </g>`);
    }

    // ── Egress / Shared memory / Tools ─────────────────────────────────
    parts.push(node({
      id: 'egress', x: 150, y: 580, w: 380, h: 186, tone: 'red',
      title: 'Egress — Lanes d\'IP',
      sub: `${lanes.length} lanes`,
      lines: [
        `Pool: ${eg.pool_size || 0} proxies · ${eg.usable || 0} utilisables`,
        `Brûlures: ${eg.burns || 0} · sondes: ${eg.probes || 0}`,
        'Une IP de sortie par compte',
        'Le proxy est transmis au couche HTTP'
      ]
    }));
    parts.push(node({
      id: 'memory', x: 610, y: 580, w: 380, h: 186, tone: 'gold',
      title: 'Memoire partagee — SessionManager',
      sub: `${sess.total_sessions || 0} sessions`,
      lines: [
        `Comptes charges: ${sess.total_accounts || 0}`,
        'Cookies recoltes (jar) par compte',
        'Identites: UA / TLS / viewport / locale',
        `Catalogue: ${hun.total_models || 0} modeles`
      ]
    }));
    parts.push(node({
      id: 'tools', x: 1070, y: 580, w: 380, h: 186, tone: 'teal',
      title: 'Registre d\'outils — MCP + API',
      sub: '5 outils',
      lines: [
        'chat · connect_provider · list_providers',
        'list_free_models · session_status',
        'API OpenAI-compatible /v1/chat/completions',
        'Dashboard: /api/dashboard/*'
      ]
    }));

    // ── Synthese / reponse finale ─────────────────────────────────────
    parts.push(node({
      id: 'synthesis', x: 600, y: 826, w: 400, h: 116, tone: 'violet',
      title: 'Synthese du resultat',
      sub: 'cascade',
      lines: ['Agit les chunks du provider retenu', 'Assemble la reponse finale']
    }));
    parts.push(node({
      id: 'response', x: 600, y: 972, w: 400, h: 100, tone: 'red',
      title: 'Reponse finale',
      sub: 'OpenAI-compatible',
      lines: ['choices[0].message.content', 'SSE streaming ou JSON']
    }));

    // ── Arêtes ─────────────────────────────────────────────────────────
    const E = [];
    // Delegation: manager -> providers
    shown.forEach((p, i) => {
      const x = px[i] + 150;
      E.push({ d: arrow(800, mgrY + mgrH, x, 296, 60), kind: 'delegate', label: 'DELEGATE', lx: x + 10, ly: 268 });
      // Statut: provider -> manager
      E.push({ d: arrow(x + 150, 300, 800, mgrY + mgrH, -50), kind: 'status', label: 'STATUT', lx: 1060, ly: 268 });
    });
    // Egress: providers -> egress
    shown.forEach((p, i) => {
      E.push({ d: arrow(px[i] + 150, 468, px[i] + 150, 576, 40), kind: 'egress' });
    });
    // Memoire: bidirectional memory <-> providers
    shown.forEach((p, i) => {
      const y = 520;
      E.push({ d: arrow(800, 576, px[i] + 150, 470, -34), kind: 'mem' });
      E.push({ d: arrow(px[i] + 150, 470, 800, 576, -34), kind: 'mem' });
      void y;
    });
    // Outils: manager -> tools
    E.push({ d: arrow(mgrX + mgrW, 110, 1260, 576, -80), kind: 'tool', label: 'OUTILS', lx: 1120, ly: 400 });
    // Resultat: providers -> synthese
    shown.forEach((p, i) => {
      E.push({ d: arrow(px[i] + 150, 468, 800, 822, 90), kind: 'result', label: 'RESULTAT', lx: 700, ly: 740 });
    });
    // Reponse finale
    E.push({ d: arrow(800, 946, 800, 968, 0), kind: 'result' });

    parts.push(`<svg class="a-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img"
      aria-label="Graphe d'orchestration ViaRoma">${E.map(edge).join('')}${parts.join('')}</svg>`);

    return { svg: parts.join(''), routable, shown, extra };
  }

  // ── Fiches cliquables (donnees reelles) ──────────────────────────────
  function openNode(id, data) {
    if (!window.RomaDrawer) return;
    const R = window.RomaDrawer.rows;
    const cascade = data.cascade || {};
    const provs = (data.providers && data.providers.providers) || [];
    const routing = (data.security && data.security.routing) || [];
    const lanes = (data.security && data.security.lanes) || [];
    const skipped = (data.security && data.security.skipped) || [];
    const sess = (data.sessions && data.sessions.stats) || {};
    const hun = (data.hunter && data.hunter.stats) || {};
    const eg = (data.egress && data.egress.stats) || {};

    const title = (s) => s;

    if (id === 'manager') {
      const stats = cascade.providers || {};
      window.RomaDrawer.open({
        kicker: 'Manager / Superviseur', title: 'CascadeManager',
        body: R([
          ['Providers routes', Object.keys(stats).length],
          ['Chaine de fallback', (cascade.fallback_chain || []).length],
          ['Max retries', (cascade.config || {}).max_retries],
          ['Comptes ecartes', skipped.length],
          ['Fail-closed', skipped.every(s => !/aucun proxy/.test(s.reason || '')) ? 'actif' : 'partiel']
        ]) + '<p class="drawer-note">Le superviseur decompose la requete en chaine de fallback, surveille les breakers et fait tourner les comptes quand un provider rate-limite.</p>'
          + '<div class="drawer-rows">' + Object.keys(stats).map(k =>
            `<div class="drawer-row"><span class="k">${esc(k)}</span><span class="v">${esc(JSON.stringify(stats[k]))}</span></div>`).join('') + '</div>',
        actions: [
          { label: '⚡ Recharger la cascade', action: 'cascade-refresh', kind: 'primary' },
          { label: '✕ Fermer', action: 'drawer-close' }
        ]
      });
      return;
    }

    if (id === 'provider:' + id.slice(9)) { /* unreachable */ }

    if (id.startsWith('provider:')) {
      const label = id.slice(9);
      const r = routing.find(x => x.label === label) || {};
      const c = (cascade.fallback_chain || []).find(x => x.name === label) || {};
      window.RomaDrawer.open({
        kicker: 'Adaptateur', title: label,
        body: R([
          ['Cle technique', r.provider_key || '—'],
          ['Compte', r.account_id || '—'],
          ['Egress', r.egress ? 'actif' : 'ABSENT (fail-closed)'],
          ['Profil TLS', r.tls_profile || '—'],
          ['User-Agent', r.user_agent || '—'],
          ['Locale', r.locale || '—'],
          ['Cookies dans le jar', r.cookie_count],
          ['Score', r.score],
          ['Etat du breaker', c.state || '—'],
          ['Taux de succes', c.success_rate != null ? (c.success_rate * 100).toFixed(1) + ' %' : '—'],
          ['Latence moyenne', c.avg_latency_ms != null ? Math.round(c.avg_latency_ms) + ' ms' : '—'],
          ['Requetes', c.total_requests || 0],
          ['Echecs consecutifs', c.consecutive_failures || 0]
        ]) + '<p class="drawer-note">Aucune valeur de cookie n\'est renvoyee par l\'API: les secrets restent sur la machine.</p>',
        actions: [
          { label: '⚡ Recharger le breaker', action: 'cascade-reset-one', data: { name: label }, kind: 'primary' },
          { label: '🔌 Connecter / configurer', action: 'provider-detail', data: { key: r.provider_key || '' } },
          { label: '✕ Fermer', action: 'drawer-close' }
        ]
      });
      return;
    }

    if (id === 'providers') {
      window.RomaDrawer.open({
        kicker: 'Routage', title: 'Tous les providers',
        body: '<div class="drawer-rows">' + provs.map(p =>
          `<div class="drawer-row"><span class="k">${esc(p.label)}</span><span class="v">${esc(p.account_id || '—')} · egress: ${p.egress ? 'oui' : 'NON'}</span></div>`).join('') + '</div>'
          + (skipped.length ? '<p class="drawer-note">Comptes ecartes: ' + esc(skipped.map(s => s.account_id).join(', ')) + '</p>' : ''),
        actions: [{ label: '✕ Fermer', action: 'drawer-close' }]
      });
      return;
    }

    if (id === 'egress') {
      window.RomaDrawer.open({
        kicker: 'Egress', title: "Lanes d'IP",
        body: R([
          ['Pool', eg.pool_size || 0], ['Utilisables', eg.usable || 0], ['Morts', eg.dead || 0],
          ['Quarantaine', eg.quarantined || 0], ['Brulures', eg.burns || 0], ['Sondes', eg.probes || 0]
        ]) + '<div class="drawer-rows">' + lanes.map(l =>
          `<div class="drawer-row"><span class="k">${esc(l.account_id)}</span><span class="v">${esc(l.public_ip || 'IP non resolue')} · ${esc(l.country || '—')} · ${esc(l.lane_state || '')}</span></div>`).join('') + '</div>',
        actions: [
          { label: '🔄 Tester le pool', action: 'egress-probe', kind: 'primary' },
          { label: '✕ Fermer', action: 'drawer-close' }
        ]
      });
      return;
    }

    if (id === 'memory') {
      window.RomaDrawer.open({
        kicker: 'Memoire partagee', title: 'SessionManager',
        body: R([
          ['Comptes charges', sess.total_accounts || 0],
          ['Sessions', sess.total_sessions || 0],
          ['Par etat', JSON.stringify(sess.by_state || {})],
          ['Par provider', JSON.stringify(sess.by_provider || {})],
          ['Catalogue', hun.total_models || 0],
          ['Frontier', hun.active_frontier || 0]
        ]) + '<p class="drawer-note">La memoire porte le jar de cookies recolte, les identites (UA/TLS/viewport/locale) et l\'etat de rotation par compte.</p>',
        actions: [
          { label: '📱 Faire tourner une identite', action: 'identity-rotate-open' },
          { label: '✕ Fermer', action: 'drawer-close' }
        ]
      });
      return;
    }

    if (id === 'tools') {
      window.RomaDrawer.open({
        kicker: 'Registre d\'outils', title: 'MCP + API',
        body: '<div class="drawer-rows">'
          + ['chat — Envoie un message a l\'IA et retourne la reponse texte.',
             'connect_provider — Connecte un compte a un provider (une seule fois).',
             'list_providers — Liste les providers connus et leur etat de connexion.',
             'list_free_models — Liste les modeles gratuits decouverts, filtres par tier.',
             'session_status — Etat live du routage: providers, sessions, lanes egress, IPs, burns.'
            ].map(t => `<div class="drawer-row"><span class="k">${esc(t.split('—')[0].trim())}</span><span class="v">${esc(t.split('—')[1] || '')}</span></div>`).join('')
          + '</div><p class="drawer-note">Transport MCP: stdio. API HTTP: /v1/chat/completions (compatible OpenAI) et /api/dashboard/* pour le dashboard.</p>',
        actions: [{ label: '✕ Fermer', action: 'drawer-close' }]
      });
      return;
    }

    if (id === 'synthesis') {
      window.RomaDrawer.open({
        kicker: 'Synthese', title: 'Synthese du resultat',
        body: R([
          ['Providers dans la chaine', (cascade.fallback_chain || []).length],
          ['Ordre', (cascade.fallback_chain || []).map(c => c.name).join(' → ') || '—'],
          ['Retries max', (cascade.config || {}).max_retries]
        ]) + '<p class="drawer-note">La synthese ne cree rien: elle concatene les chunks du provider reellement retenu par le superviseur.</p>',
        actions: [{ label: '✕ Fermer', action: 'drawer-close' }]
      });
      return;
    }

    if (id === 'response') {
      window.RomaDrawer.open({
        kicker: 'Sortie', title: 'Reponse finale',
        body: R([
          ['Format', 'OpenAI chat.completion'],
          ['Streaming SSE', 'oui (data: [DONE])'],
          ['Modele', 'frontier-auto par defaut'],
          ['Erreur cascade', '503 JSON si tous les providers echouent']
        ]) + '<pre class="drawer-code">POST /v1/chat/completions\n{\n  "model": "frontier-auto",\n  "messages": [{"role": "user", "content": "..."}]\n}</pre>',
        actions: [{ label: '✕ Fermer', action: 'drawer-close' }]
      });
      return;
    }

    void title;
  }

  // ── API publique ─────────────────────────────────────────────────────
  window.ViaRomaArchitecture = {
    render(mount, data) {
      if (!mount) return null;
      const built = build(data);
      mount.innerHTML = built.svg;
      mount.querySelectorAll('[data-arch]').forEach(g => {
        const id = g.getAttribute('data-arch');
        g.addEventListener('click', () => openNode(id, data));
        g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openNode(id, data); } });
      });
      return built;
    },
    openNode
  };
})();
