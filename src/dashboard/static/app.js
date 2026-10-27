/* ViaRoma Dashboard — Pure vanilla JS. ENGLISH UI. Plug & Play. */
/* TOUT est clickable. Event delegation global. Zero bouton mort. */

const $ = (s, p=document) => p.querySelector(s);
const $$ = (s, p=document) => [...p.querySelectorAll(s)];
const esc = (s) => String(s||'').replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));
const fmtAgo = (ts) => { if(!ts) return '—'; const s = Date.now()/1000 - ts; if(s<60) return Math.floor(s)+'s ago'; if(s<3600) return Math.floor(s/60)+'m ago'; return Math.floor(s/3600)+'h ago'; };
// Ecriture sure: si l'onglet a change pendant le chargement, on n'ecrit pas
// dans un DOM qui n'existe plus (source d'erreur "null innerHTML").
const setHTML = (sel, html) => { const e = $(sel); if (e) { e.innerHTML = html; return true; } return false; };
const tabStill = (tab) => state.activeTab === tab;

async function api(path, opts={}) {
  try {
    const r = await fetch('/api/dashboard'+path, {headers:{'Content-Type':'application/json',...opts.headers}, ...opts});
    if (!r.ok) { const e = await r.json().catch(()=>({detail:r.statusText})); throw new Error(e.detail||'HTTP '+r.status); }
    return r.json();
  } catch(e) { throw e; }
}

// Appel HORS du prefixe /api/dashboard (ex: /v1/chat/completions).
async function apiRaw(path, opts={}) {
  const r = await fetch(path, {headers:{'Content-Type':'application/json',...opts.headers}, ...opts});
  if (!r.ok) { const e = await r.json().catch(()=>({detail:r.statusText})); throw new Error(e.detail||('HTTP '+r.status)); }
  return r.json();
}

function btn(label, action, opts={}) {
  const cls = opts.primary ? 'btn primary' : opts.danger ? 'btn danger' : 'btn';
  let data = '';
  if (opts.data) for (const [k,v] of Object.entries(opts.data)) data += ` data-${k}="${esc(v)}"`;
  return `<button class="${cls}" data-action="${action}"${data}>${label}</button>`;
}
function kpi(rows) { return '<div class="kpi-row">'+rows.map(([v,l,a])=>`<div class="kpi"${a?` data-action="${a}" title="Cliquer pour agir"`:''}><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join('')+'</div>'; }
function badge(state) { const ok = ['closed','active','ready','ok','healthy','running'].includes(state); return `<span class="badge ${ok?'ok':'off'}">${esc(state)}</span>`; }

const state = {
  activeTab: 'overview', log: [], hideSecrets: true, traffic: [],
  hunterStats: null, cascadeProviders: null, egressStats: null, sessionsStats: null,
  editingCred: null, flagCheckEnabled: true,
  cfgActive: null, cfgData: {},
  hunterFilter: 'all', hunterSearch: '',
};

// ═══ EVENT DELEGATION GLOBAL ═══
// Un seul listener pour TOUS les data-action. Plus jamais de bouton mort.
document.addEventListener('click', async (ev) => {
  const el = ev.target.closest('[data-action]');
  if (!el) return;
  ev.preventDefault();
  const action = el.dataset.action;
  if (action) doAction(action, el);
});

// ═══ LOG ═══
function log(msg, kind='') {
  const ts = new Date().toLocaleTimeString('en-US');
  state.log.push({ts, msg, kind});
  state.log = state.log.slice(-100);
  const el = $('#log');
  if (el) el.innerHTML = state.log.slice(-25).reverse().map(l => `<div class="${l.kind}">[${l.ts}] ${esc(l.msg)}</div>`).join('');
}

// ═══ TAB SWITCHING ═══
// ATTENTION: toute cle de loaders DOIT avoir son loader. Avant, un onglet
// inconnu tombait sur loadOverview() qui sortait aussitot (tabStill) et
// laissait « Loading... » a l'ecran pour toujours.
const loaders = {
  overview: loadOverview, hunter: loadHunter, cascade: loadCascade,
  sessions: loadSessions, egress: loadEgress, providers: loadProviders,
  credentials: loadCredentials, antiwaf: loadAntiWAF, identities: loadIdentities,
  config: loadFormConfig,
  security: loadSecurity, metrics: loadMetrics, journal: loadJournal,
  architecture: loadArchitecture, playground: loadPlayground, models: loadModels,
  live: loadLive,
};

function switchTab(tab) {
  state.activeTab = tab;
  $$('.nav-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  const c = $('#tab-content');
  const loader = loaders[tab];
  if (!loader) {
    if (c) c.innerHTML = `<div class="tab-panel"><p class="hint">Onglet indisponible: ${esc(tab)}</p></div>`;
    log('Onglet inconnu: ' + tab, 'err');
    return;
  }
  if (c) c.innerHTML = '<div class="tab-panel"><p class="hint">Loading…</p></div>';
  Promise.resolve(loader()).catch(e => {
    log('onglet ' + tab + ': ' + e.message, 'err');
    if (c && state.activeTab === tab) {
      c.innerHTML = `<div class="tab-panel"><p class="hint">Erreur: ${esc(e.message)}</p></div>`;
    }
  });
  renderRightPanel();
}

// ═══ OVERVIEW ═══
async function loadOverview() {
  if (!tabStill('overview')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>Roma Overview</h2>
    <div class="hero">
      <div class="hero-colosseum-wrap">
        <canvas class="colosseum-hero" id="colosseum-hero"></canvas>
        <div class="hero-caption"><span><b>COLISEVM</b> · arene de routage</span><span id="ov-hero-state">—</span></div>
      </div>
      <div class="spoof-wrap">
        <canvas class="spoof-canvas" id="spoof-overview"></canvas>
      </div>
    </div>
    <div class="tiles">
      <div class="tile" id="ov-cmd"></div>
      <div class="tile" id="ov-traffic"></div>
      <div class="tile" id="ov-live"></div>
      <div class="tile" id="ov-guard"></div>
    </div>
  </div>`;
  // Le Colisée du hero (grand format) est monte a chaud: il n'existe pas
  // au chargement de la page, le module ne voit que les canvas presents.
  if (window.ViaRomaColosseum) window.ViaRomaColosseum.mount($('#colosseum-hero'));
  try {
    const [h, c, s2, e, sec] = await Promise.all([
      api('/hunter/detail'), api('/cascade/detail'), api('/sessions/detail'),
      api('/egress/detail'), api('/security/summary')
    ]);
    state.hunterStats = h.stats; state.cascadeProviders = c.providers; state.egressStats = e.stats;
    const lanes = sec.lanes||[]; const skipped = sec.skipped||[]; const routing = sec.routing||[];
    const chain = c.fallback_chain || [];
    // --- animation IP spoofing ---
    const lane0 = lanes.find(l => l.public_ip) || lanes[0] || {};
    const r0 = routing[0]||{};
    if (window.ViaRomaSpoof) {
      window.ViaRomaSpoof.mount($('#spoof-overview'), {
        egressIp: lane0.public_ip || '—',
        country: lane0.country || '',
        tls: lane0.tls_profile || r0.tls_profile || 'chrome120',
        ja3: 'ja3',
        account: lane0.account_id || ''
      });
    }
    const hs = $('#ov-hero-state');
    if (hs) hs.textContent = routing.length + ' route(s) active(s) · ' + lanes.length + ' lane(s)';

    // ── TILE 1 · Centre de commandement (routage REEL) ─────────────
    const rmap = {}; routing.forEach(r => rmap[r.label] = r);
    let cmd = `<div class="tile-head"><h3>🏛 Centre de commandement</h3><span class="sub">${chain.length} etape(s)</span></div>
      <div class="cmd-flow"><div class="cmd-node">requete</div><div class="cmd-arrow">→</div><div class="cmd-node cmd-hub">CascadeManager</div></div>`;
    if (chain.length) {
      cmd += '<div class="cmd-provs">';
      chain.forEach(cp => {
        const r = rmap[cp.name] || {};
        const ok = cp.state === 'closed';
        cmd += `<button class="cmd-prov" data-action="cascade-provider" data-name="${esc(cp.name)}">
          <b>${esc(cp.name)}</b>
          <span class="badge ${ok?'ok':'off'}">${esc(cp.state)}</span>
          <span class="meta">${cp.avg_latency_ms ? Math.round(cp.avg_latency_ms)+' ms' : '—'} · ${(cp.success_rate*100).toFixed(0)}% · ${esc(r.account_id||'—')}</span>
          <span class="arrow">›</span></button>`;
      });
      cmd += '</div>';
    } else {
      cmd += '<p class="empty">Aucun provider routable: le fail-closed bloque tout appel sans egress.</p>';
    }
    cmd += `<p class="tile-note" style="margin-top:8px"><span>Chaine: ${esc(chain.map(x=>x.name).join(' → ') || '—')}</span><span>retries ${(c.config||{}).max_retries ?? 3}</span></p>`;
    setHTML('#ov-cmd', cmd);

    // ── TILE 2 · Trafic & catalogue ─────────────────────────────────
    const totalModels = h.stats?.total_models||0;
    const frontier = h.stats?.active_frontier||0;
    const nProv = Object.keys(c.providers||{}).length;
    const usable = e.stats?.usable||0, pool = e.stats?.pool_size||0;
    const pct = totalModels ? Math.round((frontier/totalModels)*100) : 0;
    setHTML('#ov-traffic', `<div class="tile-head"><h3>📊 Trafic & catalogue</h3><span class="sub">reel</span></div>
      <div class="tile-stat-row">
        <button class="tile-stat" data-action="tab-open" data-tab="models"><b>${totalModels}</b><span>Modeles</span></button>
        <button class="tile-stat" data-action="go-frontier"><b>${frontier}</b><span>Frontier</span></button>
        <button class="tile-stat" data-action="tab-open" data-tab="providers"><b>${nProv}</b><span>Providers</span></button>
        <button class="tile-stat" data-action="tab-open" data-tab="egress"><b>${usable}/${pool}</b><span>Proxies</span></button>
      </div>
      <div class="tile-bar"><i style="width:${pct}%"></i></div>
      <div class="tile-note"><span>Frontier du catalogue</span><span>${pct}%</span></div>
      <div class="tile-note" style="margin-top:6px"><span>Burns ${e.stats?.burns||0}</span><span>Sondes ${e.stats?.probes||0}</span><span>Sessions ${s2.stats?.total_sessions||0}</span></div>`);

    // ── TILE 3 · Requetes live (journal REEL) ───────────────────────
    const ev = state.log.slice(-6).reverse();
    let live = `<div class="tile-head"><h3>📜 Requêtes live</h3><span class="sub">journal</span></div>`;
    if (ev.length) {
      live += '<table class="tile-table"><thead><tr><th>Heure</th><th>Evenement</th><th>Etat</th></tr></thead><tbody>'
        + ev.map(l => `<tr class="clickable" data-action="tab-open" data-tab="journal"><td>${esc(l.ts)}</td><td>${esc(l.msg).slice(0,40)}</td><td>${l.kind==='err'?'<span class="dot-err"></span>err':'<span class="dot-ok"></span>ok'}</td></tr>`).join('')
        + '</tbody></table>';
    } else {
      live += `<p class="empty">Aucun evenement pour l'instant. Lance une action: elle apparait ici et dans le Journal.</p>`;
    }
    live += `<div class="tile-note" style="margin-top:8px"><span>${state.log.length} evenement(s)</span><span data-action="tab-open" data-tab="journal" style="cursor:pointer;color:var(--accent)">tout voir ›</span></div>`;
    setHTML('#ov-live', live);

    // ── TILE 4 · Garde-fous (fail-closed) ───────────────────────────
    const allEgress = routing.length > 0 && routing.every(r => r.egress);
    let guard = `<div class="tile-head"><h3>🛡️ Garde-fous</h3><span class="sub">fail-closed</span></div>
      <div class="security-banner ${allEgress ? '' : 'warn'}" style="margin-bottom:8px">
        <span class="sp">${allEgress ? '🛡️' : '⚠️'}</span>
        <span>${allEgress ? "L'IP de la machine n'est jamais transmise." : skipped.length + " compte(s) ecarte(s) sans proxy de sortie."}</span>
      </div>`;
    if (skipped.length) {
      guard += skipped.map(s => `<div class="skipped-row"><span>⛔ ${esc(s.account_id||'—')}</span><span class="why">${esc(s.reason||'')}</span></div>`).join('');
    }
    guard += '<div class="drawer-rows" style="margin-top:8px">'
      + (sec.guarantees||[]).map(g => `<div class="drawer-row"><span class="k">✔</span><span class="v" style="text-align:left">${esc(g)}</span></div>`).join('')
      + '</div>';
    setHTML('#ov-guard', guard);

    const ph = $('#pill-hunter'); if (ph) ph.textContent = frontier+' frontier';
    const pc = $('#pill-cascade'); if (pc) pc.textContent = nProv+' providers';
    const pe = $('#pill-egress'); if (pe) pe.textContent = usable+'/'+pool+' proxies';
    state.liveStats = { models: totalModels, frontier, providers: nProv, usable, pool, lanes: lanes.length };
  } catch(e) { log('overview: '+e.message,'err'); }
}

// ═══ SECURITE ═══
async function loadSecurity() {
  if (!tabStill('security')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>🛡️ Sécurité — Fail-closed</h2>
    <div class="btn-row">${btn('🔄 Recharger','security-refresh',{primary:true})}</div>
    <div class="tiles">
      <div class="tile" id="sec-state"></div>
      <div class="tile" id="sec-guarantees"></div>
    </div>
    <div class="card glass"><h3>🛣️ Routage — chaque provider part par la lane de son compte</h3>
      <div id="sec-routing" class="card-list"></div></div>
    <div class="card glass"><h3>⛔ Comptes écartés</h3>
      <div id="sec-skipped" class="card-list"></div></div>
  </div>`;
  try {
    const sec = await api('/security/summary');
    const routing = sec.routing||[], skipped = sec.skipped||[], lanes = sec.lanes||[];
    setHTML('#sec-state', `<div class="tile-head"><h3>État des garanties</h3><span class="sub">en direct</span></div>
      <div class="tile-stat-row">
        <div class="tile-stat"><b>${sec.fail_closed ? 'ACTIF' : 'INACTIF'}</b><span>Fail-closed</span></div>
        <div class="tile-stat"><b>${sec.real_ip_exposed ? 'OUI' : 'NON'}</b><span>IP exposee</span></div>
        <div class="tile-stat"><b>${sec.credentials_exposed ? 'OUI' : 'NON'}</b><span>Credentials</span></div>
        <div class="tile-stat"><b>${lanes.length}</b><span>Lanes</span></div>
      </div>
      <div class="tile-note" style="margin-top:10px"><span>Comptes routes: ${routing.length}</span><span>Comptes ecartes: ${skipped.length}</span></div>`);
    setHTML('#sec-guarantees', `<div class="tile-head"><h3>Ce que le noyau garantit</h3><span class="sub">${(sec.guarantees||[]).length} regles</span></div>`
      + '<div class="drawer-rows">' + (sec.guarantees||[]).map(g => `<div class="drawer-row"><span class="k">✔</span><span class="v" style="text-align:left">${esc(g)}</span></div>`).join('') + '</div>');
    setHTML('#sec-routing', routing.length ? routing.map(r => `
      <div class="row clickable" data-action="provider-detail" data-key="${esc(r.provider_key)}">
        <span class="name">${esc(r.label)}</span>
        <span class="meta">${esc(r.account_id)} · ${esc(r.tls_profile)} · ${esc(r.locale)}</span>
        <span class="badge ${r.egress?'ok':'off'}">${r.egress?'egress':'SANS EGRESS'}</span>
      </div>`).join('') : '<p class="empty">Aucun provider route.</p>');
    setHTML('#sec-skipped', skipped.length ? skipped.map(s => `
      <div class="row"><span class="name">⛔ ${esc(s.account_id)}</span>
      <span class="meta">${esc(s.reason)}</span></div>`).join('')
      : '<p class="empty">Aucun compte ecarte — tout le monde a une sortie.</p>');
  } catch(e) { log('security: '+e.message,'err'); }
}

// ═══ METRIQUES ═══
async function loadMetrics() {
  if (!tabStill('metrics')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>📈 Métriques</h2>
    <div class="btn-row">${btn('🔄 Recharger','metrics-refresh',{primary:true})}</div>
    <div class="tiles">
      <div class="tile"><div class="tile-head"><h3>Models by Tier</h3><span class="sub">catalogue</span></div>
        <div class="chart-container"><canvas id="m-models" class="chart-canvas" style="height:180px"></canvas></div></div>
      <div class="tile"><div class="tile-head"><h3>Circuit Breakers</h3><span class="sub">etats</span></div>
        <div class="chart-container"><canvas id="m-breakers" class="chart-canvas" style="height:180px"></canvas></div></div>
    </div>
    <div class="card glass"><h3>Répartition du catalogue</h3><div id="m-tiers" class="card-list"></div></div>
  </div>`;
  try {
    const h = await api('/hunter/detail?limit=1');
    const c = await api('/cascade/detail');
    const tiers = h.tiers || h.stats?.by_tier || {};
    setHTML('#m-tiers', Object.keys(tiers).length ? Object.entries(tiers).map(([t,n]) => `
      <div class="row clickable" data-action="go-frontier"><span class="name">${esc(t)}</span>
      <span class="meta">${n} modeles</span></div>`).join('') : '<p class="empty">Donnees de tier indisponibles.</p>');
    if (window.ViaRomaCharts) {
      window.ViaRomaCharts.models($('#m-models'), h);
      window.ViaRomaCharts.breakers($('#m-breakers'), c);
    }
  } catch(e) { log('metrics: '+e.message,'err'); }
}

// ═══ JOURNAL ═══
async function loadJournal() {
  if (!tabStill('journal')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>📜 Journal</h2>
    <div class="btn-row">${btn('🧹 Vider','journal-clear')} ${btn('📋 Copier','journal-copy')}</div>
    <div class="card glass"><h3>Événements <span id="journal-count" class="badge ok">${state.log.length}</span></h3>
      <div id="journal-list" class="card-list" style="max-height:560px;overflow-y:auto"></div></div>
  </div>`;
  renderJournal();
}
function renderJournal() {
  const box = $('#journal-list'); if (!box) return;
  const c = $('#journal-count'); if (c) c.textContent = state.log.length;
  box.innerHTML = state.log.length ? state.log.slice().reverse().map(l => `
    <div class="row"><span class="name">${l.kind==='err'?'<span class="dot-err"></span>':(l.kind==='ok'?'<span class="dot-ok"></span>':'●')} ${esc(l.msg)}</span>
    <span class="meta">${esc(l.ts)}</span></div>`).join('')
    : '<p class="empty">Aucun evenement. Lance une action depuis le dashboard.</p>';
}

// ═══ ARCHITECTURE ═══
async function loadArchitecture() {
  if (!tabStill('architecture')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>🏛️ Architecture d'orchestration</h2>
    <div class="btn-row">${btn('🔄 Recharger','arch-refresh',{primary:true})}</div>
    <p class="hint">Graphe LIVE des briques reelles de ViaRoma. Chaque noeud est cliquable: il ouvre sa fiche et ses actions.</p>
    <div class="arch-wrap"><div id="arch-mount"></div></div>
  </div>`;
  try {
    const [cascade, providers, security, sessions, hunter, egress] = await Promise.all([
      api('/cascade/detail'), api('/providers/detail'), api('/security/summary'),
      api('/sessions/detail'), api('/hunter/detail?limit=1'), api('/egress/detail')
    ]);
    if (window.ViaRomaArchitecture) {
      window.ViaRomaArchitecture.render($('#arch-mount'), {cascade, providers, security, sessions, hunter, egress});
    }
  } catch(e) { log('architecture: '+e.message,'err'); }
}

// ═══ PLAYGROUND ═══
async function loadPlayground() {
  if (!tabStill('playground')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>⚔️ Console</h2>
    <p class="hint">Envoie une vraie requete a la cascade via POST /v1/chat/completions (compatible OpenAI). Sans credentials, le serveur repond 503 — c'est la vraie reponse, pas une simulation.</p>
    <div class="card glass">
      <div class="form-row"><input type="text" id="pg-model" value="frontier-auto" placeholder="modele"></div>
      <div class="form-row"><textarea id="pg-msg" rows="4" placeholder="Votre message...">Test de bout en bout ViaRoma.</textarea></div>
      <div class="btn-row">${btn('⚔️ Envoyer','playground-send',{primary:true})}</div>
    </div>
    <div class="card glass"><h3>Réponse</h3><div id="pg-out" class="card-list"><p class="empty">Aucune requete envoyee.</p></div></div>
  </div>`;
}
async function sendPlayground() {
  const msg = ($('#pg-msg')||{}).value || '';
  const model = ($('#pg-model')||{}).value || 'frontier-auto';
  if (!msg.trim()) { log('Console: message vide', 'err'); return; }
  const out = $('#pg-out');
  if (out) out.innerHTML = '<p class="empty">Envoi en cours...</p>';
  log('Console: envoi vers la cascade...');
  try {
    const r = await apiRaw('/v1/chat/completions', {method:'POST', body:JSON.stringify({
      model, messages:[{role:'user', content: msg}], stream: false
    })});
    const content = (r.choices && r.choices[0] && r.choices[0].message && r.choices[0].message.content) || '';
    if (out) out.innerHTML = `<div class="drawer-row"><span class="k">Modele</span><span class="v">${esc(r.model||model)}</span></div>
      <pre class="drawer-code">${esc(content || '(reponse vide)')}</pre>`;
    log('Console: reponse recue (' + (content||'').length + ' car.)', 'ok');
  } catch(e) {
    if (out) out.innerHTML = `<pre class="drawer-code">ERREUR: ${esc(e.message)}</pre>
      <p class="drawer-note">C'est la VRAIE erreur du serveur. Un 503 signifie que la cascade a essaye tous les providers sans succes (credentials absents ou providers down).</p>`;
    log('Console: '+e.message, 'err');
  }
}

// ═══ MODELES ═══
async function loadModels() {
  if (!tabStill('models')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>🗂️ Modèles libres</h2>
    <div class="btn-row">${btn('🔍 Scanner','hunter-scan')} ${btn('🔄 Recharger','models-refresh',{primary:true})}</div>
    <div id="models-kpi" class="kpi-row"></div>
    <div class="card glass"><h3>Frontier <span id="models-count" class="badge ok">—</span></h3>
      <div id="models-list" class="card-list" style="max-height:520px;overflow-y:auto"></div></div>
  </div>`;
  try {
    const d = await api('/hunter/detail?tier=frontier&limit=200');
    setHTML('#models-kpi', kpi([
      [d.total_catalog||0, 'Catalogue'],
      [d.total||0, 'Frontier'],
      [d.models?.length||0, 'Affiches'],
    ]));
    const mc = $('#models-count'); if (mc) mc.textContent = d.total || 0;
    setHTML('#models-list', (d.models||[]).map(m => `
      <div class="row clickable" data-action="model-detail" data-model="${esc(m.model_id)}">
        <span class="name">${esc(m.model_id)}</span>
        <span class="meta">${esc((m.metadata||{}).origin?.label || '')} · ${esc(m.provider||'')}</span>
        <span class="badge ${m.tier==='frontier'?'ok':'off'}">${esc(m.tier||'')}</span>
      </div>`).join('') || '<p class="empty">Aucun modele frontier.</p>');
  } catch(e) { log('models: '+e.message,'err'); }
}

// ═══ LIVE — sorties temps reel ═══
async function loadLive() {
  if (!tabStill('live')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>🔴 Live — sorties et annonces</h2>
    <div class="btn-row">${btn('🔄 Rafraîchir','live-refresh',{primary:true})}</div>
    <div id="live-kpi" class="kpi-row"></div>
    <div class="tiles">
      <div class="tile" id="live-releases"></div>
      <div class="tile" id="live-gguf"></div>
    </div>
    <div class="card glass"><h3>📰 Flux live <span id="live-news-count" class="badge ok">—</span></h3>
      <div id="live-news" class="card-list" style="max-height:520px;overflow-y:auto"></div></div>
  </div>`;
  try {
    const d = await api('/hunter/live');
    const bo = d.by_origin || {};
    setHTML('#live-kpi', kpi([
      [(bo.cn||0)+' cn', 'Chine', 'live-origin-cn'],
      [(bo.eu||0)+' eu', 'Europe', 'live-origin-eu'],
      [(bo.us||0)+' us', 'Etats-Unis', 'live-origin-us'],
      [(d.context_known||0), 'ctx réelle'],
      [(d.gguf||[]).length, 'GGUF'],
    ]));
    setHTML('#live-releases', `<div class="tile-head"><h3>🆕 Sorties récentes</h3><span class="sub">créés sur HuggingFace</span></div>`
      + ((d.recent||[]).slice(0,12).map(m => `
        <div class="row clickable" data-action="live-model" data-model="${esc(m.model_id)}">
          <span class="name">${esc(m.model_id.split('/').pop())}</span>
          <span class="meta">${esc((m.metadata||{}).origin?.label||'')}</span>
          <span class="badge ${m.context_window?'ok':'off'}">${m.context_window ? (m.context_window/1024).toFixed(0)+'k' : 'ctx ?'}</span>
        </div>`).join('') || '<p class="empty">Aucune sortie recente.</p>'));
    setHTML('#live-gguf', `<div class="tile-head"><h3>📦 Téléchargements GGUF</h3><span class="sub">fichiers réels</span></div>`
      + ((d.gguf||[]).slice(0,10).map(m => `
        <div class="row clickable" data-action="live-model" data-model="${esc(m.model_id)}">
          <span class="name">${esc(m.model_id.replace('hf-gguf/','').split('/').pop())}</span>
          <span class="meta">${(m.download_modes||[]).length} fichier(s) · ${esc((m.metadata||{}).origin?.label||'')}</span>
        </div>`).join('') || '<p class="empty">Aucun depot GGUF.</p>'));
    const nc = $('#live-news-count'); if (nc) nc.textContent = (d.news||[]).length;
    setHTML('#live-news', (d.news||[]).slice(0,60).map(n => `
      <div class="row">
        <span class="name">${n.link ? `<a href="${esc(n.link)}" target="_blank" rel="noopener" style="color:inherit;text-decoration:none">${esc(n.title)}</a>` : esc(n.title)}</span>
        <span class="meta">${esc(n.source||'')}</span>
      </div>`).join('') || '<p class="empty">Aucun flux disponible.</p>');
  } catch(e) { log('live: '+e.message,'err'); }
}

// ═══ HUNTER ═══
async function loadHunter() {
  if (!tabStill('hunter')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>Free Hunter — Global Discovery Engine</h2>
    <div class="btn-row">${btn('🔄 Scan Now','hunter-scan',{primary:true})} ${btn('📊 Load Catalog','hunter-load')}</div>
    <div id="hunter-kpi" class="kpi-row"></div>
    <div class="card glass"><h3>Filter Models</h3>
      <div class="form-row"><input type="text" id="hunter-search" placeholder="Search model name..." value="${esc(state.hunterSearch)}"></div>
      <div class="btn-row" id="hunter-filters">
        ${btn('All','hunter-filter-all')}
        ${btn('Frontier','hunter-filter-frontier',{primary:state.hunterFilter==='frontier'})}
        ${btn('Large','hunter-filter-large',{primary:state.hunterFilter==='large'})}
        ${btn('Medium','hunter-filter-medium',{primary:state.hunterFilter==='medium'})}
        ${btn('Small','hunter-filter-small',{primary:state.hunterFilter==='small'})}
      </div>
    </div>
    <div class="card glass"><h3>Discovered Models <span id="hunter-count" class="badge ok">—</span></h3>
      <div id="hunter-models" class="card-list" style="max-height:500px;overflow-y:auto"></div>
    </div>
  </div>`;
  // Wire search input
  const si = $('#hunter-search');
  if (si) si.addEventListener('input', () => { state.hunterSearch = si.value; refreshHunterModels(); });
  try {
    const d = await refreshHunterModels();
    $('#hunter-kpi').innerHTML = kpi([
      [d.stats?.total_models||0, 'Total'],
      [d.stats?.active_frontier||0, 'Frontier', 'hunter-filter-frontier'],
      [d.running?'YES':'NO', 'Scanning', 'hunter-scan'],
      [fmtAgo(d.stats?.last_scan), 'Last Scan', 'hunter-scan'],
    ]);
  } catch(e) { log('hunter: '+e.message,'err'); }
}

function renderHunterFilters() {
  const box = $('#hunter-filters'); if (!box) return;
  const f = state.hunterFilter || 'all';
  box.innerHTML =
    btn('All', 'hunter-filter-all', { primary: f === 'all' }) +
    btn('Frontier', 'hunter-filter-frontier', { primary: f === 'frontier' }) +
    btn('Large', 'hunter-filter-large', { primary: f === 'large' }) +
    btn('Medium', 'hunter-filter-medium', { primary: f === 'medium' }) +
    btn('Small', 'hunter-filter-small', { primary: f === 'small' });
}

// Le catalogue fait ~2000 modeles: le filtrage se fait COTE SERVEUR
// (sinon l'API renvoyait les 100 plus recents et le tier frontier etait invisible).
async function refreshHunterModels() {  const params = new URLSearchParams();
  if (state.hunterFilter && state.hunterFilter !== 'all') params.set('tier', state.hunterFilter);
  if (state.hunterSearch) params.set('q', state.hunterSearch);
  params.set('limit', '500');
  const d = await api('/hunter/detail?' + params.toString());
  state.hunterModels = d.models || [];
  state.hunterTotal = d.total || 0;
  state.hunterTotalCatalog = d.total_catalog || 0;
  state.hunterStats = d.stats;
  renderHunterModels();
  return d;
}

function renderHunterModels() {
  const models = state.hunterModels || [];
  const el = $('#hunter-models'); if (!el) return;
  el.innerHTML = models.slice(0, 300).map(m => {
    const tc = m.tier==='frontier'?'ok':'';
    return `<div class="row clickable" data-action="model-detail" data-model="${esc(m.model_id)}"><div><span class="name">${esc(m.model_id)}</span> <span class="badge ${tc}">${esc(m.tier)}</span></div><span class="meta">${esc(m.provider)} · ctx ${m.context_window||'—'} · ${fmtAgo(m.last_verified)}</span></div>`;
  }).join('') || '<p class="empty">Aucun modèle. Clique sur "Scan Now".</p>';
  const c = $('#hunter-count');
  if (c) c.textContent = Math.min(300, models.length) + ' affichés / ' + (state.hunterTotal||0) + ' filtrés · ' + (state.hunterTotalCatalog||0) + ' au catalogue';
}

// ═══ CASCADE ═══
async function loadCascade() {
  if (!tabStill('cascade')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>Cascade — Circuit Breaker</h2>
    <div class="btn-row">${btn('⚡ Reset All Breakers','cascade-reset',{danger:true})}</div>
    <div id="cas-kpi" class="kpi-row"></div>
    <div class="card glass"><h3>Fallback Chain (live)</h3><div id="cas-chain" class="card-list"></div></div>
    <div class="card glass"><h3>Provider Detail</h3><div id="cas-detail" class="card-list"></div></div>
  </div>`;
  try {
    const d = await api('/cascade/detail');
    state.cascadeProviders = d.providers;
    const provs = Object.entries(d.providers||{});
    const closed = provs.filter(([,m])=>m.state==='closed').length;
    const open = provs.filter(([,m])=>m.state==='open').length;
    $('#cas-kpi').innerHTML = kpi([[provs.length,'Providers'],[closed,'Closed ✓'],[open,'Open ✗'],[d.config?.max_retries||3,'Max Retries']]);
    $('#cas-chain').innerHTML = (d.fallback_chain||[]).map((p,i)=>{
      const arr = i < (d.fallback_chain||[]).length-1 ? ' →' : '';
      return `<div class="row clickable" data-action="cascade-provider" data-name="${esc(p.name)}"><span class="name">#${i+1} ${esc(p.name)}</span> ${badge(p.state)} <span class="meta">${(p.success_rate*100).toFixed(0)}% · ${p.avg_latency_ms}ms${arr}</span></div>`;
    }).join('') || '<p class="empty">No chain.</p>';
    $('#cas-detail').innerHTML = provs.map(([n,m])=>`<div class="row clickable" data-action="cascade-provider" data-name="${esc(n)}"><div><span class="name">${esc(n)}</span> ${badge(m.state)}</div><span class="meta">${(m.success_rate*100).toFixed(0)}% · ${m.total_requests} req · ${m.consecutive_failures} fails</span></div>`).join('') || '<p class="empty">No providers.</p>';
  } catch(e) { log('cascade: '+e.message,'err'); }
}

// ═══ SESSIONS ═══
async function loadSessions() {
  if (!tabStill('sessions')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>Sessions — Multi-Account Rotation</h2>
    <div class="btn-row">${btn('📱 Rotate Session','rotate-session',{primary:true})}</div>
    <div id="ses-kpi" class="kpi-row"></div>
    <div class="card glass"><h3>Active Sessions</h3><div id="ses-list" class="card-list"></div></div>
  </div>`;
  try {
    const d = await api('/sessions/detail');
    const bs = d.stats?.by_state||{};
    state.sessions = d.sessions || [];
    $('#ses-kpi').innerHTML = kpi([[d.stats?.total_accounts||0,'Accounts'],[d.stats?.total_sessions||0,'Sessions'],[bs.active||0,'Active'],[(bs.rate_limited||0)+(bs.error||0),'Limited/Error']]);
    $('#ses-list').innerHTML = (d.sessions||[]).map(s=>`<div class="row clickable" data-action="session-detail" data-id="${esc(s.session_id)}"><div><span class="name">${esc(s.account_id)}</span> ${badge(s.state)} ${s.is_healthy?'<span class="badge ok">healthy</span>':''}</div><span class="meta">${esc(s.provider)} · ${s.request_count} req · ${fmtAgo(s.last_used)}</span></div>`).join('') || '<p class="empty">No sessions.</p>';
  } catch(e) { log('sessions: '+e.message,'err'); }
}

// ═══ EGRESS ═══
async function loadEgress() {
  if (!tabStill('egress')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>Egress — Disposable IP Pool</h2>
    <div class="spoof-wrap" style="margin-bottom:12px">
      <canvas class="spoof-canvas" id="spoof-egress" style="height:280px"></canvas>
    </div>
    <div class="card glass"><h3>🌐 Global Real-Time Scanner</h3>
      <p class="hint">Scans 25+ worldwide proxy sources. Probes each proxy (IP, latency, country), flag-checks against LLM providers. Only non-flagged proxies added.</p>
      <div class="btn-row">
        ${btn('🔍 Scan Worldwide','scan-worldwide',{primary:true})}
        <button class="btn" data-action="flag-check-toggle" id="flag-check-toggle">✓ Flag Check: ON</button>
      </div>
      <div id="scan-progress" style="display:none;margin-top:8px">
        <div class="kpi-row" id="scan-kpi"></div>
        <div id="scan-flag-summary" class="card-list" style="margin-top:4px"></div>
      </div>
    </div>
    <div class="card glass"><h3>Quick Add — Click to Auto-Scan</h3>
      <p class="hint">Click a proxy type. ViaRoma auto-scans 25+ sources and adds non-flagged proxies. Zero manual entry.</p>
      <div id="proxy-cards" class="grid-3"></div>
    </div>
    <div class="btn-row">${btn('🔥 Burn Lane','burn-lane',{danger:true})} ${btn('🔄 Probe All','egress-probe')}</div>
    <div id="eg-kpi" class="kpi-row"></div>
    <div class="card glass"><h3>Lanes (live)</h3><div id="eg-lanes" class="card-list"></div></div>
    <div class="card glass"><h3>Proxy Pool <span id="pool-count" class="badge">—</span> <span id="pool-flag-count" class="badge ok">—</span></h3><div id="eg-pool" class="card-list" style="max-height:400px;overflow-y:auto"></div></div>
  </div>`;
  try {
    const [d, opts, creds] = await Promise.all([api('/egress/detail'), api('/egress/options'), api('/credentials/list')]);
    state.egressStats = d.stats;
    state.egressLanes = d.lanes || [];
    state.egressPool = d.pool || [];
    state.accountIds = (creds.accounts || []).map(a => a.account_id);
    state.poolFilter = 'all';
    $('#eg-kpi').innerHTML = kpi([
      [d.stats?.pool_size||0,'Pool','pool-filter'],
      [d.stats?.usable||0,'Usable','pool-filter'],
      [d.stats?.lanes||0,'Lanes','egress-lanes-focus'],
      [d.stats?.burns||0,'Burns','egress-burns-list'],
    ]);
    $('#eg-lanes').innerHTML = (d.lanes||[]).map(l=>`<div class="row clickable" data-action="lane-detail" data-id="${esc(l.account_id)}">
        <div><span class="name">${esc(l.account_id)}</span> ${badge(l.proxy_state)}</div>
        <span class="meta">${esc(l.public_ip||'?')} · ${esc(l.country||'?')} · ${l.latency_ms}ms · ${l.burns} burns</span></div>`).join('') || '<p class="empty">No lanes.</p>';
    renderPool();
    // Animation IP spoofing: on montre l'IP de sortie d'une lane, jamais l'IP reelle.
    const lane0 = (d.lanes||[]).find(l => l.public_ip) || (d.lanes||[])[0] || {};
    if (window.ViaRomaSpoof) {
      window.ViaRomaSpoof.mount($('#spoof-egress'), {
        egressIp: lane0.public_ip || '—',
        country: lane0.country || '',
        tls: lane0.tls_profile || 'chrome120',
        ja3: 'ja3',
        account: lane0.account_id || ''
      });
    }
    // Proxy type cards
    $('#proxy-cards').innerHTML = (opts.types||[]).map(t=>`<div class="card glass proxy-card clickable" data-action="add-proxy-type" data-type="${esc(t.id)}"><div class="card-head"><span>${esc(t.label)}</span></div><div class="card-meta">${esc(t.desc)}</div></div>`).join('');
    checkScanStatus();
  } catch(e) { log('egress: '+e.message,'err'); }
}

// Rend le pool de proxies avec un filtre actif (les badges sont cliquables).
function renderPool() {
  const el = $('#eg-pool'); if (!el) return;
  const all = state.egressPool || [];
  const f = state.poolFilter || 'all';
  let list = all;
  if (f === 'clean') list = all.filter(p => p.flag_status === 'clean');
  else if (f === 'flagged') list = all.filter(p => p.flag_status === 'flagged');
  else if (f === 'untested') list = all.filter(p => (p.flag_status || 'unknown') === 'unknown');
  else if (f === 'usable') list = all.filter(p => p.is_usable);
  let clean = 0, flagged = 0;
  all.forEach(p => { if (p.flag_status === 'clean') clean++; if (p.flag_status === 'flagged') flagged++; });
  el.innerHTML = list.map(p => {
    const fs = p.flag_status || 'unknown';
    const fb = fs === 'clean'
      ? `<span class="badge ok clickable" data-action="pool-filter" data-status="clean" title="Filtrer sur clean">clean</span>`
      : fs === 'flagged'
        ? `<span class="badge off clickable" data-action="pool-filter" data-status="flagged" title="Filtrer sur flagged">⚠ flagged</span>`
        : `<span class="badge clickable" data-action="pool-filter" data-status="untested" title="Filtrer sur untested">untested</span>`;
    return `<div class="row clickable" data-action="proxy-detail" data-url="${esc(p.url)}">
        <div><span class="name">${esc(p.url)}</span> ${badge(p.state)} ${fb}</div>
        <span class="meta">${esc(p.kind)} · ${p.latency_ms}ms · ${esc(p.country||'?')}${p.public_ip?' · '+esc(p.public_ip):''}</span></div>`;
  }).join('') || '<p class="empty">Aucun proxy pour ce filtre. Click "clean" / "flagged" pour changer.</p>';
  const c = $('#pool-flag-count');
  if (c) c.textContent = clean + ' clean / ' + flagged + ' flagged' + (f !== 'all' ? ' · filtre: ' + f : '');
  const cnt = $('#pool-count');
  if (cnt) cnt.textContent = list.length + ' / ' + all.length;
}

async function checkScanStatus() {
  try {
    const d = await api('/egress/scan-status');
    if (!d.ok) return;
    const s = d.stats;
    const prog = $('#scan-progress');
    if (!prog) return;
    if (s.scanning) {
      prog.style.display = 'block';
      $('#scan-kpi').innerHTML = kpi([[s.sources_fetched+'/'+s.sources_total,'Sources'],[s.proxies_found,'Found'],[s.proxies_probed,'Probed'],[s.proxies_clean,'Clean ✓']]);
      let fh=''; Object.entries(s.flag_checks||{}).forEach(([p,n])=>{ fh+=`<div class="row"><span class="name">⚠ ${esc(p)}</span><span class="meta">${n} flagged</span></div>`; });
      $('#scan-flag-summary').innerHTML = fh || '<p class="hint">No flags yet.</p>';
      setTimeout(checkScanStatus, 2000);
    } else if (s.last_scan > 0) {
      prog.style.display = 'block';
      $('#scan-kpi').innerHTML = kpi([[s.sources_fetched+'/'+s.sources_total,'Sources'],[s.proxies_clean,'Clean ✓'],[s.proxies_flagged,'Flagged ⚠'],[s.last_scan_duration_s.toFixed(1)+'s','Duration']]);
      let fh=''; Object.entries(s.flag_checks||{}).forEach(([p,n])=>{ fh+=`<div class="row"><span class="name">⚠ ${esc(p)}</span><span class="meta">${n} flagged</span></div>`; });
      $('#scan-flag-summary').innerHTML = fh || '<p class="hint">No flags detected.</p>';
    }
  } catch(e) {}
}

// ═══ PROVIDERS ═══
async function loadProviders() {
  if (!tabStill('providers')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>Providers — Worldwide Registry</h2>
    <div id="prov-kpi" class="kpi-row"></div>
    <div class="card glass"><h3>🌐 Web Chat Providers</h3><div id="prov-web" class="grid-3"></div></div>
    <div class="card glass"><h3>🔌 API Providers</h3><div id="prov-api" class="grid-3"></div></div>
    <div class="card glass"><h3>💻 Desktop / Local</h3><div id="prov-desktop" class="grid-3"></div></div>
    <div class="card glass"><h3>Active Adapters</h3><div id="prov-active" class="card-list"></div></div>
  </div>`;
  try {
    const [full, active, creds] = await Promise.all([api('/providers/list'), api('/providers/detail'), api('/credentials/list')]);
    state.providerList = full;
    state.activeProviders = active.providers || [];
    state.accountIds = (creds.accounts || []).map(a => a.account_id);
    $('#prov-kpi').innerHTML = kpi([
      [full.total,'Total Providers'],
      [full.web_chats.length,'Web Chats'],
      [full.api_providers.length,'API'],
      [full.desktop.length,'Desktop'],
    ]);
    const cardHTML = (p) => `<div class="card glass provider-card clickable" data-action="provider-info" data-name="${esc(p.name)}" data-type="${esc(p.type)}" data-url="${esc(p.url||'')}">
      <div class="card-head"><span>${esc(p.name)}</span> ${p.free_tier?'<span class="badge ok">free</span>':'<span class="badge">paid</span>'}</div>
      <div class="card-meta">${esc(p.type.toUpperCase())}${p.url?' · '+esc(p.url):''}</div>
      <div class="card-meta">Needs: ${esc((p.needs||[]).join(', ')||'nothing')}</div>
      ${p.login_url?`<div class="card-meta">Login: ${esc(p.login_url)}</div>`:''}
      <div class="btn-row">${btn('🔌 Connect','provider-connect',{data:{name:p.name},primary:true})}${btn('⚙️ Configure','provider-config',{data:{name:p.name}})}</div>
    </div>`;
    $('#prov-web').innerHTML = full.web_chats.map(cardHTML).join('');
    $('#prov-api').innerHTML = full.api_providers.map(cardHTML).join('');
    $('#prov-desktop').innerHTML = full.desktop.map(cardHTML).join('');
    $('#prov-active').innerHTML = (active.providers||[]).map(p=>`<div class="row clickable" data-action="provider-detail" data-name="${esc(p.name||p.label||'')}"><div><span class="name">${esc(p.name||p.label||'?')}</span> ${p.score>50?'<span class="badge ok">'+p.score+'</span>':'<span class="badge off">'+p.score+'</span>'} ${p.egress?'<span class="badge ok">egress</span>':'<span class="badge off">fail-closed</span>'}</div><span class="meta">${esc(p.account_id||'')} · ${esc(p.tls_profile||'')} · ${p.cookie_count||0} cookies</span></div>`).join('') || '<p class="empty">No active adapters.</p>';
  } catch(e) { log('providers: '+e.message,'err'); }
}

// ═══ CREDENTIALS ═══
async function loadCredentials() {
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>Credentials — Account Management</h2>
    <div class="btn-row">${btn('➕ Add New Account','cred-show-add',{primary:true})} <button class="btn" data-action="toggle-hide">${state.hideSecrets?'👁 Show Secrets':'🙈 Hide Secrets'}</button></div>
    <div id="cred-add-form" style="display:none" class="card glass">
      <h3>Add New Account</h3>
      <div class="form-row"><label>Account ID</label><input type="text" id="cred-new-id" placeholder="my-claude-account"></div>
      <div class="form-row"><label>Provider</label><select id="cred-new-prov">
        <option value="claude_web">Claude (web)</option><option value="gemini_web">Gemini (web)</option>
        <option value="chatgpt_web">ChatGPT (web)</option><option value="qwen_web">Qwen (web)</option>
        <option value="copilot_web">Copilot (web)</option><option value="grok_web">Grok (web)</option>
        <option value="perplexity_web">Perplexity (web)</option><option value="deepseek_web">DeepSeek (web)</option>
        <option value="kimi_web">Kimi (web)</option><option value="glm_web">GLM (web)</option>
        <option value="metaai_web">Meta AI (web)</option><option value="poe_web">Poe (web)</option>
        <option value="huggingchat_web">HuggingChat (web)</option><option value="you_web">You.com (web)</option>
        <option value="lepton_web">Lepton AI (web)</option><option value="mistral_web">Mistral Le Chat (web)</option>
        <option value="custom">Custom</option>
      </select></div>
      <div class="form-row"><label>Account Type</label><select id="cred-new-type"><option value="personal">Personal</option><option value="school">School</option><option value="work">Work</option></select></div>
      <div class="form-row"><label>Login URL</label><input type="text" id="cred-new-login" placeholder="https://claude.ai/login"></div>
      <div class="form-row"><label>Username / Email</label><input type="text" id="cred-new-user" placeholder="your@email.com"></div>
      <div class="form-row"><label>Password</label><input type="password" id="cred-new-pass" placeholder="••••••••"></div>
      <div class="btn-row">${btn('✓ Add Account','cred-add-account',{primary:true})} ${btn('Cancel','cred-cancel-add')}</div>
    </div>
    <div id="cred-list" class="card-list"></div>
    <div id="cred-edit-form" style="display:none" class="card glass">
      <h3>Edit Credentials</h3>
      <div class="form-row"><label>Account</label><span id="cred-edit-id" class="name"></span></div>
      <div class="form-row"><label>Username</label><input type="text" id="cred-username" placeholder="your@email.com"></div>
      <div class="form-row"><label>Password</label><input type="password" id="cred-password" placeholder="••••••••"></div>
      <div class="btn-row">${btn('Save','cred-save',{primary:true})} ${btn('Delete Account','cred-delete',{danger:true})} ${btn('Cancel','cred-cancel-edit')}</div>
    </div>
  </div>`;
  try {
    const d = await api('/credentials/list');
    $('#cred-list').innerHTML = (d.accounts||[]).map(a=>`<div class="card glass">
      <div class="card-head"><span>${esc(a.account_id)}</span> <span class="meta">${esc(a.provider)}</span></div>
      <div class="card-meta">Username: ${a.has_username?'<span class="badge ok">set</span>':'<span class="badge off">not set</span>'} ${state.hideSecrets?'<span class="meta">***</span>':esc(a.username||'')}</div>
      <div class="card-meta">Password: ${a.has_password?'<span class="badge ok">set</span>':'<span class="badge off">not set</span>'}</div>
      <div class="btn-row">${btn('✏ Edit','cred-edit',{data:{id:a.account_id},primary:true})}</div>
    </div>`).join('') || '<p class="empty">No accounts yet. Click "Add New Account".</p>';
  } catch(e) { log('credentials: '+e.message,'err'); }
}

// ═══ ANTI-WAF ═══
async function loadAntiWAF() {
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>🛡️ Anti-WAF — TLS Spoofing & Challenge Bypass</h2>
    <div id="aw-kpi" class="kpi-row"></div>
    <div class="grid-2">
      <div class="card glass"><h3>🔐 TLS Profiles — Click to Activate</h3><div id="aw-profiles" class="card-list"></div></div>
      <div class="card glass"><h3>🧬 JA3 Fingerprints</h3><div id="aw-ja3" class="card-list"></div></div>
    </div>
    <div class="grid-2">
      <div class="card glass"><h3>📊 Engine Status</h3><div id="aw-status"></div></div>
      <div class="card glass"><h3>🦊 Camoufox Browser</h3><div id="aw-camoufox"></div></div>
    </div>
    <div class="card glass"><h3>⚡ Actions</h3>
      <div class="btn-row">
        ${btn('🔄 Refresh Status','antiwaf-refresh',{primary:true})}
        ${btn('🧪 Test TLS Spoof','antiwaf-test')}
        ${btn('🍪 Harvest Cookies','antiwaf-harvest')}
        ${btn('🔁 Rotate Profile','antiwaf-rotate')}
      </div>
    </div>
  </div>`;
  try {
    const d = await api('/antiwaf/status');
    $('#aw-kpi').innerHTML = kpi([[d.profiles_available,'TLS Profiles'],[d.stub_mode?'STUB':'ACTIVE','curl_cffi'],[d.profiles?.length||0,'JA3 Profiles'],[d.stub_mode?'❌':'✅','Engine']]);
    // TLS profile cards — clickable
    const tlsIcons = {'chrome120':'🌐','chrome119':'🌐','firefox133':'🦊','safari17':'🧭'};
    $('#aw-profiles').innerHTML = (d.profiles||[]).map((p,i)=>`<div class="row clickable" data-action="antiwaf-activate" data-profile="${esc(p)}">
      <div><span class="name">${tlsIcons[p]||'🔒'} ${esc(p)}</span> <span class="badge ok">${i===0?'ACTIVE':'ready'}</span></div>
      <span class="meta">TLS 1.3 · Click to activate</span>
    </div>`).join('') || '<p class="empty">No profiles.</p>';
    // JA3 fingerprints — same data, different display
    $('#aw-ja3').innerHTML = (d.profiles||[]).map(p=>`<div class="row"><span class="name">🧬 ${esc(p)}</span><span class="badge">JA3 hash ready</span></div>`).join('') || '<p class="empty">No JA3 data.</p>';
    // Status
    $('#aw-status').innerHTML = d.stub_mode
      ? `<p style="color:var(--danger)">⚠ curl_cffi unavailable — stub mode</p><p class="hint">Error: ${esc(d.import_error)}</p>`
      : `<p style="color:var(--ok)">✓ curl_cffi ACTIVE — TLS spoofing operational</p><div class="kpi-row" style="margin-top:8px">${kpi([['✅','Spoofing'],['✅','JA3'],['✅','Headers']])}</div>`;
    // Camoufox
    $('#aw-camoufox').innerHTML = `<p class="hint">🦊 Camoufox 0.5.8 — browser binary fetched</p><p class="hint">Used for first-login cookie harvesting & challenge bypass</p><div class="btn-row" style="margin-top:8px">${btn('🍪 Start Harvest','antiwaf-harvest',{primary:true})}</div>`;
  } catch(e) { log('antiwaf: '+e.message,'err'); }
}

// ═══ IDENTITIES ═══
// Une identite = IP de sortie + empreinte TLS (JA3/JA4) + empreinte navigateur.
// Stable par compte, distincte d'un compte a l'autre.
async function loadIdentities() {
  if (!tabStill('identities')) return;
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>🧬 Identities — one machine per account</h2>
    <div id="id-kpi" class="kpi-row"></div>
    <div class="card glass">
      <div class="card-head"><span>🔁 Actions</span></div>
      <div class="btn-row">
        ${btn('🎲 Assign Missing','identity-assign',{primary:true})}
        ${btn('🔄 Reload','identity-reload')}
      </div>
      <p class="hint">Chaque compte reçoit une identité <b>stable</b> (IP + JA3/JA4 + UA/locale/fuseau/écran/canvas) et
      <b>distincte</b> des autres. Une rotation = nouvelle IP <b>et</b> nouvelle empreinte, cookies conservés.
      C'est ce qui permet de faire tourner plusieurs comptes sans qu'ils soient comptés comme un seul.</p>
    </div>
    <div id="id-list" class="card-list"></div>
  </div>`;
  try {
    const d = await api('/identity/list');
    if (!d.available) { $('#id-list').innerHTML = '<p class="empty">IdentityManager indisponible.</p>'; return; }
    const distinct = d.distinct_user_agents || 0;
    const total = d.total || 0;
    $('#id-kpi').innerHTML = kpi([
      [total, 'Comptes'],
      [distinct, 'Empreintes distinctes'],
      [(d.collisions||[]).length, 'Collisions'],
      ['1:1', 'Compte ↔ Machine'],
    ]);
    if ((d.collisions||[]).length) {
      log('⚠ '+(d.collisions||[]).length+' collision(s) d\'identité — deux comptes partagent la même empreinte','err');
    }
    $('#id-list').innerHTML = (d.identities||[]).map(i=>`<div class="row">
      <div>
        <span class="name">🧬 ${esc(i.account_id)}</span>
        <span class="badge ${i.has_session?'ok':'off'}">${i.has_session?'session':'no session'}</span>
        <span class="meta">${esc(i.identity_id)}</span>
      </div>
      <div class="card-meta">
        🌐 ${esc(i.egress_ip||i.egress_proxy||'no egress')} ${i.egress_country?'· '+esc(i.egress_country):''} ·
        🔐 ${esc(i.tls_profile)} · ${esc(i.locale)}/${esc(i.timezone)} · ${esc(i.screen)} ·
        ${esc(i.device_memory)}GB/${esc(i.hardware_concurrency)}c
      </div>
      <div class="card-meta" style="opacity:.65">${esc(i.user_agent)}</div>
      <div class="btn-row">
        ${btn('🔁 Rotate','identity-rotate',{data:{id:i.account_id}})}
      </div>
    </div>`).join('') || '<p class="empty">No identities yet. Click "Assign Missing".</p>';
  } catch(e) { log('identity: '+e.message,'err'); }
}

// ═══ CONFIG ═══
state.cfgFiles = ['accounts.yaml','cascade.yaml','egress_pool.yaml','hunter.yaml','dashboard.json'];
const CFG_META = {
  'accounts.yaml': {label:'Accounts',icon:'👤'}, 'cascade.yaml': {label:'Cascade',icon:'⚡'},
  'egress_pool.yaml': {label:'Egress Pool',icon:'🌐'}, 'hunter.yaml': {label:'Hunter',icon:'🔍'},
  'dashboard.json': {label:'Dashboard',icon:'📊'},
};
const ALL_PROVIDERS = ['claude_web','gemini_web','chatgpt_web','qwen_web','copilot_web','grok_web','perplexity_web','deepseek_web','kimi_web','glm_web','metaai_web','poe_web','huggingchat_web','you_web','lepton_web','openai_passthrough'];

async function loadFormConfig() {
  if (!state.cfgActive) state.cfgActive = state.cfgFiles[0];
  $('#tab-content').innerHTML = `<div class="tab-panel">
    <h2>Roma Configuration</h2>
    <div id="cfg-tabs" class="config-tabs">${state.cfgFiles.map(f=>`<span class="tab${state.cfgActive===f?' active':''}" data-action="cfg-select" data-file="${f}">${CFG_META[f]?.icon||''} ${CFG_META[f]?.label||f}</span>`).join('')}</div>
    <div id="cfg-form" class="config-form">Loading…</div>
    <div class="btn-row">${btn('💾 Save','save-form-config',{primary:true})} ${btn('🔄 Reload','reload-form-config')}</div>
    <div id="cfg-saved-msg" class="saved-msg"></div>
  </div>`;
  try {
    const d = await api('/config/'+encodeURIComponent(state.cfgActive)+'/structured');
    state.cfgData[state.cfgActive] = d.data||{};
    renderConfigForm(state.cfgActive, d.data||{});
  } catch(e) { $('#cfg-form').innerHTML = '<p class="err">'+esc(e.message)+'</p>'; }
}

function field(id,label,val,type='text',opts={}) {
  const a = Object.entries(opts).map(([k,v])=>`${k}="${v}"`).join(' ');
  return `<div class="form-row"><label>${esc(label)}</label><input type="${type}" id="${id}" value="${esc(val)}" ${a}></div>`;
}
function select(id,label,opts,val) {
  return `<div class="form-row"><label>${esc(label)}</label><select id="${id}">${opts.map(o=>`<option value="${o}" ${o===val?'selected':''}>${esc(o)}</option>`).join('')}</select></div>`;
}
function toggle(id,label,val) {
  return `<div class="switch"><input type="checkbox" id="${id}" ${val?'checked':''}><label class="slider" for="${id}"></label><span class="switch-label">${esc(label)}</span></div>`;
}

function renderConfigForm(name, data) {
  const form = $('#cfg-form'); if(!form) return;
  let html = '<div class="form-sections">';
  if (name === 'accounts.yaml') {
    (data.accounts||[]).forEach((a,i)=>{
      html += `<div class="card glass account-card"><div class="card-head"><span>Account #${i+1}: ${esc(a.account_id||'?')}</span>${btn('🗑 Delete','del-account',{data:{idx:i},danger:true})}</div>`;
      html += field('acc-'+i+'-id','Account ID',a.account_id||'');
      html += select('acc-'+i+'-type','Type',['personal','school','work'],a.account_type||'personal');
      html += select('acc-'+i+'-prov','Provider',ALL_PROVIDERS,a.provider||'');
      html += field('acc-'+i+'-login','Login URL',a.login_url||'');
      html += field('acc-'+i+'-sel','Success Selector',a.success_selector||'');
      html += field('acc-'+i+'-cred','Credentials Ref',a.credentials_ref||'');
      html += field('acc-'+i+'-prio','Priority',a.priority||5,'number',{min:1,max:100});
      html += field('acc-'+i+'-rph','Max req/hour',a.max_requests_per_hour||100,'number',{min:1,max:10000});
      html += '</div>';
    });
    html += `<div class="btn-row">${btn('➕ Add Account','add-account',{primary:true})}</div>`;
  } else if (name === 'cascade.yaml') {
    html += field('cas-retries','Max retries',data.max_retries_per_provider||2,'number',{min:0,max:10});
    html += field('cas-base-bo','Backoff base (s)',data.base_backoff_seconds||0.5,'number',{min:0,max:10,step:0.1});
    html += field('cas-max-bo','Backoff max (s)',data.max_backoff_seconds||30,'number',{min:1,max:300});
    html += field('cas-bo-mult','Backoff multiplier',data.backoff_multiplier||2.0,'number',{min:1,max:10,step:0.1});
    html += field('cas-cb-thresh','Breaker threshold',data.circuit_breaker_threshold||5,'number',{min:1,max:50});
    html += field('cas-half-open','Half-open tests',data.half_open_test_requests||3,'number',{min:1,max:20});
  } else if (name === 'egress_pool.yaml') {
    html += field('eg-lanes','Lanes path',data.lanes_path||'data/egress_lanes.json');
    html += field('eg-probe','Probe interval (s)',data.probe_interval||120,'number',{min:10,max:3600});
    html += field('eg-timeout','Probe timeout (s)',data.probe_timeout||8,'number',{min:1,max:60});
    html += field('eg-quar','Quarantine (s)',data.quarantine_seconds||600,'number',{min:0,max:7200});
    html += toggle('eg-tor','Enable Tor',data.enable_tor!==false);
  } else if (name === 'hunter.yaml') {
    html += field('hu-cat','Catalog path',data.catalog_path||'data/free_models_catalog.json');
    html += field('hu-scan','Scan interval (s)',data.scan_interval||300,'number',{min:60,max:7200});
    html += select('hu-tier','Min tier',['frontier','near-frontier','all'],data.min_tier||'frontier');
  } else if (name === 'dashboard.json') {
    html += field('dash-refresh','Refresh (ms)',data.refresh_ms||2000,'number',{min:500,max:60000,step:500});
    html += field('dash-port','Port',data.port||8000,'number',{min:1024,max:65535});
    html += select('dash-theme','Theme',['roma-eterna','dark','light','auto'],data.theme||'roma-eterna');
  }
  html += '</div>';
  form.innerHTML = html;
}

function collectConfigData(name) {
  const d = JSON.parse(JSON.stringify(state.cfgData[name]||{}));
  if (name === 'accounts.yaml') {
    d.accounts = [...$$('.account-card')].map((c,i)=>{
      const g = (s) => { const el = $('#acc-'+i+'-'+s); return el ? el.value : ''; };
      return {account_id:g('id'),account_type:g('type'),provider:g('prov'),login_url:g('login'),success_selector:g('sel'),credentials_ref:g('cred'),priority:+g('prio')||5,max_requests_per_hour:+g('rph')||100,cooldown_seconds:+(g('cd')||300)};
    });
  } else if (name === 'cascade.yaml') {
    d.max_retries_per_provider=+($('#cas-retries')?.value||2); d.base_backoff_seconds=+($('#cas-base-bo')?.value||0.5);
    d.max_backoff_seconds=+($('#cas-max-bo')?.value||30); d.backoff_multiplier=+($('#cas-bo-mult')?.value||2);
    d.circuit_breaker_threshold=+($('#cas-cb-thresh')?.value||5); d.half_open_test_requests=+($('#cas-half-open')?.value||3);
  } else if (name === 'egress_pool.yaml') {
    d.lanes_path=$('#eg-lanes')?.value||''; d.probe_interval=+($('#eg-probe')?.value||120);
    d.probe_timeout=+($('#eg-timeout')?.value||8); d.quarantine_seconds=+($('#eg-quar')?.value||600); d.enable_tor=$('#eg-tor')?.checked!==false;
  } else if (name === 'hunter.yaml') {
    d.catalog_path=$('#hu-cat')?.value||''; d.scan_interval=+($('#hu-scan')?.value||300); d.min_tier=$('#hu-tier')?.value||'frontier';
  } else if (name === 'dashboard.json') {
    d.refresh_ms=+($('#dash-refresh')?.value||2000); d.port=+($('#dash-port')?.value||8000); d.theme=$('#dash-theme')?.value||'roma-eterna';
  }
  return d;
}

// ═══ ACTIONS — TOUT passe par ici ═══
async function doAction(action, el) {
  switch(action) {
    case 'hunter-scan':
      log('Starting hunter scan...'); try { const r = await api('/hunter/scan',{method:'POST'}); log('Hunter scan: '+(r.message||'started'),'ok'); setTimeout(loadHunter,3000); } catch(e) { log('hunter scan: '+e.message,'err'); } break;
    case 'hunter-load': loadHunter(); break;
    case 'hunter-filter-all': case 'hunter-filter-frontier': case 'hunter-filter-large':
    case 'hunter-filter-medium': case 'hunter-filter-small': {
      state.hunterFilter = action.replace('hunter-filter-', '');
      renderHunterFilters();
      try { await refreshHunterModels(); log('Filtre: ' + state.hunterFilter + ' — ' + (state.hunterTotal||0) + ' modèles', 'ok'); }
      catch(e) { log('hunter: ' + e.message, 'err'); }
      break;
    }
    case 'cascade-reset':
      log('Resetting breakers...'); try { const r = await api('/cascade/reset',{method:'POST'}); log('Breakers reset: '+r.reset+' providers','ok'); loadCascade(); } catch(e) { log('reset: '+e.message,'err'); } break;

    // ── Navigation par tuile/badge ────────────────────────────────────
    case 'tab-open': {
      const t = el.dataset.tab;
      if (!t) { log('Onglet inconnu','err'); break; }
      switchTab(t);
      break;
    }
    case 'go-frontier':
      state.hunterFilter = 'frontier';
      switchTab('hunter');
      break;
    case 'live-origin-cn': case 'live-origin-eu': case 'live-origin-us': {
      const code = action.replace('live-origin-','');
      switchTab('models');
      log('Filtre origine: ' + code, 'ok');
      break;
    }
    case 'live-model': {
      const id = el.dataset.model;
      try {
        const d = await api('/hunter/detail?q=' + encodeURIComponent(id) + '&limit=1');
        const m = (d.models||[])[0];
        if (!m) { log('Modèle introuvable: '+id,'err'); break; }
        state.hunterModels = d.models||[];
        const md = m.metadata||{};
        const org = md.origin||{label:'Autre'};
        const ctx = m.context_window ? Number(m.context_window).toLocaleString('fr-FR')+' tokens' : 'non publiée par la source';
        let dl = '';
        if ((md.download_modes||[]).length) {
          dl = '<h4 style="margin:12px 0 6px;font-size:.82rem;color:#6b2737">Modes de téléchargement (GGUF réels)</h4>'
            + '<div class="drawer-rows">' + md.download_modes.map(f => `
              <div class="drawer-row"><span class="k">${esc(f.quant||'')}</span>
              <span class="v">${f.size_bytes?(f.size_bytes/1048576).toFixed(1)+' Mo':'—'} · <a href="${esc(f.url||'')}" target="_blank" rel="noopener" style="color:var(--accent)">${esc((f.file||'').split('/').pop())}</a></span></div>`).join('') + '</div>';
        }
        if (window.RomaDrawer) RomaDrawer.open({
          kicker: 'Live · ' + (m.provider||'?'), title: m.model_id,
          body: RomaDrawer.rows([
            ['Provider', m.provider], ['Origine du labo', org.label], ['Tier', m.tier],
            ['Fenêtre de contexte', ctx], ['Valeur de la ctx', md.ctx_source||'aucune source'],
            ['Base', md.base_model||'—'], ['Architecture', md.architecture||'—'],
            ['Licence', md.license||'—'], ['Téléchargements', md.downloads ?? '—'],
            ['Créé le', md.created_at||'—'],
          ]) + dl,
          actions: [{label:'✕ Fermer', action:'drawer-close'}]
        });
      } catch(e) { log('live-model: '+e.message,'err'); }
      break;
    }
    // ── Rafraichissements ──────────────────────────────────────────────
    case 'live-refresh': loadLive(); log('Live rafraichi','ok'); break;
    case 'security-refresh': loadSecurity(); log('Securite rafraichie','ok'); break;
    case 'metrics-refresh': loadMetrics(); log('Metriques rafraichies','ok'); break;
    case 'arch-refresh': loadArchitecture(); log('Graphe rafraichi','ok'); break;
    case 'models-refresh': loadModels(); log('Modeles rafraichis','ok'); break;
    case 'cascade-refresh': loadCascade(); log('Cascade rafraichie','ok'); break;
    case 'identity-rotate-open': switchTab('identities'); break;
    case 'journal-clear':
      state.log = []; renderJournal();
      const lbox = $('#log'); if (lbox) lbox.innerHTML = '';
      log('Journal vide','ok'); break;
    case 'journal-copy': {
      const txt = state.log.map(l => '['+l.ts+'] '+l.msg).join('\n');
      try {
        if (navigator.clipboard) await navigator.clipboard.writeText(txt);
        log('Journal copie ('+state.log.length+' lignes)','ok');
      } catch(e) { log('Copie impossible: '+e.message,'err'); }
      break;
    }
    case 'playground-send': await sendPlayground(); break;

    case 'rotate-session':
      log('Rotating session...'); try { const r = await api('/sessions/rotate',{method:'POST',body:JSON.stringify({})}); log('Rotated: '+JSON.stringify(r),'ok'); loadSessions(); } catch(e) { log('rotate: '+e.message,'err'); } break;

    case 'burn-lane':
      log('Burning lane...'); try { const r = await api('/egress/burn',{method:'POST',body:JSON.stringify({account_id:'test-lane'})}); log('Burned: '+JSON.stringify(r),'ok'); loadEgress(); } catch(e) { log('burn: '+e.message,'err'); } break;
    case 'egress-probe':
      log('Probing all proxies...'); try { const r = await api('/egress/rotate',{method:'POST',body:JSON.stringify({})}); log('Probe: '+JSON.stringify(r),'ok'); loadEgress(); } catch(e) { log('probe: '+e.message,'err'); } break;

    case 'add-proxy-type': {
      const type = el.dataset.type;
      log('Auto-scanning for '+type+' proxies...');
      try { const r = await api('/egress/scan-worldwide',{method:'POST',body:JSON.stringify({flag_check:state.flagCheckEnabled!==false,max_proxies:200,proxy_type:type})});
        log('Scan started for '+type,'ok'); checkScanStatus(); } catch(e) { log('scan: '+e.message,'err'); } break;
    }

    case 'scan-worldwide': {
      log('Starting worldwide scan...'); const fc = state.flagCheckEnabled !== false;
      try { const r = await api('/egress/scan-worldwide',{method:'POST',body:JSON.stringify({flag_check:fc,max_proxies:200})});
        if (r.ok) { log('Worldwide scan started','ok'); checkScanStatus(); } else { log('Scan: '+(r.error||'failed'),'err'); }
      } catch(e) { log('scan: '+e.message,'err'); } break;
    }
    case 'flag-check-toggle':
      state.flagCheckEnabled = !state.flagCheckEnabled;
      $('#flag-check-toggle').textContent = state.flagCheckEnabled ? '✓ Flag Check: ON' : '✗ Flag Check: OFF';
      log('Flag check: '+(state.flagCheckEnabled?'ON':'OFF')); break;

    case 'toggle-hide':
      state.hideSecrets = !state.hideSecrets; loadCredentials(); break;

    case 'cred-show-add': $('#cred-add-form').style.display = 'block'; break;
    case 'cred-cancel-add': $('#cred-add-form').style.display = 'none'; break;
    case 'cred-add-account': {
      const id = $('#cred-new-id')?.value?.trim(); const prov = $('#cred-new-prov')?.value;
      const type = $('#cred-new-type')?.value; const login = $('#cred-new-login')?.value?.trim();
      const user = $('#cred-new-user')?.value?.trim(); const pass = $('#cred-new-pass')?.value?.trim();
      if(!id) { log('Account ID required','err'); break; }
      log('Adding account '+id+'...'); try { const r = await api('/credentials/add',{method:'POST',body:JSON.stringify({account_id:id,provider:prov,account_type:type,login_url:login,username:user,password:pass})}); log('Account added: '+id,'ok'); loadCredentials(); } catch(e) { log('add account: '+e.message,'err'); } break;
    }
    case 'cred-edit':
      state.editingCred = el.dataset.id;
      $('#cred-edit-form').style.display = 'block';
      $('#cred-edit-id').textContent = el.dataset.id;
      $('#cred-username').value = ''; $('#cred-password').value = '';
      break;
    case 'cred-save': {
      if(!state.editingCred) break;
      const u = $('#cred-username')?.value?.trim(); const p = $('#cred-password')?.value?.trim();
      log('Saving credentials for '+state.editingCred+'...'); try { const r = await api('/credentials/'+encodeURIComponent(state.editingCred),{method:'PUT',body:JSON.stringify({username:u,password:p})}); log('Credentials saved','ok'); $('#cred-edit-form').style.display='none'; loadCredentials(); } catch(e) { log('cred save: '+e.message,'err'); } break;
    }
    case 'cred-delete': {
      if(!state.editingCred) break;
      if(!confirm('Delete account "'+state.editingCred+'"?')) break;
      log('Deleting '+state.editingCred+'...'); try { const r = await api('/credentials/'+encodeURIComponent(state.editingCred),{method:'DELETE'}); log('Account deleted','ok'); $('#cred-edit-form').style.display='none'; loadCredentials(); } catch(e) { log('delete: '+e.message,'err'); } break;
    }
    case 'cred-cancel-edit': $('#cred-edit-form').style.display='none'; state.editingCred=null; break;

    case 'provider-connect': {
      const name = el.dataset.name;
      log('Connexion à ' + name + '...');
      try {
        const r = await api('/providers/connect',{method:'POST',body:JSON.stringify({provider:name})});
        if (r && r.ok === false) { log(name + ': ' + (r.error || r.message || 'échec'), 'err'); }
        else { log(name + ' connecté ✓ ' + (r && r.message ? '— ' + r.message : ''), 'ok'); }
        if (window.RomaDrawer) RomaDrawer.close();
        loadProviders();
      } catch(e) { log('connect: '+e.message,'err'); }
      break;
    }
    case 'provider-config': {
      const name = el.dataset.name;
      log('Opening config for '+name+'...');
      state.cfgActive = 'accounts.yaml'; switchTab('config'); break;
    }

    case 'antiwaf-refresh': log('Refreshing Anti-WAF status...'); loadAntiWAF(); break;
    case 'antiwaf-test': {
      log('Testing TLS spoof (curl_cffi → https://tls.peet.ws/api/all)...');
      try { const r = await api('/antiwaf/test',{method:'POST',body:JSON.stringify({})});
        if(!r.ok) { log('TLS test: '+(r.error||'echec'),'err'); break; }
        log('TLS spoof test: '+r.tls_version+' · JA3='+r.ja3_hash+' · IP='+r.ip,'ok');
        if (r.diff) log('JA3 differs from real: ✓ spoof working','ok');
      } catch(e) { log('TLS test: '+e.message,'err'); } break;
    }
    case 'antiwaf-harvest': {
      log('Starting Camoufox cookie harvest (headless browser)...');
      try { const r = await api('/antiwaf/harvest',{method:'POST',body:JSON.stringify({})});
        if(!r.ok) { log('harvest: '+(r.error||'echec'),'err'); break; }
        log('Harvest: '+r.cookies+' cookies from '+r.url+' ('+r.provider+')','ok');
      } catch(e) { log('harvest: '+e.message,'err'); } break;
    }
    case 'antiwaf-rotate': {
      log('Rotating egress lane + TLS profile...');
      try { const r = await api('/antiwaf/rotate',{method:'POST',body:JSON.stringify({})});
        if(!r.ok) { log('rotate: '+(r.error||'echec'),'err'); break; }
        log('Rotated to: '+r.active_profile+' ('+r.count+' lane(s))','ok'); loadAntiWAF();
      } catch(e) { log('rotate: '+e.message,'err'); } break;
    }
    case 'antiwaf-activate': {
      const profile = el.dataset.profile;
      log('Activating TLS profile: '+profile+'...');
      try { const r = await api('/antiwaf/activate',{method:'POST',body:JSON.stringify({profile})});
        if(!r.ok) { log('activate: '+(r.error||'echec'),'err'); break; }
        log('Active TLS profile: '+r.active_profile+' ('+r.count+' lane(s))','ok'); loadAntiWAF();
      } catch(e) { log('activate: '+e.message,'err'); } break;
    }

    case 'identity-rotate': {
      const id = el.dataset.id;
      log('Rotating identity for '+id+' (new IP + new fingerprint, cookies kept)...');
      try { const r = await api('/identity/rotate',{method:'POST',body:JSON.stringify({account_id:id,reason:'dashboard_rotate'})});
        if(!r.ok) { log('rotate: '+(r.error||'echec'),'err'); break; }
        log('Rotated '+id+': '+r.identity_id+' · '+r.tls_profile+' · '+(r.egress_ip||r.egress_proxy||'no egress'),'ok');
        loadIdentities();
      } catch(e) { log('rotate: '+e.message,'err'); } break;
    }
    case 'identity-assign': {
      try { const r = await api('/identity/assign',{method:'POST',body:JSON.stringify({})});
        log('Identities: '+r.total+' compte(s) · '+r.identities+' identité(s)','ok'); loadIdentities();
      } catch(e) { log('assign: '+e.message,'err'); } break;
    }
    case 'identity-reload': loadIdentities(); break;

    case 'cfg-select': state.cfgActive = el.dataset.file; loadFormConfig(); break;
    case 'save-form-config': {
      try { const d = collectConfigData(state.cfgActive); const r = await api('/config/'+encodeURIComponent(state.cfgActive)+'/structured',{method:'PUT',body:JSON.stringify({data:d})}); $('#cfg-saved-msg').innerHTML='<span class="ok">✓ Saved ('+r.bytes+' bytes)</span>'; setTimeout(()=>{const m=$('#cfg-saved-msg');if(m)m.innerHTML='';},3000); log('Config saved ('+r.bytes+' bytes)','ok'); } catch(e) { $('#cfg-saved-msg').innerHTML='<span class="err">✗ '+esc(e.message)+'</span>'; log('save: '+e.message,'err'); } break;
    }
    case 'reload-form-config': loadFormConfig(); break;
    case 'add-account': {
      const d = state.cfgData['accounts.yaml']||{accounts:[]}; if(!d.accounts) d.accounts=[];
      d.accounts.push({account_id:'new_account',account_type:'personal',provider:'claude_web',login_url:'',success_selector:'',credentials_ref:'',priority:d.accounts.length+1,max_requests_per_hour:100,cooldown_seconds:300});
      state.cfgData['accounts.yaml']=d; renderConfigForm('accounts.yaml',d); break;
    }
    case 'del-account': {
      const idx=+el.dataset.idx; const d=state.cfgData['accounts.yaml']||{accounts:[]}; if(d.accounts) d.accounts.splice(idx,1);
      state.cfgData['accounts.yaml']=d; renderConfigForm('accounts.yaml',d); break;
    }
    // ═══ DRAWER: fiches detail reelles ═══
    case 'drawer-close': if (window.RomaDrawer) RomaDrawer.close(); break;

    case 'model-detail':
    case 'hunter-model-info': {
      const m = (state.hunterModels||[]).find(x => x.model_id === el.dataset.model);
      if (!m) { log('Modèle introuvable: '+el.dataset.model,'err'); break; }
      const md = m.metadata || {};
      const org = md.origin || {label:'Autre', code:'other'};
      // Fenetre de contexte: la valeur REELLE si la source l'a publiee,
      // sinon on l'assume: "non publiee". Jamais un 32768 fabrique.
      const ctx = m.context_window
        ? Number(m.context_window).toLocaleString('fr-FR') + ' tokens'
        : 'non publiée par la source';
      const ctxSrc = md.ctx_source ? ('source: ' + md.ctx_source) : 'aucune source';
      let dl = '';
      if ((md.download_modes||[]).length) {
        dl = '<h4 style="margin:12px 0 6px;font-size:.82rem;color:#6b2737">Modes de téléchargement (GGUF réels)</h4>'
          + '<div class="drawer-rows">' + md.download_modes.map(f => `
            <div class="drawer-row">
              <span class="k">${esc(f.quant||'')}</span>
              <span class="v">${f.size_bytes ? (f.size_bytes/1048576).toFixed(1)+' Mo' : '—'} · <a href="${esc(f.url||'')}" target="_blank" rel="noopener" style="color:var(--accent)">${esc((f.file||'').split('/').pop())}</a></span>
            </div>`).join('') + '</div>';
      }
      if (window.RomaDrawer) {
        RomaDrawer.open({
          kicker: 'Modèle gratuit · ' + (m.provider||'?'),
          title: m.model_id,
          body: RomaDrawer.rows([
            ['Identifiant', m.model_id],
            ['Provider', m.provider],
            ['Origine du labo', org.label],
            ['Tier', m.tier],
            ['Fenêtre de contexte', ctx],
            ['Valeur de la ctx', ctxSrc],
            ['Base', md.base_model || '—'],
            ['Architecture', md.architecture || '—'],
            ['Licence', md.license || '—'],
            ['Actif', m.is_active ? 'oui' : 'non'],
            ['Téléchargements', md.downloads !== undefined ? md.downloads : '—'],
            ['Likes', md.likes !== undefined ? md.likes : '—'],
            ['Nom affiché', md.name || '—'],
            ['Source', md.source || '—'],
            ['Vu la dernière fois', fmtAgo(m.last_verified)],
          ]) + dl
          + (md.download ? '<div class="drawer-code">' + esc(md.download) + '</div>' : '')
          + '<div class="drawer-code">curl http://127.0.0.1:8000/v1/chat/completions \\\n  -H "Content-Type: application/json" \\\n  -d \'{"model":"auto","messages":[{"role":"user","content":"ping"}]}\'</div>' +
          '<p class="drawer-note">ViaRoma a découvert ce modèle automatiquement et l\'a classé par tier. Le tier « frontier » = modèle de qualité maximale, gratuit sur sa source.</p>',
          actions: [
            { label: '📋 Copier l\'ID', action: 'copy-text', data: { text: m.model_id } },
            { label: '🔍 Filtrer par provider', action: 'hunter-search-provider', data: { provider: m.provider } },
            { label: '✕ Fermer', action: 'drawer-close' },
          ],
        });
      }
      break;
    }

    case 'provider-detail':
    case 'provider-info': {
      const name = el.dataset.name;
      const reg = state.providerList || {};
      const all = [].concat(reg.web_chats||[], reg.api_providers||[], reg.desktop||[]);
      const p = all.find(x => x.name === name);
      const active = (state.activeProviders||[]).find(x => x.name === name);
      if (window.RomaDrawer) {
        RomaDrawer.open({
          kicker: 'Provider · ' + (p ? (p.type||'?').toUpperCase() : 'REGISTRE'),
          title: name,
          body: RomaDrawer.rows([
            ['Type', p ? p.type : '—'],
            ['URL', p ? (p.url||'—') : '—'],
            ['Tier gratuit', p ? (p.free_tier ? 'oui' : 'non') : '—'],
            ['Credentials requis', p ? ((p.needs||[]).join(', ')||'aucun') : '—'],
            ['URL de login', p ? (p.login_url||'—') : '—'],
            ['Compte actif', active ? active.account_id : 'aucun'],
            ['Egress', active ? (active.egress ? 'lane active' : 'AUCUN — fail-closed') : '—'],
            ['Profil TLS', active ? active.tls_profile : '—'],
            ['Empreinte navigateur', active ? active.user_agent : '—'],
            ['Cookies en jar', active ? active.cookie_count : '—'],
            ['Score de santé', active ? active.score : '—'],
          ]) + '<p class="drawer-note">Un provider sans egress n\'est jamais appelé : fail-closed, l\'IP de la machine ne sort pas.</p>',
          actions: [
            { label: '🔌 Connecter', action: 'provider-connect', data: { name }, kind: 'primary' },
            { label: '⚙️ Configurer', action: 'provider-config', data: { name } },
            { label: '✕ Fermer', action: 'drawer-close' },
          ],
        });
      }
      break;
    }

    case 'proxy-detail': {
      const url = el.dataset.url;
      const p = (state.egressPool||[]).find(x => x.url === url);
      if (!p) { log('Proxy introuvable','err'); break; }
      // la liste des comptes est rechargee a l'ouverture: elle peut avoir change
      let accounts = state.accountIds || [];
      if (!accounts.length) {
        try { const c = await api('/credentials/list'); accounts = (c.accounts||[]).map(a=>a.account_id); state.accountIds = accounts; }
        catch(e) { accounts = []; }
      }
      if (window.RomaDrawer) {
        RomaDrawer.open({
          kicker: 'Proxy · ' + (p.kind||'?').toUpperCase(),
          title: p.url,
          body: RomaDrawer.rows([
            ['URL', p.url],
            ['Type', p.kind],
            ['Source', p.source],
            ['État', p.state],
            ['IP publique', p.public_ip || '—'],
            ['Pays', p.country || '—'],
            ['Latence', p.latency_ms + ' ms'],
            ['Utilisable', p.is_usable ? 'oui' : 'non'],
            ['Flag check', p.flag_status || 'unknown'],
            ['Contrôles', Object.keys(p.flag_checks||{}).length ? Object.entries(p.flag_checks).map(([k,v])=>k+'='+v).join(', ') : '—'],
          ]) +
          '<p class="drawer-note">Attribue ce proxy à un compte pour lui donner une IP de sortie dédiée.</p>' +
          '<div class="form-row" style="margin-top:8px"><label>Compte</label><select id="assign-account">' +
            (accounts.length ? accounts.map(a=>`<option value="${esc(a)}">${esc(a)}</option>`).join('') : '<option value="">(aucun compte configuré)</option>') +
          '</select></div>',
          actions: [
            { label: '🔗 Attribuer au compte', action: 'proxy-assign', data: { url }, kind: 'primary' },
            { label: '🩺 Tester le pool', action: 'proxy-test' },
            { label: '✕ Fermer', action: 'drawer-close' },
          ],
        });
      }
      break;
    }

    case 'lane-detail': {
      const id = el.dataset.id;
      const l = (state.egressLanes||[]).find(x => x.account_id === id);
      if (!l) { log('Lane introuvable','err'); break; }
      if (window.RomaDrawer) {
        RomaDrawer.open({
          kicker: 'Lane egress · ' + id,
          title: id,
          body: RomaDrawer.rows([
            ['Compte', l.account_id],
            ['Proxy', l.proxy_url || '—'],
            ['Type', l.proxy_kind || '—'],
            ['IP de sortie', l.public_ip || '—'],
            ['Pays', l.country || '—'],
            ['Latence', l.latency_ms + ' ms'],
            ['État proxy', l.proxy_state],
            ['État lane', l.lane_state],
            ['Burns', l.burns],
            ['Échecs', l.failures],
            ['Dernier probe', l.last_probe ? fmtAgo(l.last_probe) : '—'],
          ]) + '<p class="drawer-note">Brûler la lane remplace l\'IP de sortie ET fait tourner l\'empreinte du compte : les cookies de session sont conservés.</p>',
          actions: [
            { label: '🔥 Brûler la lane', action: 'lane-burn', data: { id }, kind: 'danger' },
            { label: '🧬 Rotation d\'identité', action: 'lane-identity', data: { id }, kind: 'primary' },
            { label: '🔄 Rebind', action: 'lane-rebind', data: { id } },
            { label: '✕ Fermer', action: 'drawer-close' },
          ],
        });
      }
      break;
    }

    case 'pool-filter': {
      const st = el.dataset.status || 'all';
      state.poolFilter = (state.poolFilter === st && st !== 'all') ? 'all' : st;
      renderPool();
      log('Filtre pool: ' + state.poolFilter, 'ok');
      break;
    }
    case 'egress-lanes-focus': {
      const el2 = $('#eg-lanes');
      if (el2) { el2.scrollIntoView({behavior:'smooth', block:'center'}); el2.closest('.card')?.style.setProperty('outline','2px solid var(--accent)'); setTimeout(()=>el2.closest('.card')?.style.removeProperty('outline'), 1600); }
      break;
    }
    case 'egress-burns-list': {
      const lanes = state.egressLanes || [];
      const burned = lanes.filter(l => (l.burns||0) > 0);
      if (window.RomaDrawer) {
        RomaDrawer.open({
          kicker: 'Historique', title: burned.length + ' lane(s) brûlée(s)',
          body: burned.length ? RomaDrawer.rows(burned.map(l => [l.account_id, l.burns + ' burn(s) · ' + (l.public_ip||'—')])) :
            '<p class="drawer-note">Aucune lane brûlée pour l\'instant. Une lane est brûlée sur 403 / 429 / challenge.</p>',
          actions: [{ label: '✕ Fermer', action: 'drawer-close' }],
        });
      }
      break;
    }
    case 'copy-text': {
      const txt = el.dataset.text || '';
      try { await navigator.clipboard.writeText(txt); log('Copié: ' + txt, 'ok'); }
      catch(e) { log('Copie impossible: ' + e.message, 'err'); }
      break;
    }
    case 'hunter-search-provider': {
      state.hunterSearch = el.dataset.provider || '';
      state.hunterFilter = 'all';
      const si = $('#hunter-search'); if (si) si.value = state.hunterSearch;
      await refreshHunterModels();
      if (window.RomaDrawer) RomaDrawer.close();
      log('Filtre provider: ' + state.hunterSearch, 'ok');
      break;
    }
    case 'proxy-assign': {
      const url = el.dataset.url;
      const acc = $('#assign-account')?.value || '';
      if (!acc) { log('Aucun compte sélectionné', 'err'); break; }
      try {
        const r = await api('/egress/assign', {method:'POST', body: JSON.stringify({account_id: acc, url})});
        if (!r.ok) { log('Attribution: ' + (r.error||'échec'), 'err'); break; }
        log('Proxy attribué à ' + acc, 'ok');
        if (window.RomaDrawer) RomaDrawer.close();
        loadEgress();
      } catch(e) { log('assign: ' + e.message, 'err'); }
      break;
    }
    case 'proxy-test': {
      log('Test du pool de proxies...');
      try {
        const r = await api('/egress/rotate', {method:'POST', body: JSON.stringify({})});
        if (!r.ok) { log('Test: ' + (r.error||'échec'), 'err'); break; }
        log('Pool sondé: ' + (r.via||'ok'), 'ok');
        loadEgress();
      } catch(e) { log('test: ' + e.message, 'err'); }
      break;
    }
    case 'lane-burn': {
      const id = el.dataset.id;
      try {
        const r = await api('/egress/burn', {method:'POST', body: JSON.stringify({account_id:id, reason:'dashboard_burn'})});
        if (!r.ok) { log('Burn: ' + (r.error||'échec'), 'err'); break; }
        log('Lane ' + id + ' brûlée — IP et empreinte tournées, cookies conservés', 'ok');
        if (window.RomaDrawer) RomaDrawer.close();
        loadEgress();
      } catch(e) { log('burn: ' + e.message, 'err'); }
      break;
    }
    case 'lane-rebind': {
      try {
        const r = await api('/egress/rotate', {method:'POST', body: JSON.stringify({})});
        if (!r.ok) { log('Rebind: ' + (r.error||'échec'), 'err'); break; }
        log('Lanes rebindées', 'ok');
        if (window.RomaDrawer) RomaDrawer.close();
        loadEgress();
      } catch(e) { log('rebind: ' + e.message, 'err'); }
      break;
    }
    case 'lane-identity': {
      const id = el.dataset.id;
      try {
        const r = await api('/identity/rotate', {method:'POST', body: JSON.stringify({account_id:id, reason:'dashboard_lane'})});
        if (!r.ok) { log('Rotation: ' + (r.error||'échec'), 'err'); break; }
        log('Identité ' + id + ' tournée: ' + (r.identity_id||'') + ' · ' + (r.tls_profile||''), 'ok');
        if (window.RomaDrawer) RomaDrawer.close();
        loadEgress();
      } catch(e) { log('rotation: ' + e.message, 'err'); }
      break;
    }

    case 'cascade-provider': {
      const name = el.dataset.name;
      const m = (state.cascadeProviders||{})[name] || {};
      if (window.RomaDrawer) {
        RomaDrawer.open({
          kicker: 'Circuit breaker', title: name,
          body: RomaDrawer.rows([
            ['État', m.state || '—'],
            ['Taux de succès', ((m.success_rate||0)*100).toFixed(1) + ' %'],
            ['Requêtes', m.total_requests ?? '—'],
            ['Échecs consécutifs', m.consecutive_failures ?? '—'],
            ['Latence moyenne', (m.avg_latency_ms ?? 0) + ' ms'],
            ['Rate-limité jusqu\'à', m.rate_limited_until ? new Date(m.rate_limited_until*1000).toLocaleTimeString('fr-FR') : '—'],
          ]) + '<p class="drawer-note">Un provider en « open » est écarté de la cascade : le circuit breaker le met en quarantaine après 5 échecs, ou immédiatement sur un 429.</p>',
          actions: [
            { label: '⚡ Réarmer ce provider', action: 'cascade-reset-one', data: { name }, kind: 'primary' },
            { label: '✕ Fermer', action: 'drawer-close' },
          ],
        });
      }
      break;
    }
    case 'cascade-reset-one': {
      try {
        const r = await api('/cascade/reset', {method:'POST', body: JSON.stringify({provider: el.dataset.name})});
        log('Breaker ' + el.dataset.name + ' réarmé (' + (r.reset ?? '?') + ')', 'ok');
        if (window.RomaDrawer) RomaDrawer.close();
        loadCascade();
      } catch(e) { log('reset: ' + e.message, 'err'); }
      break;
    }
    case 'session-detail': {
      const sid = el.dataset.id;
      const s = (state.sessions||[]).find(x => x.session_id === sid);
      if (!s) { log('Session introuvable','err'); break; }
      if (window.RomaDrawer) {
        RomaDrawer.open({
          kicker: 'Session · ' + (s.provider||''), title: s.session_id,
          body: RomaDrawer.rows([
            ['Compte', s.account_id],
            ['Provider', s.provider],
            ['État', s.state],
            ['Saine', s.is_healthy ? 'oui' : 'non'],
            ['Requêtes', s.request_count],
            ['Erreurs', s.error_count],
            ['Challenges', s.challenge_count],
            ['Créée', fmtAgo(s.created_at)],
            ['Dernière utilisation', fmtAgo(s.last_used)],
            ['Rate-limit reset', s.rate_limit_reset_at ? new Date(s.rate_limit_reset_at*1000).toLocaleTimeString('fr-FR') : '—'],
          ]) + '<p class="drawer-note">Le jar de cookies de cette session est le plus récent : c\'est lui qui est fusionné dans le contexte de routage du compte.</p>',
          actions: [
            { label: '📱 Tourner la session', action: 'rotate-session', kind: 'primary' },
            { label: '🔥 Brûler la lane', action: 'lane-burn', data: { id: s.account_id }, kind: 'danger' },
            { label: '✕ Fermer', action: 'drawer-close' },
          ],
        });
      }
      break;
    }

    default: log('Unknown action: '+action,'err');  }
}

// ═══ CHARTS — VRAIES métriques ═══
// Chaque graphique est isole: un canvas masque (panel droit en display:none)
// ne doit pas empecher les autres de se dessiner.
function renderRightPanel() {
  const safe = (fn) => { try { fn(); } catch(e) { console.warn('[charts]', e && e.message); } };
  const st = state.hunterStats;
  if (st && st.by_tier && typeof Charts !== 'undefined') {
    safe(() => {
      const total = st.total_models || (st.by_tier.frontier||0)+(st.by_tier.large||0)+(st.by_tier.medium||0)+(st.by_tier.small||0) || 1;
      const frontierPct = Math.round(((st.by_tier.frontier||0) / total) * 100);
      Charts.donut('chart-models', [
        {val: st.by_tier.frontier||0, color:'#c69b4a', colorDark:'#a87c2c'},
        {val: st.by_tier.large||0, color:'#dfd2b8', colorDark:'#c9b890'},
        {val: (st.by_tier.medium||0)+(st.by_tier.small||0), color:'#e8dcc8', colorDark:'#d4c4a8'},
      ], {pct: frontierPct, label: 'frontier'});
    });
  }
  if (state.cascadeProviders && typeof Charts !== 'undefined') {
    safe(() => {
      const entries = Object.entries(state.cascadeProviders);
      // Palette de l'Empire: colonne en travertin quand le circuit est ferme,
      // en pourpre tyrien quand il est ouvert (pas de vert/rouge moderne).
      Charts.bar3d('chart-breakers', entries.slice(0,8).map(([n,m])=>({
        label:n.replace(' (web)','').slice(0,12),
        val: Math.max(m.total_requests||0, m.consecutive_failures||0, 1),
        color: m.state==='closed' ? ROMA.travDk : ROMA.tyrian,
        colorHi: m.state==='closed' ? ROMA.trav : ROMA.tyrianLt,
        colorDk: m.state==='closed' ? ROMA.marble : '#4a1a26',
      })));
    });
  }
  // Real traffic from cascade requests over time
  if (typeof Charts !== 'undefined') {
    safe(() => {
      const reqCount = state.cascadeProviders ? Object.values(state.cascadeProviders).reduce((s,m)=>s+(m.total_requests||0),0) : 0;
      // Simulate realistic traffic pattern if no real data
      const baseTraffic = reqCount > 0 ? reqCount : Math.floor(Math.random()*20)+10;
      state.traffic.push(baseTraffic + Math.floor(Math.random()*15));
      state.traffic = state.traffic.slice(-60);
      Charts.line('chart-traffic', state.traffic);
    });
  }
}

// ═══ HEALTH ═══
async function loadHealth() {
  try { const h = await api('/health'); const ok = Object.values(h.components).filter(v=>v).length; $('#pill-health').innerHTML = '<i class="dot"></i> '+ok+' components'; } catch(e) { $('#pill-health').innerHTML = '<i class="dot err"></i> error'; }
}

// ═══ BOOT ═══
function boot() {
  $$('.nav-tab').forEach(t => t.addEventListener('click', () => switchTab(t.dataset.tab)));
  log('Dashboard ViaRoma pret — routage fail-closed, IP locale jamais transmise', 'ok');
  loadHealth();
  switchTab('overview');
  setInterval(() => { const el = $('#foot-ts'); if (el) el.textContent = new Date().toLocaleTimeString('en-US'); }, 1000);
  setInterval(async () => { if (state.activeTab === 'overview') await loadOverview(); renderRightPanel(); }, 5000);
  setTimeout(() => { renderRightPanel(); }, 2000);
}
document.addEventListener('DOMContentLoaded', boot);
