"""Preuve automatisee que l'IP reelle de la machine ne sort JAMAIS.

5 niveaux de preuve, tous hors-ligne (aucun appel reseau) :

  1) STRUCTURE  : aucun provider n'est construit sans proxy de sortie
                  (fail-closed). Un compte sans egress est ecarte, pas degrade.
  2) TRANSPORT  : la session HTTP qui porte le trafic est configuree avec le
                  proxy du compte. La connexion TCP vise donc le proxy.
  3) CIBLE      : l'URL demandee est bien celle du fournisseur, mais elle
                  transite par le proxy: les deux ne sont jamais confondus.
  4) IP LOCALE  : l'IP de la machine (calculee A L'EXECUTION, jamais ecrite en
                  dur dans le depot) est absente du depot, des proxies configures
                  et des lanes actives.
  5) JOURNAUX   : l'IP locale n'apparait dans aucun fichier de log ecrit par
                  ViaRoma.

Aucun appel reseau. Aucun fichier de production modifie.

Run:  .venv/Scripts/python.exe tests/test_ip_leak.py
"""
import asyncio
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.providers.providers import build_providers
from src.proxy.proxy_engine import get_adapter
from src.schemas import ChatCompletionRequest

FAILURES = 0


def check(label, condition, detail=""):
    global FAILURES
    status = "PASS" if condition else "FAIL"
    print("  [{}] {}{}".format(status, label, (" :: " + detail) if detail else ""))
    if not condition:
        FAILURES += 1


# ──────────────────────────────────────────────────────────────────────────
# IP reelle de la machine: calculee a l'execution, jamais codee en dur.
# ──────────────────────────────────────────────────────────────────────────
def local_ips():
    """IP locales de la machine (hors loopback).

    UDP connect(): aucun paquet n'est envoye, seul le routage local est
    consulte. Ca donne l'IP que verrait un egress distant.
    """
    ips = set()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ips.add(sock.getsockname()[0])
    except OSError:
        pass
    finally:
        sock.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:
        ips.add(socket.gethostbyname(socket.gethostname()))
    except OSError:
        pass
    return {ip for ip in ips if not ip.startswith("127.") and ip != "0.0.0.0"}


def proxy_host(url):
    """Hote d'une URL de proxy (sans://user:pass@host:port)."""
    if not url:
        return ""
    rest = url.split("://", 1)[-1]
    rest = rest.rsplit("@", 1)[-1]
    return rest.split("/")[0].split(":")[0]


class _Capture(Exception):
    """Interrompt la requete apres capture des parametres de transport."""


async def probe_stub_branch(adapter):
    """Chemin stub (aiohttp): la requete doit partir AVEC proxy=.

    On force le branche stub du code de production (session aiohttp creee par
    le spoofer lui-meme) pour le verifier meme quand curl_cffi est installe:
    ce chemin sert quand curl_cffi manque.
    """
    import aiohttp

    captured = {}
    original = aiohttp.ClientSession._request

    async def fake_request(self, method, url, **kwargs):
        captured["method"] = method
        captured["url"] = str(url)
        captured["proxy"] = kwargs.get("proxy")
        raise _Capture()

    spoofer = adapter._spoofer
    was_stub = spoofer.is_stub
    was_session = spoofer._session
    spoofer.is_stub = True
    session = spoofer.create_session()
    spoofer._session = session
    aiohttp.ClientSession._request = fake_request
    try:
        async for _ in adapter.stream_chat(
            ChatCompletionRequest(messages=[{"role": "user", "content": "ping"}])
        ):
            pass
    except Exception:
        pass
    finally:
        aiohttp.ClientSession._request = original
        spoofer.is_stub = was_stub
        spoofer._session = was_session
        try:
            await session.close()
        except Exception:
            pass
    return captured


async def probe_real_branch(adapter):
    """Chemin reel (curl_cffi): la session porte le proxy du compte."""
    client = await adapter.get_client()
    proxies = dict(getattr(client, "proxies", {}) or {})
    return {"proxies": proxies, "stub": bool(adapter._spoofer.is_stub)}


def repo_files():
    """Fichiers versionnes a scanner (data/ et .venv exclus)."""
    skip = {".git", ".venv", "node_modules", "__pycache__", "data", "dist", "build"}
    exts = {".py", ".js", ".mjs", ".yaml", ".yml", ".json", ".md", ".toml",
            ".html", ".css", ".txt", ".cfg", ".ini"}
    out = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip for part in path.parts):
            continue
        if path.suffix.lower() not in exts:
            continue
        out.append(path)
    return out


def main():
    ips = local_ips()
    print("== 0) IP reelle de la machine detectee ==")
    print("  IP protegees: " + (", ".join(sorted(ips)) if ips else "aucune (machine hors-ligne)"))
    check("au moins une IP locale detectable", len(ips) >= 1,
          "sinon les verifications 4 et 5 ne prouvent rien")

    proxy_url = "http://203.0.113.9:8080"

    print("== 1) STRUCTURE: fail-closed, aucun provider sans egress ==")
    ctxs = [
        {"account_id": "sans-egress", "provider": "claude_web", "proxy": "",
         "tls_profile": "chrome120", "user_agent": "UA", "locale": "fr-CA", "creds": {}},
        {"account_id": "avec-egress", "provider": "claude_web", "proxy": proxy_url,
         "tls_profile": "chrome120", "user_agent": "UA", "locale": "fr-CA", "creds": {}},
    ]
    providers, skipped = build_providers(ctxs)
    check("un seul provider construit", len(providers) == 1, "n={}".format(len(providers)))
    check("le compte sans egress est ecarte", len(skipped) == 1, str(skipped))
    check("tous les providers ont un proxy",
          all(p._proxy for p in providers),
          "proxy vide = l'IP reelle sort")
    check("le proxy du compte est conserve",
          bool(providers) and providers[0]._proxy == proxy_url,
          str(getattr(providers[0], "_proxy", None)))

    adapter = get_adapter("claude_web", "acct", cookies={}, creds={},
                          user_agent="UA", proxy=proxy_url,
                          tls_profile="chrome120", locale="fr-CA")

    print("== 2) TRANSPORT reel (curl_cffi): la session porte le proxy ==")
    real = asyncio.run(probe_real_branch(adapter))
    proxies = real["proxies"]
    check("la session declare un proxy", bool(proxies), str(proxies))
    check("le proxy de la session est celui du compte",
          proxy_url in list(proxies.values()), str(proxies))
    check("aucun proxy vide dans la session",
          all(v for v in proxies.values()), str(proxies))
    check("la cible n'est pas branchee en direct",
          all(proxy_host(v) != proxy_host(adapter.base_url) for v in proxies.values()),
          "cible={}".format(adapter.base_url))

    print("== 3) TRANSPORT stub (aiohttp): la requete part avec proxy= ==")
    stub = asyncio.run(probe_stub_branch(adapter))
    check("la requete a ete capturee", "url" in stub, str(stub))
    check("la requete porte le proxy du compte", stub.get("proxy") == proxy_url, str(stub.get("proxy")))
    check("la cible est bien l'URL du fournisseur",
          stub.get("url", "").startswith(adapter.base_url),
          "{} vs {}".format(stub.get("url"), adapter.base_url))
    check("la cible et le proxy sont distincts",
          proxy_host(stub.get("proxy") or "") != proxy_host(stub.get("url") or ""),
          "proxy={} url={}".format(stub.get("proxy"), stub.get("url")))

    print("== 4) IP LOCALE absente du depot, de la config et des lanes ==")
    leaked = []
    for path in repo_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for ip in ips:
            if ip in text:
                leaked.append("{} -> {}".format(path.relative_to(ROOT).as_posix(), ip))
    check("aucune IP reelle dans les fichiers versionnes", not leaked, "; ".join(leaked))

    pool_cfg = ROOT / "config" / "egress_pool.yaml"
    if pool_cfg.exists():
        static = []
        for line in pool_cfg.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("static_proxies:"):
                inside = line.split(":", 1)[1].strip()
                if inside.startswith("["):
                    static = [p.strip().strip("\"'") for p in inside.strip("[]").split(",") if p.strip()]
        check("aucun proxy statique = IP de la machine",
              not any(proxy_host(p) in ips for p in static), str(static))
    else:
        print("  (config/egress_pool.yaml absent: verification ignoree)")

    lanes_path = ROOT / "data" / "egress_lanes.json"
    if lanes_path.exists():
        lanes = json.loads(lanes_path.read_text(encoding="utf-8"))
        lane_ips = set()
        for lane in (lanes.get("lanes") or {}).values():
            prx = (lane or {}).get("proxy") or {}
            lane_ips.add(proxy_host(prx.get("url", "")))
            if prx.get("public_ip"):
                lane_ips.add(prx["public_ip"])
        check("aucune lane ne pointe vers l'IP de la machine",
              not (lane_ips & ips), "collision={}".format(sorted(lane_ips & ips)))
        check("les lanes ont une IP de sortie distincte de la machine",
              len(lane_ips) >= 1, "lanes={}".format(sorted(lane_ips)))
    else:
        print("  (data/egress_lanes.json absent: verification ignoree)")

    print("== 5) IP LOCALE absente des journaux ==")
    log_hits = []
    logs = [p for p in (ROOT / "data").glob("*.log")] if (ROOT / "data").is_dir() else []
    logs += [p for p in (ROOT / "data").glob("*.err")] if (ROOT / "data").is_dir() else []
    for path in logs:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for ip in ips:
            if ip in text:
                log_hits.append("{} -> {}".format(path.name, ip))
    check("aucune IP reelle dans les logs produits", not log_hits, "; ".join(log_hits))

    print("")
    if FAILURES:
        print("ECHEC: {} verification(s)".format(FAILURES))
        return 1
    print("OK: l'IP reelle de la machine ne sort pas (5 niveaux verifies)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
