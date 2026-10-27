
"""
Module: src/proxy/egress_lanes.py
Role: Pool d'egress IP jetables + lanes persistantes liees 1:1 a un account_id.
Principe: l'IP de sortie est une ressource jetable, pas un reglage statique.
  - Un pool de proxies (SOCKS5/HTTP, Tor 127.0.0.1:9050, listes publiques, pool local) est maintenu.
  - Chaque account_id recoit une `lane` persistante (proxy + profil TLS associe).
  - Une boucle de sante sonde chaque lane: IP publique, latence, pays/ASN -> quarantaine si morte.
  - burn_lane(): sur 403/429, la lane est remplacee depuis le pool; le cookie de session reste intact.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import aiohttp


def _log(*args, **kwargs):
    """Logs sur stderr: stdout est reserve au protocole MCP (transport stdio)."""
    kwargs.setdefault("file", sys.stderr)
    import builtins
    builtins.print(*args, **kwargs)


class LaneState(Enum):
    READY = "ready"
    ACTIVE = "active"
    PROBING = "probing"
    QUARANTINED = "quarantined"
    DEAD = "dead"


class ProxyKind(Enum):
    HTTP = "http"
    SOCKS5 = "socks5"
    TOR = "tor"


@dataclass
class ProxyEndpoint:
    url: str                      # ex: socks5://127.0.0.1:9050
    kind: ProxyKind = ProxyKind.HTTP
    source: str = "unknown"       # public-list | tor | local | manual | worldwide-scan
    country: str = ""
    asn: str = ""
    latency_ms: float = 0.0
    public_ip: str = ""
    state: LaneState = LaneState.READY
    failures: int = 0
    burns: int = 0
    added_at: float = field(default_factory=time.time)
    last_probe: float = 0.0
    quarantine_until: float = 0.0
    flag_status: str = "unknown"  # unknown | clean | flagged
    flag_checks: Dict[str, str] = field(default_factory=dict)  # {"openai": "ok", "cloudflare": "blocked"}

    def to_dict(self):
        d = asdict(self)
        d["kind"] = self.kind.value if hasattr(self.kind, "value") else self.kind
        d["state"] = self.state.value if hasattr(self.state, "value") else self.state
        return d

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data["kind"] = ProxyKind(data["kind"])
        data["state"] = LaneState(data["state"])
        return cls(**data)

    @property
    def is_usable(self):
        if self.state == LaneState.DEAD:
            return False
        if self.state == LaneState.QUARANTINED and time.time() < self.quarantine_until:
            return False
        if self.failures >= 5:
            return False
        return True


@dataclass
class Lane:
    lane_id: str
    account_id: str
    proxy: ProxyEndpoint
    tls_profile: str = "chrome120"
    state: LaneState = LaneState.READY
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    rotate_count: int = 0
    request_count: int = 0

    def to_dict(self):
        return {
            "lane_id": self.lane_id,
            "account_id": self.account_id,
            "tls_profile": self.tls_profile,
            "state": self.state.value if hasattr(self.state, "value") else self.state,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "rotate_count": self.rotate_count,
            "request_count": self.request_count,
            "proxy": self.proxy.to_dict(),
        }

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data["state"] = LaneState(data["state"])
        data["proxy"] = ProxyEndpoint.from_dict(data["proxy"])
        return cls(**data)


# --- Definitions de pool statiques (gratuites) ---

TOR_ENDPOINT = ProxyEndpoint(url="socks5://127.0.0.1:9050", kind=ProxyKind.TOR, source="tor")

# Listes publiques gratuites (sources brutes, sans cle API) — 20+ sources mondiales.
PUBLIC_PROXY_SOURCES = {
    # ── HTTP proxies (12 sources) ──
    "proxifly-http": "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
    "monosans-http": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "thespeedx-http": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "clarketm-http": "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "shiftytr-http": "https://raw.githubusercontent.com/shiftytr/proxy-list/master/proxy.txt",
    "roosterkid-http": "https://raw.githubusercontent.com/roosterkid/openproxy-list/main/proxies/http.txt",
    "mertyasar-http": "https://raw.githubusercontent.com/mertcobanoglu/http-proxy-list/main/proxy.txt",
    "vakhov-http": "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/http.txt",
    "proxyscrape-http": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "proxy-list-dl-http": "https://www.proxy-list.download/api/v1/get?type=http",
    "geonode-http": "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=http",
    "openproxylist-http": "https://raw.githubusercontent.com/zloi-user/hideip.me/main/http.txt",
    # ── SOCKS5 proxies (10 sources) ──
    "proxifly-socks5": "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt",
    "thespeedx-socks5": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "monosans-socks5": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "roosterkid-socks5": "https://raw.githubusercontent.com/roosterkid/openproxy-list/main/proxies/socks5.txt",
    "hookzof-socks5": "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "jetkai-socks5": "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt",
    "proxyscrape-socks5": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all",
    "proxy-list-dl-socks5": "https://www.proxy-list.download/api/v1/get?type=socks5",
    "zloi-socks5": "https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks5.txt",
    # ── SOCKS4 ──
    "thespeedx-socks4": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
}

IPIFY_URL = "https://api.ipify.org?format=json"
IPAPI_URL = "http://ip-api.com/json/"  # gratuit, sans cle, 45 req/min


def _parse_proxy_line(line, kind):
    """Parse 'ip:port' ou 'user:pass@ip:port' -> ProxyEndpoint."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" in line:
        url = line
    else:
        scheme = "socks5" if kind == ProxyKind.SOCKS5 else "http"
        url = scheme + "://" + line
    return ProxyEndpoint(url=url, kind=kind, source="public-list")


class _NoopCM:
    """Context manager asynchrone no-op pour semaphores optionnels."""
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass


class EgressLanePool:
    """Pool d'egress IP jetables + binding lane persistante par compte.

    - refresh_pool(): rafraichit le pool depuis Tor + listes publiques
    - probe_lane(): sonde IP publique, latence, pays/ASN
    - health_loop(): boucle de fond style FreeHunter, quarantaine des lanes mortes
    - bind(account_id): attribue une lane persistante (1:1) et la retourne
    - burn_lane(account_id): remplace la lane sur 403/429; cookies intacts
    """

    def __init__(self, lanes_path="data/egress_lanes.json", probe_interval=120,
                 probe_timeout=8, quarantine_seconds=600, enable_tor=True,
                 static_proxies=None, on_burn=None):
        self.lanes_path = Path(lanes_path)
        self.probe_interval = probe_interval
        self.probe_timeout = probe_timeout
        self.quarantine_seconds = quarantine_seconds
        self.enable_tor = enable_tor
        self.on_burn = on_burn
        self.pool: List[ProxyEndpoint] = []
        self.lanes: Dict[str, Lane] = {}          # account_id -> Lane
        self._running = False
        self._task = None
        self.stats = {"probes": 0, "burns": 0, "quarantined": 0, "refreshes": 0}
        # ── Etat du scan mondial temps reel ──
        self._scan_running = False
        self._scan_last_ts = 0.0
        self._scan_duration = 0.0
        self._scan_sources_ok = 0
        self._scan_proxies_found = 0
        self._scan_proxies_probed = 0
        self._scan_proxies_clean = 0
        self._scan_proxies_flagged = 0
        self._scan_proxies_added = 0
        self._scan_flag_summary: Dict[str, int] = {}
        if static_proxies:
            for p in static_proxies:
                kind = ProxyKind.SOCKS5 if p.startswith("socks5") else ProxyKind.HTTP
                self.pool.append(ProxyEndpoint(url=p, kind=kind, source="manual"))
        if enable_tor:
            self.pool.append(ProxyEndpoint(**{k: v for k, v in TOR_ENDPOINT.to_dict().items()
                                              if k in ("url", "kind", "source")}))

    # --- Pool discovery ---

    async def fetch_public_list(self, url, kind):
        out = []
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        for line in text.splitlines():
                            ep = _parse_proxy_line(line, kind)
                            if ep:
                                out.append(ep)
        except Exception as e:
            _log("[EgressLanes] fetch failed " + url + ": " + str(e))
        return out

    async def refresh_pool(self, max_per_source=40):
        tasks = []
        for name, url in PUBLIC_PROXY_SOURCES.items():
            kind = ProxyKind.SOCKS5 if "socks5" in name else ProxyKind.HTTP
            tasks.append(self.fetch_public_list(url, kind))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        existing = {ep.url for ep in self.pool}
        added = 0
        for r in results:
            if isinstance(r, list):
                for ep in r[:max_per_source]:
                    if ep.url not in existing:
                        self.pool.append(ep)
                        existing.add(ep.url)
                        added += 1
        self.stats["refreshes"] += 1
        _log("[EgressLanes] pool refresh: +" + str(added) + " (total " + str(len(self.pool)) + ")")
        return added

    # --- Probes ---

    async def probe_endpoint(self, ep):
        start = time.time()
        try:
            timeout = aiohttp.ClientTimeout(total=self.probe_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(IPIFY_URL, proxy=ep.url) as resp:
                    if resp.status != 200:
                        raise RuntimeError("ipify status " + str(resp.status))
                    data = await resp.json()
                    ep.public_ip = data.get("ip", "")
                ep.latency_ms = (time.time() - start) * 1000
                try:
                    async with session.get(IPAPI_URL + ep.public_ip) as gresp:
                        if gresp.status == 200:
                            g = await gresp.json()
                            ep.country = g.get("countryCode", "")
                            ep.asn = g.get("as", "")
                except Exception:
                    pass
            ep.state = LaneState.READY
            ep.failures = 0
            ep.last_probe = time.time()
            self.stats["probes"] += 1
            return True
        except Exception:
            ep.failures += 1
            ep.last_probe = time.time()
            if ep.failures >= 5:
                ep.state = LaneState.DEAD
            elif ep.failures >= 2:
                ep.state = LaneState.QUARANTINED
                ep.quarantine_until = time.time() + self.quarantine_seconds
                self.stats["quarantined"] += 1
            self.stats["probes"] += 1
            return False

    async def probe_all(self, limit=40):
        candidates = [ep for ep in self.pool if ep.state != LaneState.DEAD][:limit]
        if not candidates:
            return 0
        results = await asyncio.gather(*[self.probe_endpoint(ep) for ep in candidates], return_exceptions=True)
        ok = sum(1 for r in results if r is True)
        _log("[EgressLanes] probes: " + str(ok) + "/" + str(len(candidates)) + " OK")
        return ok

    # --- Binding lane <-> compte ---

    def _pick_proxy(self):
        usable = [ep for ep in self.pool if ep.is_usable]
        bound = {lane.proxy.url for lane in self.lanes.values()}
        free = [ep for ep in usable if ep.url not in bound]
        candidates = free or usable
        if not candidates:
            return None
        probed = [ep for ep in candidates if ep.latency_ms > 0]
        if probed:
            probed.sort(key=lambda e: e.latency_ms)
            return probed[0]
        return candidates[0]

    def bind(self, account_id, tls_profile="chrome120"):
        existing = self.lanes.get(account_id)
        if existing and existing.proxy.is_usable:
            return existing
        proxy = self._pick_proxy()
        if proxy is None:
            return None
        lane = Lane(
            lane_id="lane_" + account_id + "_" + str(int(time.time())),
            account_id=account_id,
            proxy=proxy,
            tls_profile=tls_profile,
            state=LaneState.ACTIVE,
        )
        self.lanes[account_id] = lane
        self.save()
        return lane

    def get_lane(self, account_id):
        return self.lanes.get(account_id)

    def add_proxy(self, url, source="user", kind="http"):
        """Ajoute un proxy au pool (dedupe par URL). Retourne l'endpoint ou None."""
        url = (url or "").strip()
        if not url:
            return None
        if "://" not in url:
            url = "http://" + url
        if any(ep.url == url for ep in self.pool):
            return None
        try:
            pk = ProxyKind(str(kind).lower()) if kind else ProxyKind.HTTP
        except ValueError:
            pk = ProxyKind.HTTP
        ep = ProxyEndpoint(url=url, kind=pk, source=source)
        self.pool.append(ep)
        self.save()
        return ep

    def rebind(self, account_id, tls_profile=None):
        """Re-attache une lane pour un compte: nouveau proxy + profil TLS optionnel.
        Les cookies de session ne sont pas touches (ils vivent dans SessionManager)."""
        old = self.lanes.get(account_id)
        profile = tls_profile or (old.tls_profile if old else "chrome120")
        if old is not None:
            old.proxy.state = LaneState.QUARANTINED
            old.proxy.quarantine_until = time.time() + self.quarantine_seconds
            old.rotate_count += 1
            self.stats["burns"] += 1
        self.lanes.pop(account_id, None)
        lane = self.bind(account_id, profile)
        self.save()
        return lane

    async def burn_lane(self, account_id, reason="403/429"):
        old = self.lanes.get(account_id)
        if old is None:
            return None
        old.proxy.burns += 1
        old.proxy.state = LaneState.QUARANTINED
        old.proxy.quarantine_until = time.time() + self.quarantine_seconds
        old.rotate_count += 1
        self.stats["burns"] += 1
        new_proxy = self._pick_proxy()
        if new_proxy is None:
            self.save()
            return None
        old.proxy = new_proxy
        old.state = LaneState.ACTIVE
        old.last_used = time.time()
        self.save()
        if self.on_burn:
            try:
                self.on_burn(account_id, reason)
            except Exception:
                pass
        _log("[EgressLanes] burn " + account_id + " (" + reason + ") -> " + new_proxy.url)
        return old

    # --- Persistance ---

    def save(self):
        try:
            self.lanes_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "lanes": {aid: lane.to_dict() for aid, lane in self.lanes.items()},
                "pool": [ep.to_dict() for ep in self.pool],
                "stats": self.stats,
                "saved_at": time.time(),
            }
            self.lanes_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            _log("[EgressLanes] save failed: " + str(e))

    def load(self):
        if not self.lanes_path.exists():
            return
        try:
            data = json.loads(self.lanes_path.read_text(encoding="utf-8"))
            for aid, ldata in data.get("lanes", {}).items():
                self.lanes[aid] = Lane.from_dict(ldata)
            seen = {ep.url for ep in self.pool}
            for pdata in data.get("pool", []):
                if pdata["url"] not in seen:
                    self.pool.append(ProxyEndpoint.from_dict(pdata))
                    seen.add(pdata["url"])
            self.stats.update(data.get("stats", {}))
            _log("[EgressLanes] loaded " + str(len(self.lanes)) + " lanes, " + str(len(self.pool)) + " proxies")
        except Exception as e:
            _log("[EgressLanes] load failed: " + str(e))

    # --- Boucle de sante (style FreeHunter) ---

    async def health_loop(self, interval_seconds=None):
        interval = interval_seconds or self.probe_interval
        self._running = True
        self.load()
        while self._running:
            await self.probe_all()
            self.save()
            await asyncio.sleep(interval)

    def start(self, interval_seconds=None):
        self._task = asyncio.create_task(self.health_loop(interval_seconds))
        return self._task

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    def get_stats(self):
        by_state = {}
        for lane in self.lanes.values():
            by_state[lane.state.value] = by_state.get(lane.state.value, 0) + 1
        return {
            "pool_size": len(self.pool),
            "usable": sum(1 for ep in self.pool if ep.is_usable),
            "dead": sum(1 for ep in self.pool if ep.state == LaneState.DEAD),
            "quarantined": sum(1 for ep in self.pool if ep.state == LaneState.QUARANTINED),
            "lanes": len(self.lanes),
            "lanes_by_state": by_state,
            "burns": self.stats.get("burns", 0),
            "probes": self.stats.get("probes", 0),
        }

    def get_scan_stats(self):
        """Stats du scan mondial temps reel."""
        return {
            "scanning": self._scan_running,
            "last_scan": self._scan_last_ts,
            "last_scan_duration_s": round(self._scan_duration, 1) if self._scan_duration else 0,
            "sources_total": len(WORLDWIDE_SOURCES),
            "sources_fetched": self._scan_sources_ok,
            "proxies_found": self._scan_proxies_found,
            "proxies_probed": self._scan_proxies_probed,
            "proxies_clean": self._scan_proxies_clean,
            "proxies_flagged": self._scan_proxies_flagged,
            "proxies_added": self._scan_proxies_added,
            "flag_checks": dict(self._scan_flag_summary),
        }

    async def scan_worldwide(self, max_proxies=200, concurrency=50, flag_check=True):
        """Scanne mondial temps reel: 20+ sources -> probe -> flag-check LLM -> pool.

        1. Fetch toutes les sources mondiales (PUBLIC_PROXY_SOURCES + WORLDWIDE_SOURCES).
        2. Deduplique les proxies.
        3. Probe chaque proxy (IP publique, latence, pays/ASN).
        4. Flag-check: teste si l'IP est bloquee par les LLM providers (403/429).
        5. Ajoute uniquement les proxies non-flagges au pool.
        """
        if self._scan_running:
            return {"error": "scan deja en cours"}
        self._scan_running = True
        t0 = time.time()
        all_sources = {**PUBLIC_PROXY_SOURCES, **WORLDWIDE_SOURCES}
        self._scan_sources_ok = 0
        self._scan_proxies_found = 0
        self._scan_proxies_probed = 0
        self._scan_proxies_clean = 0
        self._scan_proxies_flagged = 0
        self._scan_proxies_added = 0
        self._scan_flag_summary = {}

        # Phase 1: fetch toutes les sources (timeout court 10s, semaphore 8 concurrent)
        fetch_timeout = aiohttp.ClientTimeout(total=10, connect=5)
        fetch_sem = asyncio.Semaphore(8)
        async with aiohttp.ClientSession(timeout=fetch_timeout) as session:
            fetch_tasks = []
            for name, url in all_sources.items():
                kind = ProxyKind.SOCKS5 if "socks5" in name else (ProxyKind.SOCKS5 if "socks4" not in name and "socks" in name else ProxyKind.HTTP)
                if "socks4" in name:
                    kind = ProxyKind.SOCKS5  # traites comme SOCKS5 (fallback)
                fetch_tasks.append(self._fetch_source(session, name, url, kind, fetch_sem))
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            # Deduplication (O(n) avec set de tracking, pas O(n²))
            existing_urls = {ep.url for ep in self.pool}
            seen_urls = set()
            all_proxies = []
            sources_ok = 0
            for r in results:
                if isinstance(r, list) and r:
                    sources_ok += 1
                    for ep in r:
                        if ep.url not in existing_urls and ep.url not in seen_urls:
                            seen_urls.add(ep.url)
                            all_proxies.append(ep)
            self._scan_sources_ok = sources_ok
            self._scan_proxies_found = len(all_proxies)

            if not all_proxies:
                self._scan_running = False
                self._scan_duration = time.time() - t0
                self._scan_last_ts = time.time()
                return {"error": "aucun proxy trouve", "sources_ok": sources_ok}

            # Phase 2+3: probe + flag-check (limite le nombre de proxies)
            candidates = all_proxies[:max_proxies]
            semaphore = asyncio.Semaphore(concurrency)
            probe_tasks = [_probe_and_flag(session, ep, semaphore, flag_check) for ep in candidates]
            probe_results = await asyncio.gather(*probe_tasks, return_exceptions=True)

            flag_summary: Dict[str, int] = {}
            for r in probe_results:
                if isinstance(r, Exception):
                    continue
                ep, status, checks = r
                self._scan_proxies_probed += 1
                if status == "clean":
                    self._scan_proxies_clean += 1
                    # Ajoute au pool
                    ep.source = "worldwide-scan"
                    self.pool.append(ep)
                    self._scan_proxies_added += 1
                elif status == "flagged":
                    self._scan_proxies_flagged += 1
                # Resume des flags par provider
                for pname, pstatus in checks.items():
                    if pstatus == "flagged":
                        flag_summary[pname] = flag_summary.get(pname, 0) + 1
            self._scan_flag_summary = flag_summary

        self._scan_duration = time.time() - t0
        self._scan_last_ts = time.time()
        self._scan_running = False
        self.save()
        _log("[EgressLanes] scan worldwide: " + str(self._scan_proxies_clean) + " clean / "
              + str(self._scan_proxies_flagged) + " flagged / " + str(self._scan_proxies_probed) + " probed")
        return {
            "sources_ok": self._scan_sources_ok,
            "proxies_found": self._scan_proxies_found,
            "proxies_probed": self._scan_proxies_probed,
            "proxies_clean": self._scan_proxies_clean,
            "proxies_flagged": self._scan_proxies_flagged,
            "proxies_added": self._scan_proxies_added,
            "duration_s": round(self._scan_duration, 1),
            "flag_summary": dict(flag_summary),
        }

    async def _fetch_source(self, session, name, url, kind, fetch_sem=None):
        """Fetch une source de proxies (texte ou JSON) avec semaphore."""
        out = []
        sem_ctx = fetch_sem if fetch_sem else _NoopCM()
        async with sem_ctx:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return out
                    text = await resp.text()
                    # Detection JSON (geonode, proxy-list-dl)
                    if text.strip().startswith("{") or text.strip().startswith("["):
                        import json as _json
                        try:
                            data = _json.loads(text)
                            items = data.get("data", []) if isinstance(data, dict) else data
                            for item in items:
                                ip = item.get("ip", "")
                                port = item.get("port", "")
                                if ip and port:
                                    scheme = "socks5" if kind == ProxyKind.SOCKS5 else "http"
                                    if item.get("protocols") and "socks5" in item.get("protocols", []):
                                        scheme = "socks5"
                                    url_str = scheme + "://" + str(ip) + ":" + str(port)
                                    out.append(ProxyEndpoint(url=url_str, kind=kind, source=name))
                            return out
                        except Exception:
                            pass
                    # Texte brut (ip:port par ligne)
                    for line in text.splitlines():
                        ep = _parse_proxy_line(line, kind)
                        if ep:
                            out.append(ep)
            except Exception:
                pass
        return out


# ════════════════════════════════════════════════════════════════════
# SCANNER MONDIAL TEMPS REEL — Proxies non-flagges par les LLM
# ════════════════════════════════════════════════════════════════════

# Sources mondiales supplementaires (au-dela de PUBLIC_PROXY_SOURCES).
WORLDWIDE_SOURCES = {
    # JSON APIs (structured, with country/uptime metadata)
    "geonode-json-http": "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=http&filterUpTime=80",
    "geonode-json-socks5": "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=socks5&filterUpTime=80",
    "proxyscrape-http-ssl": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=elite",
    "proxyscrape-socks5-anon": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all",
    "proxyscrape-s4": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=10000&country=all",
    # GitHub lists (raw text, updated hourly/daily)
    "almroot-http": "https://raw.githubusercontent.com/almroot/proxylist/master/http.txt",
    "almroot-socks5": "https://raw.githubusercontent.com/almroot/proxylist/master/socks5.txt",
    "yemixx-http": "https://raw.githubusercontent.com/yemixstar/proxylist/main/http.txt",
    "yemixx-socks5": "https://raw.githubusercontent.com/yemixstar/proxylist/main/socks5.txt",
    "mmpx12-http": "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
    "mmpx12-socks5": "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt",
    "saschadds-http": "https://raw.githubusercontent.com/saschadds/proxylists/master/http.txt",
    "saschadds-socks5": "https://raw.githubusercontent.com/saschadds/proxylists/master/socks5.txt",
    "internet Ruiz-http": "https://raw.githubusercontent.com/internetRuiz/proxy-list/main/http.txt",
    # Proxy-list.download API
    "proxy-list-dl-anon-http": "https://www.proxy-list.download/api/v1/get?type=http&anon=elite",
    "proxy-list-dl-anon-socks5": "https://www.proxy-list.download/api/v1/get?type=socks5&anon=elite",
}

# Endpoints LLM pour le flag-check: si l'IP est flaggee, on obtient 403/429.
# (name, url, ok_statuses, flagged_statuses)
FLAG_CHECK_ENDPOINTS = [
    # Cloudflare protege Claude.ai, OpenAI, beaucoup de LLM chats.
    ("cloudflare", "https://challenges.cloudflare.com/turnstile/v0/api.js", {200}, {403, 503}),
    # OpenAI API: 401 = cle requise (IP OK), 403/429 = IP bloquee.
    ("openai", "https://api.openai.com/v1/models", {401}, {403, 429}),
    # Anthropic API: 400/401 = requete invalide/cle requise (IP OK), 403 = IP bloquee.
    ("anthropic", "https://api.anthropic.com/v1/messages", {400, 401}, {403, 429}),
    # HuggingFace: 200 = OK, 403/429 = IP bloquee.
    ("huggingface", "https://huggingface.co/api/models?limit=1", {200}, {403, 429}),
    # Google AI: 400 = cle invalide (IP OK), 429 = IP flaggee.
    ("google_ai", "https://generativelanguage.googleapis.com/v1/models?key=invalid_test_key_xyz", {400, 403}, {429}),
]


async def _check_proxy_flag(session, proxy_url, semaphore):
    """Teste si un proxy est flagge par les LLM providers.

    Retourne (status, checks_dict) ou status = "clean" | "flagged" | "dead".
    """
    checks = {}
    any_flagged = False
    any_ok = False
    async with semaphore:
        for name, url, ok_statuses, flagged_statuses in FLAG_CHECK_ENDPOINTS:
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with session.get(url, proxy=proxy_url, timeout=timeout, ssl=False) as resp:
                    code = resp.status
                    if code in flagged_statuses:
                        checks[name] = "flagged"
                        any_flagged = True
                    elif code in ok_statuses:
                        checks[name] = "ok"
                        any_ok = True
                    else:
                        checks[name] = "other_" + str(code)
                        any_ok = True  # pas un flag clair, on considere OK
            except asyncio.TimeoutError:
                checks[name] = "timeout"
            except Exception as e:
                checks[name] = "error"
    if any_flagged:
        return "flagged", checks
    if any_ok:
        return "clean", checks
    return "dead", checks


async def _probe_and_flag(session, ep, semaphore, do_flag_check=True):
    """Probe un proxy (IP + latence) puis flag-check LLM si connectivite OK."""
    start = time.time()
    # Phase 1: connectivite
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with semaphore:
            async with session.get(IPIFY_URL, proxy=ep.url, timeout=timeout, ssl=False) as resp:
                if resp.status != 200:
                    raise RuntimeError("ipify " + str(resp.status))
                data = await resp.json()
                ep.public_ip = data.get("ip", "")
            ep.latency_ms = (time.time() - start) * 1000
        # Geo (best-effort)
        try:
            async with session.get(IPAPI_URL + ep.public_ip, timeout=aiohttp.ClientTimeout(total=5)) as gresp:
                if gresp.status == 200:
                    g = await gresp.json()
                    ep.country = g.get("countryCode", "")
                    ep.asn = g.get("as", "")
        except Exception:
            pass
        ep.state = LaneState.READY
        ep.last_probe = time.time()
    except Exception:
        ep.state = LaneState.DEAD
        ep.last_probe = time.time()
        return ep, "dead", {}
    # Phase 2: flag-check LLM
    if do_flag_check:
        flag_status, checks = await _check_proxy_flag(session, ep.url, semaphore)
        ep.flag_status = flag_status
        ep.flag_checks = checks
    else:
        ep.flag_status = "unknown"
    return ep, ep.flag_status, ep.flag_checks
