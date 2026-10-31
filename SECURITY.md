# Security — ViaRoma

This project manipulates **session identities** (cookies, tokens, TLS fingerprint) and
**disposable output IP**. It is a sensitive surface: a leak here is not visible
not, it feels when an account gets banned or an address starts circulating.

The rules below are not intentions: they are **coded in the
core** and verified by `tests/test_security_context.py`.

---

## 🔒 Kernel Guarantees

| Warranty | Mechanism | Test |
|---|---|---|
| **The IP of the machine is never transmitted** | No provider is executed without an output proxy: `build_providers()` **discard** the account (*fail-closed*). The proxy comes from the **account** lane, never from a global setting. | `test_security_context.py` |
| **Actual IP is never read or displayed** | The API only returns the exit IP (`lane.proxy.public_ip`). The local address is not read, logged, or exposed. | ditto |
| **Credentials never leave the machine** | On-the-fly resolution (`env:VAR` / `file:chemin`) at the time of the request. No values ​​are logged, returned by the API, or versioned. | ditto |
| **No cookie value is returned** | Session endpoints return a **number** of cookies, never their values. | ditto |
| **Tokens do not travel in cookies** | The field `cookie` is a *string*: it is broken into jar. The tokens go `Authorization` ; the meta (`org_id`, `device_id`) in the URL or a dedicated header. | ditto |
| **The dashboard only listens on the local loop** | `VIAROMA_HOST` vaut `127.0.0.1` by default. | — |
| **The repository contains no secrets** | `data/` is gitignored. Accounts only point to references (`env:` / `file:`). | pre-push scan |
| **stdout is reserved for the MCP protocol** | Core logs go to **stderr**, otherwise they break JSON-RPC. | `test_mcp_server.py` |

---

## 🧭 Threat model — what the project protects, and from whom

| Actor | Capacity | What protects him |
|---|---|---|
| **A third-party service** (web front of the model) | Sees the output IP, the `User-Agent`, JA3/JA4, session cookies | Identity consistency: IP + TLS + UA + locale come from the **same** account. An inconsistency (request from another IP, or with another TLS profile) is the most classic ban signal. |
| **A network observer** | Sees TLS traffic, but not content | The TLS is spoofed (`curl_cffi`, JA3/JA4 profiles per account), the output is a disposable proxy. |
| **An unauthorized third party** reads the filing | See the code | The license [`LICENSE`](LICENSE) is **proprietary**: redistribution, public fork and commercial use are prohibited without written consent. |
| **A local attacker** reads the machine | User Disk Access | `data/creds/` is neither versioned nor encrypted by the project: it is the responsibility of the operator (disk encryption, dedicated OS account). |

---

## 📣 Report a vulnerability

If you find a security vulnerability in ViaRoma:

1. **Do not open a public issue** until the fix is ​​delivered.
2. Write via the **private issues** of the GitHub repository, or by DM to the author.
3. Describe: the component, the reproduction, the impact (IP leak? IP leak
   credential? bypassing fail-closed?), and if possible a fix.
4. You have the right to a **publication** of the flaw after patching and
   updating this page — unless the publication exposes a secret in
   circulation, in which case the agreement will be discussed on a case-by-case basis.

**Target deadline**: acknowledgment of receipt within 7 days, correction or plan
fix within 30 days.

---

## 🧾 Checklist before publication (to be done with each push)

```powershell
# 1. No secrets in the history or in the working tree
git log -p --all | Select-String -Pattern 'sk-|AIza|Bearer [A-Za-z0-9]{20,}|sessionKey='
git ls-files | Select-String -Pattern 'sk-|AIza|sessionKey='

#2. data/ is well ignored
git check-ignore -v data/creds data/identities.json data/egress_lanes.json

#3. The 4 sequels pass
.venv/Scripts/python.exe tests/test_burn_chain.py
.venv/Scripts/python.exe tests/test_identity.py
.venv/Scripts/python.exe tests/test_security_context.py
.venv/Scripts/python.exe tests/test_mcp_server.py
```

The IC (`.github/workflows/ci.yml`) replays points 3 with each push.

---

## ⚠️ Limits assumed

* ViaRoma **does not encrypt** your credentials: they live in plain text in
  `data/creds/` (outside git). That's the job of the operating system, not the project.
* The session harvest has never yet turned against a real front: the
  path "harvested cookies → merged jar" is proven by unit test, not
  by a real session.
*A real completion has not yet been observed: it depends on your
  credentials.
* Fail-closed protects against unintentional exit on local IP.
  It does not protect against a proxy lying about its own address.

---

© 2026 MlkBlk-IT — All rights reserved. See [`LICENSE`](LICENSE).
