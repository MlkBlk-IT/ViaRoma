"""Automated proof that the real IP of the machine NEVER comes out.

5 levels of proof, all offline (no network calls):

  1) STRUCTURE: no provider is built without an exit proxy
                  (fail-closed). An account without egress is discarded, not degraded.
  2) TRANSPORT: the HTTP session that carries the traffic is configured with the
                  account proxy. The TCP connection therefore targets the proxy.
  3) TARGET: the requested URL is indeed that of the supplier, but it
                  passes through the proxy: the two are never confused.
  4) LOCAL IP: the IP of the machine (calculated AT EXECUTION, never written in
                  hard in the repository) is missing from the repository, from the configured proxies
                  and active lanes.
  5) LOGS: the local IP does not appear in any log files written by
                  ViaRoma.

No network calls. No production files edit.

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
# Real IP of the machine: calculated at runtime, never hardcoded.
# ──────────────────────────────────────────────────────────────────────────
def local_ips():
    """Local IPs of the machine (excluding loopback).

    UDP connect(): no packets are sent, only local routing is
    consult. This gives the IP that a remote egress would see.
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
    """Host of a proxy URL (without //user:pass@host:port)."""
    if not url:
        return ""
    rest = url.split("://", 1)[-1]
    rest = rest.rsplit("@", 1)[-1]
    return rest.split("/")[0].split(":")[0]


class _Capture(Exception):
    """Stops the query after capturing transport parameters."""


async def probe_stub_branch(adapter):
    """Stub path (aiohttp): the request must go WITH proxy=.

    We force the stub branch of the production code (aiohttp session created by
    the spoofer itself) to check it even when curl_cffi is installed:
    this path is used when curl_cffi is missing.
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
    """Real path (curl_cffi): the session carries the proxy of the account."""
    client = await adapter.get_client()
    proxies = dict(getattr(client, "proxies", {}) or {})
    return {"proxies": proxies, "stub": bool(adapter._spoofer.is_stub)}


def repo_files():
    """Versioned files to scan (data/ and .venv excluded)."""
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
    print("== 0) Real IP of the detected machine ==")
    print("  IP protegees: " + (", ".join(sorted(ips)) if ips else "none (machine offline)"))
    check("at least one detectable local IP", len(ips) >= 1,
          "otherwise checks 4 and 5 prove nothing")

    proxy_url = "http://203.0.113.9:8080"

    print("== 1) STRUCTURE: fail-closed, no provider without egress ==")
    ctxs = [
        {"account_id": "sans-egress", "provider": "claude_web", "proxy": "",
         "tls_profile": "chrome120", "user_agent": "UA", "locale": "fr-CA", "creds": {}},
        {"account_id": "avec-egress", "provider": "claude_web", "proxy": proxy_url,
         "tls_profile": "chrome120", "user_agent": "UA", "locale": "fr-CA", "creds": {}},
    ]
    providers, skipped = build_providers(ctxs)
    check("a single provider built", len(providers) == 1, "n={}".format(len(providers)))
    check("the account without egress is discarded", len(skipped) == 1, str(skipped))
    check("all providers have a proxy",
          all(p._proxy for p in providers),
          "proxy vide = l'Real IP sort")
    check("the account proxy is preserved",
          bool(providers) and providers[0]._proxy == proxy_url,
          str(getattr(providers[0], "_proxy", None)))

    adapter = get_adapter("claude_web", "acct", cookies={}, creds={},
                          user_agent="UA", proxy=proxy_url,
                          tls_profile="chrome120", locale="fr-CA")

    print("== 2) real TRANSPORT (curl_cffi): the session carries the proxy ==")
    real = asyncio.run(probe_real_branch(adapter))
    proxies = real["proxies"]
    check("session declares a proxy", bool(proxies), str(proxies))
    check("the session proxy is that of the account",
          proxy_url in list(proxies.values()), str(proxies))
    check("no empty proxy in session",
          all(v for v in proxies.values()), str(proxies))
    check("the target is not connected directly",
          all(proxy_host(v) != proxy_host(adapter.base_url) for v in proxies.values()),
          "cible={}".format(adapter.base_url))

    print("== 3) TRANSPORT stub (aiohttp): the request goes with proxy= ==")
    stub = asyncio.run(probe_stub_branch(adapter))
    check("the request has been captured", "url" in stub, str(stub))
    check("the request carries the proxy of the account", stub.get("proxy") == proxy_url, str(stub.get("proxy")))
    check("the target is indeed the provider's URL",
          stub.get("url", "").startswith(adapter.base_url),
          "{} vs {}".format(stub.get("url"), adapter.base_url))
    check("the target and the proxy are distinct",
          proxy_host(stub.get("proxy") or "") != proxy_host(stub.get("url") or ""),
          "proxy={} url={}".format(stub.get("proxy"), stub.get("url")))

    print("== 4) LOCAL IP missing from repository, config and lanes ==")
    leaked = []
    for path in repo_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for ip in ips:
            if ip in text:
                leaked.append("{} -> {}".format(path.relative_to(ROOT).as_posix(), ip))
    check("no real IP in versioned files", not leaked, "; ".join(leaked))

    pool_cfg = ROOT / "config" / "egress_pool.yaml"
    if pool_cfg.exists():
        static = []
        for line in pool_cfg.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("static_proxies:"):
                inside = line.split(":", 1)[1].strip()
                if inside.startswith("["):
                    static = [p.strip().strip("\"'") for p in inside.strip("[]").split(",") if p.strip()]
        check("no static proxy = machine IP",
              not any(proxy_host(p) in ips for p in static), str(static))
    else:
        print("  (config/egress_pool.yaml missing: verification ignored)")

    lanes_path = ROOT / "data" / "egress_lanes.json"
    if lanes_path.exists():
        lanes = json.loads(lanes_path.read_text(encoding="utf-8"))
        lane_ips = set()
        for lane in (lanes.get("lanes") or {}).values():
            prx = (lane or {}).get("proxy") or {}
            lane_ips.add(proxy_host(prx.get("url", "")))
            if prx.get("public_ip"):
                lane_ips.add(prx["public_ip"])
        check("no lane points to the machine's IP",
              not (lane_ips & ips), "collision={}".format(sorted(lane_ips & ips)))
        check("lanes have a separate output IP from the machine",
              len(lane_ips) >= 1, "lanes={}".format(sorted(lane_ips)))
    else:
        print("  (data/egress_lanes.json missing: verification ignored)")

    print("== 5) LOCAL IP missing from logs ==")
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
    check("no real IP in the product logs", not log_hits, "; ".join(log_hits))

    print("")
    if FAILURES:
        print("FAILED: {} check(s)".format(FAILURES))
        return 1
    print("OK: the real IP of the machine does not come out (5 levels checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
