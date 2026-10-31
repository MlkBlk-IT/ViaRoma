<div align="center">

<img src="docs/banner.png" width="100%" alt="ViaRoma — Free Frontier Router" />

<br/>

<img src="https://img.shields.io/badge/%F0%9F%A7%7F_ALPHA-e10600?style=for-the-badge&labelColor=0d0d0d" height="40" alt="alpha" />
<img src="https://img.shields.io/badge/MCP_SERVER-00ff9c?style=for-the-badge&labelColor=0d0d0d" height="40" alt="mcp server" />
<img src="https://img.shields.io/badge/ACTIVE_DEVELOPMENT-00ff9c?style=for-the-badge&labelColor=0d0d0d" height="40" alt="active development" />
<img src="https://img.shields.io/badge/LICENSE-PROPRIETARY%20%C2%BB%20ALL_RIGHTS_RESERVED-e10600?style=for-the-badge&labelColor=0d0d0d" height="40" alt="proprietary license" />

</div>

> # ⚠️ THIS IS NOT READY. DO NOT USE IT IN PRODUCTION. ⚠️
>
> **The project is unfinished and not reliable yet.** It is published here **so the work is
> visible and open to criticism**, not to be used.
>
> What is **not** demonstrated:
>
> - ❌ **No end-to-end completion.** Only one adapter (`claude_web`) was validated against its
>   front end. The other 14 have a `chat_path`, an `sse_kind` and a correct payload, but
>   **never answered**. Do not assume they work.
> - ❌ **The anti-WAF bypass has never worked against a real site.** The browser flow has never
>   been exercised on a live target.
> - ❌ **No credentials are provided.** Without `data/creds/<account>.json` (which you create
>   yourself) `chat` returns a clean 503. That is intended: the secret never touches this
>   repository.
> - ❌ **Web front ends only.** `PROVIDER_META` covers 15 web providers; no desktop or CLI front end.
> - ❌ **CI proves offline code only.** It proves nothing about network behaviour.
>
> **A blocking bug was found on 2026-10-31** and is **not fixed yet**:
> `src/sessions/session_manager.py` uses a `logger` that was never defined, so every account
> connection raises `NameError` instead of returning the clean fail-closed message. See
> [`PROGRESS.md`](PROGRESS.md) → *Open bugs*.
>
> **What is solid and verified**: fail-closed (no provider is called without an exit proxy —
> 5 automated levels of proof), the cascade and the circuit breaker, the dashboard (every click
> is a real API call), the catalog (real metrics only, provenance traced), and the guarantee
> that no secret leaks.
>
> You may fork it, read it and criticize it — but **do not plug a real account into it** until
> these points are lifted. The detailed status, module by module and bug by bug, is in
> [`PROGRESS.md`](PROGRESS.md).

> ## 🚧 ALPHA — no release — active development 🚧
>
> HTTP and MCP answer, the cascade is wired, the egress pool runs, the dashboard renders.
> **What is not demonstrated: an actual completion.** See [`PROGRESS.md`](PROGRESS.md).

> ## 🔒 Proprietary license — all rights reserved
>
> This repository is **not** under a free license. Personal use on your own machine is
> permitted; redistribution, public forks and commercial use are prohibited without written
> consent. See [`LICENSE`](LICENSE). The security model and the flaw-reporting procedure are
> in [`SECURITY.md`](SECURITY.md).

---

## 🏛️ What is ViaRoma?

<div align="center">
<img src="docs/poster.png" width="100%" alt="ViaRoma at a glance: the path of a request, the measured state, the catalog with no invented values, what is verified and what is not" />
</div>

**ViaRoma** — *via Romana*, "all roads lead to Rome". A single entry point giving access to
**free frontier models**: an OpenAI-compatible HTTP API and an **MCP server**, pluggable into
any agent.

The architecture rests on three unusual ideas for a proxy:

| Idea | Implementation |
|---|---|
| **The exit IP is a consumable resource** | `EgressLanePool` keeps a pool of SOCKS5/HTTP/Tor endpoints, probes them, quarantines the dead ones. |
| **A session belongs to an account, not to an IP** | Each `account_id` is bound 1:1 to a persistent **lane** (proxy + TLS profile). Burned lane → new lane, cookie jar kept. |
| **Failure is a routing signal** | A `CircuitBreaker` per provider classifies `429` / `403` / challenge, opens the circuit and **burns the lane** before switching. |

```text
agent (Hermes, Claude Code, …)
   │
   ├── MCP stdio ──▶ src/mcp_server.py ──┐
   │                                    │
   └── HTTP ───────▶ src/main.py ────────┤
                                        ▼
                     CascadeManager ──▶ CircuitBreaker (per provider)
                                        │   ├── 429 rate limit ──▶ burn lane
                                        │   ├── 403 permission ─▶ burn lane
                                        │   └── challenge ───────▶ burn lane
                                        ▼
                     ProxyLayer ──▶ ProviderAdapter (16 adapters)
                                        │
                                        ▼
                     TLSSpoofer (curl_cffi JA3/JA4) ──▶ SSE ──▶ ChatChunk
```

<div align="center">

<img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white&labelColor=0d0d0d" />
<img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white&labelColor=0d0d0d" />
<img src="https://img.shields.io/badge/MCP-00ff9c?style=for-the-badge&labelColor=0d0d0d" />
<img src="https://img.shields.io/badge/curl__cffi-00ff9c?style=for-the-badge&labelColor=0d0d0d" />
<img src="https://img.shields.io/badge/Playwright%20%2B%20Chrome-e10600?style=for-the-badge&labelColor=0d0d0d" />
<br/>
<img src="https://img.shields.io/badge/SOCKS5%20%2F%20HTTP%20%2F%20Tor-00ff9c?style=for-the-badge&labelColor=0d0d0d" />
<img src="https://img.shields.io/badge/OpenAI--compatible%20API-e10600?style=for-the-badge&labelColor=0d0d0d" />
<img src="https://img.shields.io/badge/16_adapters-00ff9c?style=for-the-badge&labelColor=0d0d0d" />
<img src="https://img.shields.io/badge/100%25%20CPU%20%C2%B7%200%20GPU%20%C2%B7%200%20paid%20API-e10600?style=for-the-badge&labelColor=0d0d0d" />

</div>

---

## 📐 Modules

| Module | Role |
|---|---|
| [`src/main.py`](src/main.py) | FastAPI app, startup/shutdown hooks, `/v1/chat/completions` (stream + non-stream), `/v1/egress/stats`, dashboard mounted. |
| [`src/mcp_server.py`](src/mcp_server.py) | **MCP server** (stdio / sse / streamable-http): 5 tools, same core as the HTTP API. |
| [`src/core/cascade.py`](src/core/cascade.py) | `CircuitBreaker` (CLOSED/OPEN/HALF_OPEN, per-provider metrics, exponential backoff) + `CascadeManager`. Loads `config/cascade.yaml`. |
| [`src/proxy/egress_lanes.py`](src/proxy/egress_lanes.py) | `EgressLanePool` — disposable exit IPs, lanes bound 1:1 per `account_id`, health loop, quarantine, `burn_lane()`, `add_proxy()`, `rebind()`. |
| [`src/proxy/identity.py`](src/proxy/identity.py) | `IdentityManager` — one **complete machine per account**: IP + TLS fingerprint + browser fingerprint (UA, locale, timezone, screen, WebGL, canvas). Stable and distinct. |
| [`src/proxy/anti_waf_harvester.py`](src/proxy/anti_waf_harvester.py) | Hybrid anti-WAF stack: Playwright + installed Chrome for login and challenge pages, then curl_cffi with full JA3/JA4 spoofing; aiohttp fallback. |
| [`src/proxy/proxy_engine.py`](src/proxy/proxy_engine.py) | `ProviderAdapter` × 16 (15 web + an OpenAI passthrough), `TLSSpoofer`, `PROVIDER_META`, `ADAPTER_REGISTRY`. |
| [`src/proxy/sse_converter.py`](src/proxy/sse_converter.py) | Normalises native SSE → `ChatChunk` for 3 dialects: OpenAI, Claude, Gemini. |
| [`src/sessions/session_manager.py`](src/sessions/session_manager.py) | Multi-account rotation, cookie-jar isolation, lane binding per account, cooldown / rate-limit / challenge states, JSON persistence. |
| [`src/hunter/hunter.py`](src/hunter/hunter.py) | `FreeHunter` — discovery of free frontier models (OpenRouter, HuggingFace, desktop apps), tier filter, persistent catalog. |
| [`src/dashboard/routes.py`](src/dashboard/routes.py) | **47 endpoints**: stats, actions, config editing, credentials, egress, anti-WAF. |
| [`src/dashboard/config_io.py`](src/dashboard/config_io.py) | Reads/writes the config files, default skeletons **without sensitive data**, backups. |
| [`src/config_loader.py`](src/config_loader.py) | Loads `accounts.yaml` and resolves `credentials_ref` (`env:` \| `file:`). |
| [`src/providers/providers.py`](src/providers/providers.py) | `BaseProvider` + web chat registry, health scoring, delegation to the real adapters. |
| [`src/schemas.py`](src/schemas.py) | Pydantic models: `ChatMessage`, `ChatCompletionRequest`, `ChatChunk`. |
| [`src/dashboard/static/app.js`](src/dashboard/static/app.js) | Dashboard control layer: 17 tabs, actions, 2 s refresh, charts. |
| [`src/dashboard/static/charts.js`](src/dashboard/static/charts.js) | 2D canvas charts with no library, **Roma Aeterna** theme: laurel wreath, Roman columns, aqueduct. |
| [`src/dashboard/static/colosseum3d.js`](src/dashboard/static/colosseum3d.js) | Real WebGL Colosseum (three.js + GLB), procedural fallback. |
| [`src/dashboard/static/architecture.js`](src/dashboard/static/architecture.js) | Live architecture graph driven by server data. |
| [`src/dashboard/static/index.html`](src/dashboard/static/index.html) | Dashboard skeleton, cache-busting `?v=`. |

---

## 🔌 The MCP server

This is the gateway for agents. Five tools, not one more:

| Tool | What it does |
|---|---|
| `chat` | Sends a message; the cascade routes internally and returns the text. The agent never chooses the provider. |
| `connect_provider` | Connects an account **once** (session harvest via Playwright/Chrome). Never returns credential values. |
| `list_providers` | The provider matrix plus the connection state of every session. |
| `list_free_models` | The catalog of free models, filtered by tier. |
| `session_status` | Live health: providers, sessions, lanes, IPs, burns, cooldowns. |

### Connect an agent

```jsonc
// claude_desktop_config.json / mcp.json — stdio transport
{
  "mcpServers": {
    "via-roma": {
      "command": "via-roma-mcp"
    }
  }
}
```

```bash
# or over HTTP, for an agent that expects streamable-http
via-roma-mcp --transport streamable-http --port 8001
```

Server logs go to **stderr**: stdout is reserved for the protocol.

---

## 🛣️ Egress lanes — the heart of the design

The exit IP is a **consumable resource**, not a setting. That decision is what makes account
rotation and IP rate-limit survival tractable.

```text
                    EgressLanePool
        ┌───────────────────────────────────────────┐
        │  pool: SOCKS5 · HTTP · Tor · lists        │
        │  probe_endpoint() → health                │
        └───────────────────┬───────────────────────┘
                            │ bind(account_id)
                            ▼
        account:perso   ──▶ [ lane-A · proxy · TLS profile ]
        account:school  ──▶ [ lane-B · proxy · TLS profile ]
                            │
                            │ burn_lane(account_id, "429 rate_limit")
                            ▼
        lane replaced from the pool — cookie jar intact
```

* **Persistent lane** — an account keeps the same exit identity from one request to the next.
* **`burn_lane()`** — on `403` / `429` / challenge, the circuit breaker recalls
  `SessionManager.burn_lane()`, which replaces the lane and keeps the cookies.
* **Health loop** — every 120 s each lane is polled (public IP, latency, country/ASN) and
  quarantined if dead. State persisted in `data/egress_lanes.json`.
* **Credentials stay out of the code** — accounts resolve their secrets through
  `credentials_ref: env:NAME | file:path`. No key is hardcoded, nothing is versioned.

---

## 🧬 Identities — one machine per account

Free-tier services often limit a person to **1 or 2 accounts**. ViaRoma answers by giving each
account a **full machine identity**:

| Layer | What varies per account |
|---|---|
| **Network** | The exit IP (lane), unique and disposable. |
| **TLS** | The JA3/JA4 profile (`chrome120`, `chrome119`, `firefox133`, `safari17`). |
| **Browser** | User-Agent, `sec-ch-ua`, platform, locale, timezone, screen resolution, viewport, `deviceMemory`, `hardwareConcurrency`, WebGL vendor/renderer, canvas noise seed. |

Two invariants, enforced by `IdentityManager`:

* **Stable** — an account keeps the same identity throughout. Changing the fingerprint during
  a session is how accounts get banned.
* **Distinct** — two accounts never share the same fingerprint. The service must see one
  person with one identity, not ten accounts.

The identity is **derived from a seed** = `hash(account_id + install salt + rotation)`: it is
reproducible without storing 30 fields, unique per account, and rotatable — a new seed yields a
new coherent identity.

**Coupling is the key**: `burn_lane()` rotates the IP **and** the fingerprint **together**. A new
IP with the same fingerprint is an account that "jumps machine".

The **🧬 Identities** tab of the dashboard shows the status per account and per rotation.

---

## ⚡ Quick start

```bash
# Python 3.12 is required — curl_cffi has no _cffi_backend wheel on 3.14+
py -3.12 -m venv .venv
.venv/Scripts/pip install -r requirements.txt

# HTTP API + dashboard, from the repository root
.venv/Scripts/python -m src.main

# MCP server (stdio) for an agent
.venv/Scripts/python -m src.mcp_server
```

The 3D models of the Colosseum (~31 MB) are **not** in the repository. Fetch them once:

```bash
.venv/Scripts/python scripts/fetch_3d_assets.py
```

Without them the dashboard falls back to a procedural Colosseum — it still works.

The API listens on **port 8000** (override with `VIAROMA_PORT`):

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"ping"}],"stream":true}'

curl http://127.0.0.1:8000/v1/egress/stats
```

The dashboard is at **http://127.0.0.1:8000/dashboard/** — 17 tabs, Roma Aeterna theme.

Any OpenAI-compatible client works: point its `base_url` at `http://127.0.0.1:8000/v1`.

> **Before the first request works**, three local files must agree on the same account id:
> a row in `config/accounts.yaml`, a credential file in `data/creds/<account_id>.json`, and an
> exit lane in `data/egress_lanes.json`. Without an exit lane the account is excluded by
> design (fail-closed). The exact current state of this machine is documented in
> [`PROGRESS.md`](PROGRESS.md).

### 📦 Installation packages

The repository is packaged for npm and PyPI. Both paths are **prepared and checked in CI**;
publishing requires an account and a token.

```bash
# npm — the package installs the launchers (they look for Python 3.12 only)
npm install -g via-roma
via-roma-mcp      # MCP server (stdio)
via-roma          # HTTP API + dashboard

# PyPI
pip install via-roma
via-roma-mcp
via-roma
```

`config/` is generated with safe skeletons at first launch; `data/` (identities, lanes, catalog,
sessions, credentials) is local state and is never versioned.

To store the state somewhere else than the package folder:

```bash
export VIAROMA_HOME=/path/to/state
```

If Python 3.12 cannot be found, the launcher exits with an explicit message
(`VIAROMA_PYTHON`, or install `requirements.txt`). It never guesses.

### Requirements

| Package | Role |
|---|---|
| `fastapi`, `uvicorn` | HTTP surface and ASGI server |
| `mcp` | MCP server (stdio / sse / streamable-http) |
| `pydantic` | Request/response schemas |
| `curl_cffi` | TLS impersonation (JA3/JA4) — **Python 3.12 only** |
| `aiohttp` | Fallback transport when curl_cffi is unavailable |
| `playwright` | Browser automation with installed Chrome for login and challenge pages |
| `pyyaml` | Config files (`config/*.yaml`) |

---

## 🛡️ Security — the real IP never goes out, credentials never leak

This is a **structural guarantee**, not an option. It lives in the core and is verified by
`tests/test_security_context.py` and `tests/test_ip_leak.py`.

| Guarantee | How it is held | Tested |
|---|---|---|
| **The machine IP is never transmitted** | No provider runs without an exit proxy: `build_providers()` **discards** the account (fail-closed) instead of letting it live. The proxy comes from the **account lane**, never from a global setting. | ✅ |
| **The real IP is never displayed** | The API only returns the exit IP (`lane.proxy.public_ip`). The local IP is neither read, logged nor exposed by `/api/dashboard/security/summary`. | ✅ |
| **Credentials never leave the machine** | Resolved on the fly (`env:VAR` / `file:path`) at request time. Values are never logged, never returned by the API, never stored in the repository. | ✅ |
| **No cookies are returned** | Session endpoints return a **count** of cookies, never their values. | ✅ |
| **Tokens do not travel in cookies** | The `cookie` field is a *string* of cookies: it is split into a jar. Tokens (`access_token`, `token`, `api_key`, `auth_token`) leave in the `Authorization` header; metadata (`org_id`, `device_id`) goes into the URL or a dedicated header. | ✅ |
| **The dashboard only listens on the loopback** | `VIAROMA_HOST` defaults to `127.0.0.1`. The dashboard shows routing state; it has nothing to do on the LAN. | — |
| **The repository contains no secrets** | `data/` is gitignored; accounts only point to references. The CI runs a secret scanner on every commit. | ✅ |

The dashboard shows these guarantees live (**Overview → Active guarantees**), with the list of
excluded accounts and the reason for each.

### Routing starts from a unique context per account

This is the point that makes the guarantees hold. A request is no longer assembled from
scattered settings but from a **context** carrying the complete identity of the account:

```text
context(account_id)
  ├── proxy      ← lane exit of the account (required, otherwise fail-closed)
  ├── tls_profile ← account identity JA3/JA4 profile
  ├── user_agent  ← UA collected by the browser (otherwise the identity's)
  ├── locale      ← identity locale (Accept-Language follows)
  └── creds       ← harvested cookie jar + resolved credentials
```

Sending a request from another IP than the browser's, or with another TLS profile than the
identity's, is exactly how an account gets banned. Here the five elements come from the
**same** source.

---

## 🎨 The "Roma Aeterna" dashboard

* **The Colosseum in WebGL (real 3D)** — three.js plus a **real GLB model** of the Colosseum
  (reconstruction of the 80 A.D. amphitheatre and of the current state): cast shadows, bloom,
  flickering torches, suspended dust, slow camera pan, mouse drag and wheel zoom. Automatic
  fallback to a procedural Colosseum when the GLB or WebGL are unavailable.
  The models are too large for the repository: `python scripts/fetch_3d_assets.py`.
  three.js is **shipped locally** (`vendor/three/`) — no CDN at runtime.
  Attribution: [Colosseum.how](https://www.colosseum.how/it/modello-3d) — see `CREDITS.md`.
* **Complete grouped side panel** — Control / Observability / Architecture / Playground /
  Configuration / Operations. Each entry opens a real tab, never an empty log.
* **Tiled overview** — command center (the real routing chain, clickable), traffic and catalog,
  live queries and safeguards (fail-closed).
* **Live architecture graph** — ViaRoma's orchestration graph in SVG, driven by server data:
  supervisor, adapters, egress, shared memory, tool registry, synthesis. Each node opens its
  file and its actions.
* **Live tab** — releases and announcements **scraped live** (Hugging Face papers from updated
  and recently created models, r/LocalLLaMA, Hacker News, OpenAI and Google AI blogs), plus the
  GGUF repositories with their **real quantized files** (name, size, URL).
* **Intro "Roman street → Colosseum"** — on start the camera descends a paved street between
  columns and arches, lit by torches, and emerges in front of the Colosseum. Skippable
  (click / Escape) and disabled when `prefers-reduced-motion` is active.
* **IP spoofing animation** — the identity enters a Roman arch, is scrambled there, and comes
  out transformed. The real IP is **hidden by construction**: it is never written.
* **Interface animations** — entrance to the Colosseum, card appearance, counting numbers,
  button reflection, pulsing halo on the status pads.

### 🔎 The catalog: real metrics, never invented values

Free Hunter scrapes public APIs **at runtime**. The important point: **no context window is
guessed**. When the source publishes the value it is taken as is and the source is traced;
otherwise the entry is flagged as "not published by source" rather than filled with a plausible
number.

---

## 🧪 Tests

```powershell
cd <repo>; $env:PYTHONIOENCODING='utf-8'
foreach ($t in 'test_burn_chain','test_identity','test_mcp_server','test_security_context','test_ip_leak') {
  & '.\.venv\Scripts\python.exe' "tests\$t.py"
}
node scripts\scan_secrets.mjs
```

The suites are standalone scripts (a `check()` helper, not pytest): each one prints a
`[PASS] / [FAIL]` line per assertion and exits non-zero on failure.

---

## 🔭 Repository status

- Single commit `6f617e1`; the English pass and the 2026-10-31 diagnostic live in the working
  tree, uncommitted by request.
- Proprietary license, all rights reserved — [`LICENSE`](LICENSE).
- Security model and flaw reporting — [`SECURITY.md`](SECURITY.md).
- Third-party asset attribution — [`CREDITS.md`](CREDITS.md).
- `data/` is local state and is never versioned.

<div align="center">
<sub>ViaRoma — <i>via Romana</i>. All roads lead to Rome.</sub>
</div>
