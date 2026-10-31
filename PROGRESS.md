# PROGRESS — ViaRoma

> **Status: ALPHA — no release — active development.**
> Every line below was checked by running the code on **2026-10-31**, not inferred from intent.
> This file is the honest ledger: what is proven, what is broken, what is missing.

---

## 🟢 Verified by execution

| Domain | Proof | Where |
|---|---|---|
| **Fail-closed (no IP leak)** | No provider is called without an egress proxy. 5 automated levels: structure, curl_cffi transport, aiohttp transport, target ≠ proxy, local IP absent from repo/lanes/logs. | `tests/test_ip_leak.py` |
| **Cascade / circuit breaker** | 403/429 → lane burn, account survives, exponential backoff, breaker open/closed, `cascade.yaml` mapping honoured. | `tests/test_burn_chain.py` |
| **Identities** | One stable and distinct browser fingerprint per account, propagated up to the TLS layer. | `tests/test_identity.py` |
| **MCP server** | 5 tools exposed, stdout reserved for JSON-RPC, no credential value in any response, no traceback on the stdout channel. | `tests/test_mcp_server.py` |
| **Routing security** | TLS profile, cookies and credentials resolved per provider; a YAML account without a proxy never goes live. | `tests/test_security_context.py` |
| **Secrets** | `data/creds/` gitignored, `credentials_ref: env:VAR \| file:path`, scanner OK (**80 files, 12 signatures**), pre-commit hook + CI check. | `scripts/scan_secrets.mjs` |
| **Packaging** | PyPI wheel builds and installs (54 entries, `src/` + `static/vendor/three` included). npm package assembled by `scripts/prepack.mjs`. | CI, `scripts/verify_wheel.py` |
| **Catalog** | Real metrics only — a context window is either taken from the source or flagged "not published by source"; provenance is traced. | `src/hunter/hunter.py` |
| **Dashboard** | 17 tabs, 47 API endpoints, every action issues a real API call. | `src/dashboard/` |

**5 suites · 142 checks · green on the last run (2026-10-31).**

---

## 🐛 Open bugs — full diagnostic (2026-10-31)

### P0 — blocking: the product cannot complete a single request

| # | Bug | Evidence | Impact |
|---|---|---|---|
| **P0-1** | **`NameError: name 'logger' is not defined`** in `src/sessions/session_manager.py:223`. The module has no `import logging` and no `logger = logging.getLogger(__name__)` (every other module has it). | `python -c "import src.sessions.session_manager as m; print(hasattr(m,'logger'))"` → `False`; `tests/test_mcp_server.py` prints `ERROR: harvest impossible: name 'logger' is not defined`. | **Every** account connection dies on the fail-closed path — MCP `connect_provider` and dashboard `POST /api/dashboard/providers/connect` alike. The clean fail-closed message is never shown; the caller gets a Python error instead. **This is the primary reason the product "does not work".** |
| **P0-2** | **Local state is inconsistent**, so the cascade legitimately has **0 providers**: `config/accounts.yaml` declares `claude-perso` + `gemini-perso` with `credentials_ref: file:data/creds/<id>.json`, but `data/creds/` only holds `chatgpt_web-perso.json` — a credential for an account that does not exist in `accounts.yaml`. `data/egress_lanes.json` holds **one** lane, bound to `claude-perso` only, so `gemini-perso` has no exit IP. | `data/egress_lanes.json` → 1 lane; `data/creds/` → 1 file, wrong account. | `build_providers()` discards every account (fail-closed, correct behaviour) → `chat` returns `All the 0 providers failed. Latest error: None`. Fixing P0-1 alone will not produce a completion; the local state must be aligned. |
| **P0-3** | **The error message hides the cause.** The per-account exclusion reasons already exist in `cascade.get_skipped()` ("no exit proxy (fail-closed…)", "provider unknown to registry", "cooldown session…") but are never surfaced. `src/core/cascade.py:235` builds `All the 0 providers failed. Latest error: None`; `src/core/cascade.py:434` and `src/main.py:146` prefix it with `All border endpoints have failed` ("border" is a mistranslation of "frontier"). | Running the MCP server reproduces both strings. | The user sees "0 providers / None" and cannot tell a missing credential from a missing lane or a dead circuit. Nothing is actionable. |

**Fix order:** P0-1 (2 lines) → align `accounts.yaml` / `data/creds/` / `data/egress_lanes.json` → surface `get_skipped()` in every error path (MCP `chat`, `/v1/chat/completions`, dashboard).

### P1 — correctness, packaging, documentation integrity

| # | Bug | Where |
|---|---|---|
| **P1-1** | **Package metadata is still French** — `description` starts with `Un MCP qui donne acces a des modeles frontier gratuits…`. This is what PyPI and npm show. | `pyproject.toml`, `package.json` |
| **P1-2** | **The wheel ships `src/` only** (54 entries, no `config/`, no `scripts/`). An installed user therefore cannot run `scripts/fetch_3d_assets.py` → the dashboard silently degrades to the procedural Colosseum. | `pyproject.toml` `[tool.setuptools.packages.find] include = ["src*"]` |
| **P1-3** | **README documents `redis` as a dependency**; `pyproject.toml` states redis is a dead list and installs nothing. | `README.md` requirements table |
| **P1-4** | **README/PROGRESS were machine-translated and are partly unreadable**: "validated against its **forehead**" (×3, means *front end*), "The browser flow has **not never** been exercised", "Change **imprint** to during the session is to get banned", "the **nucleus**", "**Deposit**" (repo), "**Allocation** of third-party assets" (attribution), "IP egress **jetables**", "**quarantaine**", "**Navigateur**", "d'install", "**fronts web uniquement**", "**Exercer**", "file:**chemin**". | `README.md`, `PROGRESS.md` |
| **P1-5** | **Stale numbers**: "16 tabs" and "10 tabs" (actual **17**), "43 endpoints" (actual **47**), every module line count in the table is wrong. | `README.md` |
| **P1-6** | **~40 French strings still ship in the product**, most of them user-visible: | see below |
| **P1-7** | **`openai_passthrough` is registered in `ADAPTER_REGISTRY` but absent from `PROVIDER_META`** → it is invisible to `list_providers` and to the dashboard provider matrix, and `get_active_providers()` can never build it. | `src/proxy/proxy_engine.py:365-400` |

**Residual French in the product (P1-6):**

| Location | String |
|---|---|
| `src/sessions/session_manager.py` | `Connexion bloquee : aucun proxy de sortie valide…`, `Aucun navigateur n'a ete ouvert…`, `Utilisez la connexion interactive du dashboard.`, `La page de connexion n'a pas ete validee.`, `Connexion non confirmee…` |
| `src/proxy/anti_waf_harvester.py:145` | `ValueError("Profil inconnu: … Dispo: …")` |
| `src/dashboard/routes.py:630,633,636` | `"Profil inconnu: …"`, `"Test bloque : egress pool indisponible (IP directe interdite)."` |
| `src/main.py:73,97,108,112,114,115` | `"format non servi"`, `[dashboard] config creee:`, `[sessions] init impossible:`, `[cascade] providers actifs:`, `Free-Hunter en arriere-plan.` |
| `src/mcp_server.py:166,329` + tool docstrings | `Disponibles: %s`, `Serveur MCP ViaRoma`, `she tries the available providers`, `Instruction systeme optionnelle`, `tier … (default: border)`, `if a **cat** fails` |
| `src/core/cascade.py:407,434` | `Provider inconnu: `, `All border endpoints have failed.` |
| Dashboard UI | `index.html` tab labelled **Journal**; `drawer.js` `title="Fermer"`; `architecture.js` `actif (IP dediee)`, `partiel`; `app.js` `Actif / oui / non` |
| `scripts/fetch_3d_assets.py`, `scripts/verify_wheel.py` | `recu`, `Colisee 3D` |

### P2 — robustness and user experience

| # | Bug | Where |
|---|---|---|
| **P2-1** | `@app.on_event("startup"/"shutdown")` is deprecated in FastAPI 0.162. | `src/main.py:92,118` |
| **P2-2** | `asyncio.create_task(hunter.run_discovery_loop(...))` is **not stored** → the task may be garbage-collected mid-run, and it is never cancelled at shutdown ("Task was destroyed but it is pending"). | `src/main.py:116` |
| **P2-3** | `except Exception: pass` around `cascade.refresh()` hides the reason the cascade is empty. | `src/mcp_server.py:64-67` |
| **P2-4** | The MCP `chat` tool returns `"ERROR: …"` as **text** instead of raising → an agent cannot distinguish failure from content, and never receives the per-account reasons. | `src/mcp_server.py:135-139` |
| **P2-5** | **Dashboard intuitiveness**: 17 tabs with no URL deep-link (the active tab lives in JS state only), no empty-state guidance, the Connect flow never explains *why* an account is excluded, mixed-language labels, whole-dashboard polling every 2 s. | `src/dashboard/static/` |
| **P2-6** | `except Exception: continue` while loading persisted sessions hides corrupted session files. | `src/sessions/session_manager.py:174` |
| **P2-7** | Stale build artifacts in the tree: `tests/__pycache__/test_browser_connect.cpython-312.pyc` (deleted test) and both `cpython-312`/`cpython-314` caches. | `__pycache__/` |
| **P2-8** | `config_io.ensure_defaults()` writes the skeleton `accounts.yaml` with `success_selector: "textarea, [contenteditable=true]`, while the dashboard itself writes `success_selector: ""` (and `harvest_session()` falls back to URL-change detection when the selector is empty). Two defaults for the same file. | `src/dashboard/config_io.py:145` vs `src/dashboard/routes.py:576,1137` |

---

## ❌ Not demonstrated

- **One real completion.** Only `claude_web` was validated against its front end. The other 14 adapters have a `chat_path`, an `sse_kind` and a correct payload, but **never responded**: do not assume they work.
- **The anti-WAF bypass has never worked against a real site.** The browser flow has never been exercised on a live target.
- **No credential is shipped.** Without `data/creds/<account>.json` (which you create yourself) `chat` returns a clean 503 — by design, the secret never touches this repository.
- **Web front-ends only.** `PROVIDER_META` covers 15 web providers; no desktop/CLI front end.
- **CI proves offline code only.** It proves nothing about network behaviour.
- **The wheel/npm package has never been published.** Both are built and checked in CI; publication awaits a token.

---

## 🎯 Next steps, in order

1. **Fix `src/sessions/session_manager.py:223`** — add `import logging` + `logger = logging.getLogger(__name__)`. One-line risk, unblocks the whole connect flow.
2. **Surface the real reason in every error path** — inject `cascade.get_skipped()` into the MCP `chat` error, the HTTP 503 detail and the dashboard Connect response; fix `border` → `frontier`.
3. **Align the local state** — one account id in `config/accounts.yaml`, one credential file in `data/creds/`, one lane in `data/egress_lanes.json`, matching names. Rotate the stored ChatGPT cookies if they were ever pasted anywhere else.
4. **Finish the EN pass on the product strings** — the table in P1-6 is the exact work list; keep `logger`/docstrings/tool descriptions in English.
5. **Fix packaging** — English `description` in `pyproject.toml` + `package.json`, ship `config/` and `scripts/` in the wheel, drop `redis` from the README.
6. **Repack the dashboard for intuition** — deep-link per tab, per-account exclusion reasons in the Connect flow, empty states, consistent EN labels.
7. **Then** validate the 15 adapters one by one against their front end, exercise `ChallengeBypasser.harvest_session()` on a real site, and expand `PROVIDER_META` to desktop/CLI front ends.
8. **Publication** (npm + PyPI) stays blocked on tokens — the packages are prepared and verified in CI.

---

## 📐 Repository status

- Proprietary license, all rights reserved — see [`LICENSE`](LICENSE).
- Security model and reporting procedure: [`SECURITY.md`](SECURITY.md).
- Third-party asset attribution (three.js, Colosseum model): [`CREDITS.md`](CREDITS.md).
- `data/` is **local state** (identities, lanes, catalog, sessions, credentials): never versioned.
- Git: single commit `6f617e1`; the FR→EN pass and this diagnostic are **uncommitted in the working tree**, by explicit request.
