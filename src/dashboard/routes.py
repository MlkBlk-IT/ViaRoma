"""
Module: src/dashboard/routes.py
Role: FastAPI Router of the ViaRoma dashboard.
Shows the stats of Roma components + actions (burn lane, rotate session) + config editing.
No destructive deletion: burn = quarantine.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, Body, HTTPException, Request

from . import config_io

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

SENSITIVE = ("password", "token", "key", "secret", "cookie", "credential")


async def _body(request: Request) -> Dict[str, Any]:
    """Body JSON tolerant: corps vide/absent -> {}."""
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _components(request: Request) -> Dict[str, Any]:
    # Components injected into app.state by src/main.py at the startup.
    state = request.app.state
    return {
        "egress_pool": getattr(state, "egress_pool", None),
        "identities": getattr(state, "identities", None),
        "sessions": getattr(state, "sessions", None),
        "cascade": getattr(state, "cascade", None),
        "hunter": getattr(state, "hunter", None),
        "proxy": getattr(state, "proxy", None),
    }


def _scrub(d: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in d.items():
        if str(k).startswith("_"):
            continue
        if any(s in str(k).lower() for s in SENSITIVE):
            continue
        out[k] = v
    return out


def _safe_stats(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {"available": False, "reason": "unloaded component"}
    fn = getattr(obj, "get_stats", None)
    if fn is None:
        return {"available": False, "reason": "get_stats absent"}
    try:
        data = fn()
    except Exception as e:
        return {"available": False, "error": str(e)}
    base = dict(data) if isinstance(data, dict) else {"value": data}
    base["available"] = True
    return base


@router.get("/health")
async def health(request: Request) -> Dict[str, Any]:
    comps = _components(request)
    return {
        "status": "ok",
        "service": "viaroma-dashboard",
        "ts": time.time(),
        "components": {k: (v is not None) for k, v in comps.items()},
    }


@router.get("/egress/stats")
async def egress_stats(request: Request) -> Dict[str, Any]:
    return _safe_stats(_components(request)["egress_pool"])


@router.get("/egress/lanes")
async def egress_lanes(request: Request) -> Dict[str, Any]:
    pool = _components(request)["egress_pool"]
    if pool is None:
        return {"lanes": [], "available": False}
    lanes = getattr(pool, "lanes", None)
    if lanes is None:
        lanes = getattr(pool, "_lanes", []) or []
    items = lanes.values() if isinstance(lanes, dict) else lanes
    out: List[Dict[str, Any]] = []
    for ln in items or []:
        if isinstance(ln, dict):
            d = dict(ln)
        elif hasattr(ln, "to_dict"):
            d = dict(ln.to_dict())
        elif hasattr(ln, "__dict__"):
            d = dict(vars(ln))
        else:
            d = {"repr": repr(ln)}
        out.append(_scrub(d))
    return {"lanes": out, "count": len(out), "available": True}


@router.post("/egress/burn")
async def burn_lane(request: Request, payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    sessions = _components(request)["sessions"]
    account_id = str(payload.get("account_id") or payload.get("lane") or "")
    reason = str(payload.get("reason") or "manual_burn_from_dashboard")
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id required")
    if sessions is None:
        return {"ok": False, "error": "SessionManager indisponible"}
    fn = getattr(sessions, "burn_lane", None)
    if fn is None:
        return {"ok": False, "error": "burn_lane absente"}
    try:
        res = fn(account_id, reason)
    except TypeError:
        res = fn(account_id)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not isinstance(res, (dict, list, str, int, float, bool, type(None))):
        res = repr(res)
    return {"ok": True, "account_id": account_id, "reason": reason, "result": res}


@router.post("/egress/rotate")
async def rotate_egress(request: Request, payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    pool = _components(request)["egress_pool"]
    if pool is None:
        return {"ok": False, "error": "EgressLanePool indisponible"}
    for meth in ("rotate", "rotate_lane", "refresh", "probe_all", "check_all"):
        fn = getattr(pool, meth, None)
        if fn is None:
            continue
        try:
            res = fn()
        except Exception as e:
            return {"ok": False, "error": str(e), "via": meth}
        return {"ok": True, "via": meth, "result": str(res)[:400]}
    return {"ok": False, "error": "no rotation method exposed by the pool"}


@router.post("/egress/assign")
async def egress_assign(request: Request, payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    """Explicitly assigns a pool proxy to an account.

    Without this endpoint, you cannot CHOOSE the exit IP of an account:
    `rebind()` draws lots from the available pool.
    """
    pool = _components(request)["egress_pool"]
    if pool is None:
        return {"ok": False, "error": "EgressLanePool indisponible"}
    account_id = str(payload.get("account_id") or "")
    url = str(payload.get("url") or "")
    if not account_id or not url:
        raise HTTPException(status_code=400, detail="account_id and url required")
    ep = next((e for e in pool.pool if e.url == url), None)
    if ep is None:
        return {"ok": False, "error": "proxy missing from pool"}
    sessions = _components(request).get("sessions")
    account = sessions.accounts.get(account_id) if sessions else None
    if not ep.is_browser_ready(account.provider if account else None):
        return {"ok": False, "error": "Proxy non verifie, mort, marque ou deja brule."}
    from src.proxy.egress_lanes import Lane, LaneState
    old = pool.lanes.get(account_id)
    tls = getattr(old, "tls_profile", "chrome120") if old is not None else "chrome120"
    if old is not None:
        try:
            old.proxy.state = LaneState.QUARANTINED
        except Exception:
            pass
    lane = Lane(
        lane_id="lane_" + account_id + "_" + str(int(time.time())),
        account_id=account_id,
        proxy=ep,
        tls_profile=tls,
        state=LaneState.ACTIVE,
    )
    pool.lanes[account_id] = lane
    try:
        pool.save()
    except Exception:
        pass
    return {
        "ok": True,
        "account_id": account_id,
        "url": url,
        "tls_profile": tls,
        "public_ip": getattr(ep, "public_ip", ""),
        "country": getattr(ep, "country", ""),
    }


@router.get("/sessions/stats")
async def sessions_stats(request: Request) -> Dict[str, Any]:
    return _safe_stats(_components(request)["sessions"])


@router.post("/sessions/rotate")
async def rotate_session(request: Request, payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    sessions = _components(request)["sessions"]
    if sessions is None:
        return {"ok": False, "error": "SessionManager indisponible"}
    account_id = str(payload.get("account_id") or "")
    for meth in ("rotate_account", "rotate", "renew"):
        fn = getattr(sessions, meth, None)
        if fn is None:
            continue
        try:
            res = fn(account_id) if account_id else fn()
        except TypeError:
            res = fn()
        except Exception as e:
            return {"ok": False, "error": str(e), "via": meth}
        return {"ok": True, "via": meth, "account_id": account_id, "result": str(res)[:400]}
    return {"ok": False, "error": "no rotation method exposed"}


@router.get("/cascade/stats")
async def cascade_stats(request: Request) -> Dict[str, Any]:
    return _safe_stats(_components(request)["cascade"])


@router.get("/hunter/catalog")
async def hunter_catalog(request: Request) -> Dict[str, Any]:
    h = _components(request)["hunter"]
    if h is None:
        return {"models": [], "available": False}
    cat = getattr(h, "catalog", None) or {}
    items = cat.values() if isinstance(cat, dict) else cat
    models: List[Dict[str, Any]] = []
    for m in items or []:
        if hasattr(m, "to_dict"):
            models.append(dict(m.to_dict()))
        elif isinstance(m, dict):
            models.append(dict(m))
        else:
            models.append({"repr": repr(m)})
    models.sort(key=lambda x: str(x.get("tier", "")), reverse=True)
    return {"models": models, "count": len(models), "stats": _safe_stats(h), "available": True}


@router.get("/config")
async def get_config() -> Dict[str, Any]:
    return {"files": config_io.read_all(), "backups": config_io.list_backups()[:10]}


@router.put("/config/{filename}")
async def put_config(filename: str, payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    content = payload.get("content")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="required content (string) field")
    try:
        report = config_io.write_config(filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not report.get("ok"):
        raise HTTPException(status_code=422, detail=report.get("error"))
    return report


@router.post("/config/ensure-defaults")
async def ensure_defaults() -> Dict[str, Any]:
    created = config_io.ensure_defaults()
    return {"ok": True, "created": created}


@router.get("/overview")
async def overview(request: Request) -> Dict[str, Any]:
    c = _components(request)
    return {
        "egress": _safe_stats(c["egress_pool"]),
        "sessions": _safe_stats(c["sessions"]),
        "cascade": _safe_stats(c["cascade"]),
        "hunter": _safe_stats(c["hunter"]),
        "ts": time.time(),
    }





# ─── Roma component detail endpoints ────────────────────────────


@router.get("/hunter/detail")
async def hunter_detail(request: Request) -> Dict[str, Any]:
    """Hunter catalog, filterable and paginated on the server side.

    The catalog has ~2000 entries. Without filter, we returned the 100 models
    the most recently discovered: the 259 frontier were diluted in it and
    the “border” filter did not return anything. Here the sorting places the border in
    tete, et `tier` / `q` filtrent reellement.
    """
    hunter = _components(request)["hunter"]
    if hunter is None:
        return {"available": False}
    stats = hunter.get_stats()
    catalog = [m.to_dict() for m in hunter.catalog.values()]
    total_catalog = len(catalog)

    tier = (request.query_params.get("tier") or "").strip().lower()
    q = (request.query_params.get("q") or "").strip().lower()
    origin = (request.query_params.get("origin") or "").strip().lower()
    try:
        limit = max(1, min(2000, int(request.query_params.get("limit") or 500)))
    except (TypeError, ValueError):
        limit = 500

    if tier and tier != "all":
        catalog = [m for m in catalog if str(m.get("tier", "")).lower() == tier]
    if origin and origin != "all":
        catalog = [m for m in catalog
                   if str((m.get("metadata") or {}).get("origin", {}).get("code", "other")).lower() == origin]
    if q:
        catalog = [m for m in catalog
                   if q in str(m.get("model_id", "")).lower()
                   or q in str(m.get("provider", "")).lower()]

    # border first, then the most recently verified
    order = {"frontier": 0, "large": 1, "medium": 2, "small": 3}
    catalog.sort(key=lambda m: (order.get(str(m.get("tier", "")).lower(), 9),
                                 -float(m.get("last_verified") or 0)))

    return {
        "available": True,
        "stats": stats,
        "models": catalog[:limit],
        "total": len(catalog),
        "total_catalog": total_catalog,
        "tier": tier or "all",
        "origin": origin or "all",
        "running": getattr(hunter, "_running", False),
        "sources": list(hunter.SOURCES.keys()),
        "scan_interval": hunter.scan_interval,
        "discovered_endpoints": getattr(hunter, "discovered_endpoints", []),
    }


@router.get("/hunter/live")
async def hunter_live(request: Request) -> Dict[str, Any]:
    """Live releases: news, recently released models, GGUF models.

    Everything is scraped live: RSS/JSON feeds from labs and the community,
    recently created HuggingFace models, and GGUF repositories with their REAL
    quantization files (name + size in bytes + URL).
    """
    hunter = _components(request)["hunter"]
    if hunter is None:
        return {"available": False}
    # Refreshes the live stream on demand (the background scan runs every
    # the 5 min, but the Live tab must be immediate).
    try:
        await hunter.scan_news()
    except Exception:
        pass

    def slim(m):
        d = m.to_dict()
        md = d.get("metadata") or {}
        d["origin"] = md.get("origin") or {"code": "other", "label": "Autre"}
        d["ctx_source"] = md.get("ctx_source") or ""
        d["download_modes"] = md.get("download_modes") or []
        return d

    recent = [slim(m) for m in hunter.get_recent_models(limit=30)]
    gguf = [slim(m) for m in hunter.get_gguf_models(limit=60)]
    news = hunter.get_news()[:80]
    stats = hunter.get_stats()
    return {
        "available": True,
        "news": news,
        "recent": recent,
        "gguf": gguf,
        "by_origin": stats.get("by_origin", {}),
        "context_known": stats.get("context_known", 0),
        "context_unknown": stats.get("context_unknown", 0),
        "last_scan": stats.get("last_scan", 0),
    }


@router.get("/cascade/detail")
async def cascade_detail(request: Request) -> Dict[str, Any]:
    """Detailed circuit breaker: status by provider, fallback chain."""
    cascade = _components(request)["cascade"]
    if cascade is None:
        return {"available": False}
    stats = cascade.get_stats()
    # Build fallback chain
    breaker = getattr(cascade, "breaker", None)
    chain = []
    if breaker:
        available = breaker.get_available_providers()
        for name in available:
            m = breaker.metrics.get(name)
            if m:
                chain.append({
                    "name": name,
                    "state": m.state.value,
                    "success_rate": round(m.success_rate, 3),
                    "total_requests": m.total_requests,
                    "avg_latency_ms": round(m.avg_latency_ms, 1),
                    "consecutive_failures": m.consecutive_failures,
                })
    return {
        "available": True,
        "providers": stats,
        "fallback_chain": chain,
        "config": {
            "max_retries": getattr(breaker, "max_retries", 3) if breaker else 3,
            "providers_tracked": len(stats),
        },
    }


@router.get("/sessions/detail")
async def sessions_detail(request: Request) -> Dict[str, Any]:
    """Detailed sessions: complete list with status, cookies, health."""
    sessions = _components(request)["sessions"]
    if sessions is None:
        return {"available": False}
    stats = sessions.get_stats()
    session_list = []
    for sid, sess in sessions.sessions.items():
        session_list.append({
            "session_id": sid,
            "account_id": sess.account_id,
            "provider": sess.provider,
            "state": sess.state.value,
            "request_count": sess.request_count,
            "error_count": sess.error_count,
            "is_healthy": sess.is_healthy(),
            "created_at": sess.created_at,
            "last_used": sess.last_used,
            "rate_limit_reset_at": sess.rate_limit_reset_at,
            "challenge_count": sess.challenge_count,
        })
    session_list.sort(key=lambda s: s["last_used"], reverse=True)
    return {
        "available": True,
        "stats": stats,
        "sessions": session_list[:50],
        "total": len(session_list),
    }


@router.get("/egress/detail")
async def egress_detail(request: Request) -> Dict[str, Any]:
    """Detailed Egress lanes: pool, lanes with IP/country/latency/state."""
    pool = _components(request)["egress_pool"]
    if pool is None:
        return {"available": False}
    stats = pool.get_stats()
    lanes = []
    for account_id, lane in pool.lanes.items():
        ep = lane.proxy
        lanes.append({
            "account_id": account_id,
            "proxy_url": ep.url if ep else "",
            "proxy_kind": (ep.kind.value if hasattr(ep.kind, "value") else ep.kind) if ep else "",
            "proxy_state": (ep.state.value if hasattr(ep.state, "value") else ep.state) if ep else "",
            "lane_state": (lane.state.value if hasattr(lane.state, "value") else lane.state),
            "public_ip": ep.public_ip if ep else "",
            "country": ep.country if ep else "",
            "latency_ms": round(ep.latency_ms, 1) if ep else 0,
            "failures": ep.failures if ep else 0,
            "burns": ep.burns if ep else 0,
            "last_probe": ep.last_probe if ep else 0,
        })
    pool_list = []
    for ep in pool.pool:
        pool_list.append({
            "url": ep.url,
            "kind": (ep.kind.value if hasattr(ep.kind, "value") else ep.kind),
            "source": ep.source,
            "state": (ep.state.value if hasattr(ep.state, "value") else ep.state),
            "country": ep.country,
            "latency_ms": round(ep.latency_ms, 1),
            "is_usable": ep.is_usable,
            "browser_ready": ep.is_browser_ready(),
            "compatible": [p for p in ("claude_web", "gemini_web", "chatgpt_web")
                           if ep.flag_checks.get(p) == "ok"],
            "flag_status": getattr(ep, "flag_status", "unknown"),
            "flag_checks": getattr(ep, "flag_checks", {}),
            "public_ip": ep.public_ip,
            "burns": ep.burns,
            "last_probe": ep.last_probe,
        })
    ready_pool = [p for p in pool_list if p.get("browser_ready")]
    return {
        "available": True,
        "stats": stats,
        "lanes": lanes,
        "pool": pool_list[:200],
        "ready_pool": ready_pool[:100],
        "total_pool": len(pool_list),
    }


@router.get("/providers/detail")
async def providers_detail(request: Request) -> Dict[str, Any]:
    """Web providers: routing identity by account (IP, TLS, UA). No secrets."""
    from src.providers.providers import build_providers, get_active_providers
    comps = _components(request)
    sessions = comps.get("sessions")
    rows = []
    skipped = []
    if sessions is not None:
        try:
            contexts = sessions.get_provider_contexts()
            providers, skipped = build_providers(contexts)
            rows = [p.describe() for p in providers]
        except Exception:
            rows = []
    if not rows:
        rows = [p.describe() for p in get_active_providers()]
    return {"providers": rows, "total": len(rows), "skipped": skipped}


@router.post("/providers/connect")
async def providers_connect(request: Request) -> Dict[str, Any]:
    """One-click provider connection: opens a visible browser, user logs in
    manually, cookies are harvested automatically. No technical setup required.
    Auto-creates an account if none exists for the provider.
    """
    body = await _body(request)
    name = str(body.get("provider", "") or "")
    requested_account_id = str(body.get("account_id", "") or "").strip()
    connection_mode = str(body.get("mode", "egress") or "egress").strip().lower()
    if connection_mode not in {"egress", "direct"}:
        raise HTTPException(400, "Unknown connection mode")
    if requested_account_id and not __import__("re").fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", requested_account_id):
        raise HTTPException(400, "Invalid account_id. Use letters, numbers, dot, dash or underscore.")

    from src.proxy.proxy_engine import PROVIDER_META
    # Resolve provider key from name (label or key)
    key = name
    if name not in PROVIDER_META:
        for k, meta in PROVIDER_META.items():
            if str(meta.get("label", "")).lower() == name.lower():
                key = k
                break
    if key not in PROVIDER_META:
        raise HTTPException(404, f"Provider '{name}' not found")

    login_url = PROVIDER_META[key].get("login_url", "")

    sessions = _components(request).get("sessions")
    if sessions is None:
        return {"ok": False, "error": "SessionManager unavailable"}

    # Check if an account exists for this provider
    accounts = [a for a in sessions.accounts.values() if a.provider == key]

    if not accounts or requested_account_id:
        # Auto-create an account for the 1-click interactive flow. Credentials
        # are not required: the user authenticates in the visible browser.
        from src.dashboard.config_io import config_path, backup, strip_inline_credentials
        import yaml as _y
        p = config_path("accounts.yaml")
        backup("accounts.yaml")
        if p.exists():
            data = _y.safe_load(p.read_text(encoding="utf-8")) or {}
        else:
            data = {"accounts": []}
        if not data.get("accounts"):
            data["accounts"] = []
        account_id = requested_account_id or f"{key}_auto"
        # Skip if already exists (race guard)
        existing = next((a for a in data["accounts"] if a.get("account_id") == account_id), None)
        if existing is not None and existing.get("provider") != key:
            raise HTTPException(409, f"Account '{account_id}' already belongs to another provider")
        if existing is None:
            new_acc = {
                "account_id": account_id,
                "account_type": "personal",
                "provider": key,
                "login_url": login_url,
                "success_selector": "",
                "credentials_ref": "",
                "priority": len(data["accounts"]) + 1,
                "max_requests_per_hour": 100,
                "cooldown_seconds": 300,
            }
            strip_inline_credentials(new_acc)
            data["accounts"].append(new_acc)
            p.write_text(_y.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
        # Reload accounts into SessionManager
        sessions.accounts.clear()
        sessions.account_sessions.clear()
        await sessions.load_accounts()

    # Trigger interactive harvest (browser visible, user logs in)
    session = await sessions.get_session(
        key,
        interactive=True,
        account_id=requested_account_id or None,
        allow_direct=connection_mode == "direct",
    )
    if session is None:
        return {"ok": False, "error": sessions.last_error or "No secure exit available. Add a working HTTP/SOCKS5 proxy in Egress, set VIAROMA_PROXY, or start Tor on 127.0.0.1:9050. Direct IP is never used.",
                "setup_required": True,
                "provider": key,
                "mode": connection_mode,
                "account_id": requested_account_id or None}
    return {
        "ok": True,
        "provider": key,
        "provider_label": PROVIDER_META[key].get("label", key),
        "account_id": session.account_id,
        "session_id": session.session_id,
        "state": session.state.value,
        "cookie_count": len(session.cookies),
        "has_user_agent": bool(session.user_agent),
        "connected": True,
    }


@router.get("/antiwaf/status")
async def antiwaf_status(request: Request) -> Dict[str, Any]:
    """Anti-WAF: statut TLS spoofing, profils disponibles, mode stub."""
    from src.proxy.anti_waf_harvester import get_ja3_profiles, is_stub_mode, get_import_error
    profiles = get_ja3_profiles()
    return {
        "stub_mode": is_stub_mode(),
        "import_error": get_import_error(),
        "profiles": list(profiles.keys()) if profiles else [],
        "profiles_available": len(profiles),
    }


@router.post("/antiwaf/test")
async def antiwaf_test(request: Request) -> Dict[str, Any]:
    """Tests anti-WAF stack: TLS profile (JA3/JA4) observed via tls.peet.ws."""
    body = await _body(request)
    profile = str(body.get("profile") or "chrome120").strip()
    from src.proxy.anti_waf_harvester import get_ja3_profiles, get_spoofer, is_stub_mode
    profiles = get_ja3_profiles()
    if profiles and profile not in profiles:
        raise HTTPException(400, "Profil inconnu: " + profile + ". Dispo: " + str(list(profiles.keys())))
    pool = _components(request)["egress_pool"]
    if pool is None:
        return {"ok": False, "error": "Test bloque : egress pool indisponible (IP directe interdite)."}
    endpoint = pool._pick_proxy()
    if endpoint is None:
        return {"ok": False, "error": "Test bloque : aucun proxy de sortie valide (IP directe interdite)."}
    if not endpoint.public_ip and not await pool.probe_endpoint(endpoint):
        return {"ok": False, "error": "Test bloque : le proxy de sortie ne repond pas (IP directe interdite)."}
    spoofer = get_spoofer(profile=profile, proxy=endpoint.url)
    out: Dict[str, Any] = {"ok": False, "profile": profile, "stub_mode": is_stub_mode(),
                           "active_profile": profile}
    try:
        session = spoofer.get_session()
        pending = session.get("https://tls.peet.ws/api/all", timeout=20)
        if hasattr(pending, "__aenter__"):
            async with pending as resp:
                data = await resp.json()
        else:
            data = (await pending).json()
        tls_info = data.get("tls") or {}
        observed = tls_info.get("ja3_hash")
        out["ja3_hash"] = observed
        out["ja4_hash"] = tls_info.get("ja4_hash")
        out["tls_version"] = data.get("tls_version")
        out["http_version"] = data.get("http_version")
        out["ip"] = data.get("ip")
        out["user_agent"] = data.get("user_agent")
        # diff = the observed JA3 hash does not correspond to the announcement profile
        # => the real footprint of the customer is very different (active spoofing).
        expected = (profiles.get(profile) or {}).get("ja3")
        if expected and observed:
            import hashlib
            expected_hash = hashlib.md5(expected.encode("utf-8")).hexdigest()
            out["expected_ja3_hash"] = expected_hash
            out["diff"] = observed != expected_hash
        out["ok"] = bool(observed)
    except Exception as e:
        out["error"] = str(e)
    finally:
        try:
            await spoofer.close()
        except Exception:
            pass
    return out


@router.post("/antiwaf/harvest")
async def antiwaf_harvest(request: Request) -> Dict[str, Any]:
    """Connection 'once': session harvest (cookies) for a provider.
    NEVER returns the value of cookies, only their number."""
    body = await _body(request)
    provider = str(body.get("provider") or body.get("provider_key") or "").strip()
    sessions = _components(request)["sessions"]
    if sessions is None:
        return {"ok": False, "error": "SessionManager indisponible"}

    from src.proxy.proxy_engine import PROVIDER_META
    key = provider
    if provider and provider not in PROVIDER_META:
        for k, meta in PROVIDER_META.items():
            if str(meta.get("label", "")).lower() == provider.lower():
                key = k
                break
    if key and key not in PROVIDER_META:
        return {"ok": False, "error": "Provider inconnu: " + provider}

    accounts = list(sessions.accounts.values())
    if key:
        accounts = [a for a in accounts if a.provider == key]
    if not accounts:
        return {"ok": False, "error": "No accounts configured (see accounts.yaml)"}

    # One-click mode is interactive by default: the user logs in in the
    # visible browser. Credentials are optional and never need to enter the API.
    account = accounts[0]
    session = await sessions.get_session(account.provider, interactive=True)
    if session is None:
        return {"ok": False, "error": sessions.last_error or "Harvest fails (login/challenge not resolved)",
                "provider": account.provider, "account_id": account.account_id}
    return {
        "ok": True,
        "provider": account.provider,
        "account_id": account.account_id,
        "session_id": session.session_id,
        "state": session.state.value,
        "cookies": len(session.cookies),
        "cookie_count": len(session.cookies),
        "url": account.login_url,
        "has_user_agent": bool(session.user_agent),
    }


@router.post("/antiwaf/rotate")
async def antiwaf_rotate(request: Request) -> Dict[str, Any]:
    """Rotation: new exit IP + (optional) new TLS profile.
    Zero entry: without account_id we run all accounts, without profile we
    moves to the next TLS profile in the list."""
    body = await _body(request)
    account_id = str(body.get("account_id") or "").strip()
    profile = str(body.get("profile") or "").strip()
    pool = _components(request)["egress_pool"]
    sessions = _components(request)["sessions"]
    if pool is None:
        return {"ok": False, "error": "EgressLanePool indisponible"}

    from src.proxy.anti_waf_harvester import get_ja3_profiles
    profiles = list((get_ja3_profiles() or {}).keys())
    if not profile and profiles:
        current = None
        if account_id:
            lane = pool.get_lane(account_id)
            current = lane.tls_profile if lane else None
        idx = profiles.index(current) if current in profiles else -1
        profile = profiles[(idx + 1) % len(profiles)]
    if profile and profiles and profile not in profiles:
        raise HTTPException(400, "Profil inconnu: " + profile + ". Dispo: " + str(profiles))

    if account_id:
        targets = [account_id]
    else:
        targets = list(sessions.accounts.keys()) if sessions else []
        if not targets:
            targets = list(pool.lanes.keys())
    if not targets:
        return {"ok": False, "error": "No account to run"}

    rotated = []
    for acc in targets:
        lane = pool.rebind(acc, tls_profile=profile or None)
        if lane is not None:
            rotated.append({"account_id": acc, "lane_id": lane.lane_id,
                            "tls_profile": lane.tls_profile, "proxy": lane.proxy.url})
    return {
        "ok": bool(rotated),
        "active_profile": profile or (rotated[0]["tls_profile"] if rotated else ""),
        "rotated": rotated,
        "count": len(rotated),
    }


@router.post("/antiwaf/activate")
async def antiwaf_activate(request: Request) -> Dict[str, Any]:
    """Activate a TLS profile (JA3/JA4) for an account and rebind its lane."""
    body = await _body(request)
    profile = str(body.get("profile") or "").strip()
    account_id = str(body.get("account_id") or "").strip()
    if not profile:
        raise HTTPException(400, "profile required (ex: chrome120)")
    from src.proxy.anti_waf_harvester import get_ja3_profiles
    profiles = get_ja3_profiles()
    if profiles and profile not in profiles:
        raise HTTPException(400, "Profil inconnu: " + profile + ". Dispo: " + str(list(profiles.keys())))
    pool = _components(request)["egress_pool"]
    sessions = _components(request)["sessions"]
    if pool is None:
        return {"ok": False, "error": "EgressLanePool indisponible"}
    if account_id:
        targets = [account_id]
    else:
        targets = list(sessions.accounts.keys()) if sessions else []
        if not targets:
            targets = list(pool.lanes.keys())
    applied = []
    for acc in targets:
        lane = pool.rebind(acc, tls_profile=profile)
        if lane is not None:
            applied.append({"account_id": acc, "lane_id": lane.lane_id,
                            "tls_profile": lane.tls_profile, "proxy": lane.proxy.url})
    return {"ok": bool(applied), "active_profile": profile, "applied": applied, "count": len(applied)}



# ─── Identities (IP + browser fingerprint per account) ───────────

@router.get("/identity/list")
async def identity_list(request: Request) -> Dict[str, Any]:
    """Complete identity of each account: Exit IP + browser fingerprint.

    Two accounts should never share the same identity: this is what
    allows you to have several accounts without the service counting them as one
    alone (Z.Code type services limit to 1-2 accounts per person)."""
    comps = _components(request)
    identities = comps["identities"]
    pool = comps["egress_pool"]
    sessions = comps["sessions"]
    if identities is None:
        return {"available": False, "error": "IdentityManager indisponible", "identities": []}

    accounts = list(sessions.accounts.keys()) if sessions else []
    for acc in accounts:
        identities.get(acc)

    rows = []
    for prof in identities.all():
        lane = pool.get_lane(prof.account_id) if pool else None
        rows.append({
            "account_id": prof.account_id,
            "identity_id": prof.identity_id,
            "tls_profile": prof.tls_profile,
            "user_agent": prof.user_agent,
            "platform": prof.platform,
            "locale": prof.locale,
            "timezone": prof.timezone,
            "screen": "{}x{}".format(prof.screen_w, prof.screen_h),
            "device_memory": prof.device_memory,
            "hardware_concurrency": prof.hardware_concurrency,
            "rotation": prof.rotation,
            "rotated_at": prof.rotated_at,
            "last_reason": prof.last_reason,
            "egress_ip": lane.proxy.public_ip if lane else "",
            "egress_proxy": lane.proxy.url if lane else "",
            "egress_country": lane.proxy.country if lane else "",
            "egress_state": lane.state.value if lane else "none",
            "has_session": bool(sessions and sessions.account_sessions.get(prof.account_id)),
        })
    rows.sort(key=lambda r: r["account_id"])
    return {
        "available": True,
        "identities": rows,
        "total": len(rows),
        "distinct_user_agents": identities.distinct_ua_count(),
        "distinct_fingerprints": identities.distinct_fingerprint_count(),
        "collisions": identities.collisions(),
    }


@router.get("/identity/status")
async def identity_status(request: Request) -> Dict[str, Any]:
    """Identity synthesis: how many accounts, how many distinct fingerprints."""
    identities = _components(request)["identities"]
    if identities is None:
        return {"available": False}
    st = identities.status()
    st["available"] = True
    st["distinct_user_agents"] = identities.distinct_ua_count()
    st["distinct_fingerprints"] = identities.distinct_fingerprint_count()
    st["collisions"] = identities.collisions()
    return st


@router.post("/identity/rotate")
async def identity_rotate(request: Request) -> Dict[str, Any]:
    """Identity rotation: new IP + new fingerprint for an account.
    Session cookies are retained."""
    body = await _body(request)
    account_id = str(body.get("account_id") or "").strip()
    reason = str(body.get("reason") or "manual_rotate")
    comps = _components(request)
    identities = comps["identities"]
    pool = comps["egress_pool"]
    sessions = comps["sessions"]
    if identities is None or pool is None:
        return {"ok": False, "error": "IdentityManager / EgressLanePool indisponible"}
    if not account_id:
        return {"ok": False, "error": "account_id required"}
    lane = pool.get_lane(account_id)
    tls_profile = lane.tls_profile if lane else "chrome120"
    prof = identities.rotate(account_id, reason=reason, tls_profile=tls_profile)
    new_lane = pool.rebind(account_id, tls_profile=tls_profile)
    return {
        "ok": True,
        "account_id": account_id,
        "identity_id": prof.identity_id,
        "tls_profile": prof.tls_profile,
        "rotation": prof.rotation,
        "user_agent": prof.user_agent,
        "timezone": prof.timezone,
        "egress_proxy": new_lane.proxy.url if new_lane else "",
        "egress_ip": new_lane.proxy.public_ip if new_lane else "",
    }


@router.post("/identity/assign")
async def identity_assign(request: Request) -> Dict[str, Any]:
    """Creates an identity for each account that does not yet have one (zero entries)."""
    comps = _components(request)
    identities = comps["identities"]
    sessions = comps["sessions"]
    if identities is None:
        return {"ok": False, "error": "IdentityManager indisponible"}
    accounts = list(sessions.accounts.keys()) if sessions else []
    created = []
    for acc in accounts:
        before = identities.get(acc).identity_id
        after = identities.get(acc).identity_id
        if before != after:
            created.append(acc)
    return {"ok": True, "accounts": accounts, "total": len(accounts),
            "created": created, "identities": identities.status()["total_identities"]}


# ─── Web chat registry + credentials + egress options ───────────

@router.get("/webchat/registry")
async def webchat_registry(request: Request) -> Dict[str, Any]:
    """Full registry of all known web chat providers worldwide."""
    from src.providers.providers import get_registry
    registry = get_registry()
    return {"providers": registry, "total": len(registry)}


@router.get("/egress/options")
async def egress_options(request: Request) -> Dict[str, Any]:
    """All available proxy types the user can choose from."""
    return {
        "types": [
            {"id": "socks5",     "label": "SOCKS5 Proxy",      "desc": "Standard SOCKS5, good for most sites"},
            {"id": "http",       "label": "HTTP Proxy",        "desc": "HTTP/HTTPS proxy"},
            {"id": "https",      "label": "HTTPS Proxy",       "desc": "HTTPS tunnel proxy"},
            {"id": "tor",        "label": "Tor (SOCKS5 9050)", "desc": "Free anonymity network, slower"},
            {"id": "wireguard",  "label": "WireGuard VPN",     "desc": "Fast VPN tunnel, needs config"},
            {"id": "residential","label": "Residential Proxy","desc": "Real ISP IPs, best for WAF bypass"},
            {"id": "datacenter", "label": "Datacenter Proxy", "desc": "Fast datacenter IPs"},
            {"id": "rotating",   "label": "Rotating Proxy",    "desc": "Auto-rotating IP pool"},
            {"id": "custom",     "label": "Custom Proxy",      "desc": "User-defined proxy URL"},
        ],
        "free_providers": [
            {"name": "Tor Network",       "url": "socks5://127.0.0.1:9050",  "cost": "free",   "speed": "slow"},
            {"name": "FreeProxyList",      "url": "https://free-proxy-list.net", "cost": "free", "speed": "varies"},
            {"name": "ProxyScrape",        "url": "https://proxyscrape.com", "cost": "free",   "speed": "varies"},
            {"name": "Geonode Free",       "url": "https://geonode.com/free-proxy-list", "cost": "free", "speed": "varies"},
            {"name": "User-Provided",      "url": "",                        "cost": "free",   "speed": "user"},
        ],
    }


@router.post("/egress/add-proxy")
async def egress_add_proxy(request: Request) -> Dict[str, Any]:
    """Add a user-provided proxy to the pool. Accepte url|proxy_url et type|kind."""
    body = await _body(request)
    proxy_url = str(body.get("url") or body.get("proxy_url") or "").strip()
    proxy_type = str(body.get("type") or body.get("kind") or "http").strip()
    if not proxy_url:
        raise HTTPException(400, "URL required")
    pool = _components(request)["egress_pool"]
    if pool is None:
        return {"added": False, "error": "egress pool not available"}
    try:
        ep = pool.add_proxy(proxy_url, source="user", kind=proxy_type)
        if ep is None:
            return {"added": False, "error": "proxy already present or invalid URL", "proxy_url": proxy_url}
        return {"added": True, "proxy_url": ep.url, "kind": ep.kind.value,
                "pool_size": pool.get_stats()["pool_size"]}
    except Exception as e:
        return {"added": False, "error": str(e)}


@router.post("/egress/scan-worldwide")
async def egress_scan_worldwide(request: Request) -> Dict[str, Any]:
    """Triggers real-time global scan: 20+ sources -> probe -> flag-check LLM -> pool.
    Only proxies not flagged by LLM are added to the pool.
    """
    pool = _components(request)["egress_pool"]
    if pool is None:
        return {"ok": False, "error": "egress pool indisponible"}
    body = await request.json() if request.method == "POST" else {}
    max_proxies = int(body.get("max_proxies", 200)) if body else 200
    flag_check = body.get("flag_check", True) if body else True
    if pool._scan_running:
        return {"ok": False, "error": "scan already in progress", "stats": pool.get_scan_stats()}
    # Starts scanning in the background (non-blocking)
    import asyncio as _aio
    _aio.get_event_loop().create_task(pool.scan_worldwide(max_proxies=max_proxies, flag_check=flag_check))
    return {"ok": True, "message": "scan mondial lance", "stats": pool.get_scan_stats()}


@router.get("/egress/scan-status")
async def egress_scan_status(request: Request) -> Dict[str, Any]:
    """Real-time global scan status (progress, results)."""
    pool = _components(request)["egress_pool"]
    if pool is None:
        return {"ok": False, "error": "egress pool indisponible"}
    return {"ok": True, "stats": pool.get_scan_stats()}


@router.post("/egress/flag-check")
async def egress_flag_check(request: Request) -> Dict[str, Any]:
    """Checks if a proxy is flagged by LLM providers (single test)."""
    body = await request.json()
    proxy_url = body.get("url", "").strip()
    if not proxy_url:
        raise HTTPException(400, "url required")
    from src.proxy.egress_lanes import _check_proxy_flag, FLAG_CHECK_ENDPOINTS
    import aiohttp as _aio
    import asyncio as _aio_mod
    semaphore = _aio_mod.Semaphore(1)
    timeout = _aio.ClientTimeout(total=15)
    async with _aio.ClientSession(timeout=timeout) as session:
        status, checks = await _check_proxy_flag(session, proxy_url, semaphore)
    return {"url": proxy_url, "flag_status": status, "checks": checks, "endpoints": [e[0] for e in FLAG_CHECK_ENDPOINTS]}


@router.get("/credentials/list")
async def credentials_list(request: Request) -> Dict[str, Any]:
    """List all configured credentials — values ALWAYS redacted."""
    from src.dashboard.config_io import config_path, _safe_name, read_credentials
    p = config_path("accounts.yaml")
    if not p.exists():
        return {"accounts": [], "note": "No accounts configured"}
    import yaml
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    accounts = []
    for acc in data.get("accounts", []):
        # Credentials live outside of YAML (data/creds/ or env:).
        stored = read_credentials(acc.get("credentials_ref", ""))
        accounts.append({
            "account_id": acc.get("account_id", "—"),
            "provider": stored.get("api_provider") or acc.get("provider", "-"),
            "has_username": bool(stored.get("username") or acc.get("username")),
            "has_password": bool(stored.get("password") or acc.get("password")),
            "has_cookie": bool(stored.get("cookie") or stored.get("cookies") or acc.get("credentials_ref")),
            "username": "***REDACTED***" if (stored.get("username") or acc.get("username")) else "",
            "password": "***REDACTED***" if (stored.get("password") or acc.get("password")) else "",
            "credentials_ref": acc.get("credentials_ref", ""),
        })
    return {"accounts": accounts, "total": len(accounts)}


@router.put("/credentials/{account_id}")
async def credentials_update(request: Request, account_id: str) -> Dict[str, Any]:
    """Update username/password for an account.

    Values ​​are NEVER written to config/accounts.yaml (file
    versioned by git): they go in data/creds/ (gitignore) and the YAML does not
    carries only the credentials_ref. If secrets were already in the clear in the
    YAML, they are migrated to data/creds/ then deleted from the YAML.
    """
    from src.dashboard.config_io import (config_path, backup, store_credentials,
                                         strip_inline_credentials)
    import yaml
    p = config_path("accounts.yaml")
    if not p.exists():
        raise HTTPException(404, "accounts.yaml not found")
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    # Backup before write
    backup("accounts.yaml")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    migrated = False
    saved = False
    for acc in data.get("accounts", []):
        if acc.get("account_id") == account_id:
            # Migration: a secret already in the clear in the YAML is recovered.
            legacy = {k: acc.get(k) for k in ("username", "password") if acc.get(k)}
            values = {k: v for k, v in (("username", username), ("password", password)) if v}
            if legacy:
                migrated = True
                values = {**legacy, **values}
            if values:
                acc["credentials_ref"] = store_credentials(account_id, values)
                saved = True
            strip_inline_credentials(acc)
            break
    p.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    return {
        "saved": saved,
        "account_id": account_id,
        "migrated_from_inline": migrated,
        "credentials_ref": next((a.get("credentials_ref", "") for a in data.get("accounts", [])
                                  if a.get("account_id") == account_id), ""),
        "username": "***REDACTED***" if username else "",
        "password": "***REDACTED***" if password else "",
    }


@router.post("/credentials/add")
async def credentials_add(request: Request) -> Dict[str, Any]:
    """Add a new account to accounts.yaml — all fields set via GUI.

    As for the update: the secret goes in data/creds/ (gitignore),
    never in accounts.yaml (versioned).
    """
    from src.dashboard.config_io import (config_path, backup, store_credentials,
                                         strip_inline_credentials)
    import yaml as _y
    body = await request.json()
    account_id = body.get("account_id", "").strip()
    provider = body.get("provider", "").strip()
    account_type = body.get("account_type", "personal").strip()
    login_url = body.get("login_url", "").strip()
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    if not account_id or not provider:
        raise HTTPException(400, "account_id and provider required")
    p = config_path("accounts.yaml")
    if p.exists():
        backup("accounts.yaml")
        data = _y.safe_load(p.read_text(encoding="utf-8")) or {}
    else:
        data = {"accounts": []}
    if not data.get("accounts"):
        data["accounts"] = []
    # Check duplicate
    for acc in data["accounts"]:
        if acc.get("account_id") == account_id:
            raise HTTPException(409, f"Account '{account_id}' already exists")
    values = {k: v for k, v in (("username", username), ("password", password)) if v}
    credentials_ref = f"env:{account_id.upper()}_PASS"
    if values:
        credentials_ref = store_credentials(account_id, values)
    new_acc = {
        "account_id": account_id,
        "account_type": account_type,
        "provider": provider,
        "login_url": login_url,
        "success_selector": "",
        "credentials_ref": credentials_ref,
        "priority": len(data["accounts"]) + 1,
        "max_requests_per_hour": 100,
        "cooldown_seconds": 300,
    }
    strip_inline_credentials(new_acc)
    data["accounts"].append(new_acc)
    p.write_text(_y.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    return {"added": True, "account_id": account_id, "provider": provider,
            "credentials_ref": credentials_ref}


@router.delete("/credentials/{account_id}")
async def credentials_delete(request: Request, account_id: str) -> Dict[str, Any]:
    """Delete an account from accounts.yaml."""
    from src.dashboard.config_io import config_path, backup
    import yaml as _y
    p = config_path("accounts.yaml")
    if not p.exists():
        raise HTTPException(404, "accounts.yaml not found")
    backup("accounts.yaml")
    data = _y.safe_load(p.read_text(encoding="utf-8")) or {}
    before = len(data.get("accounts", []))
    data["accounts"] = [a for a in data.get("accounts", []) if a.get("account_id") != account_id]
    after = len(data["accounts"])
    if before == after:
        raise HTTPException(404, f"Account '{account_id}' not found")
    p.write_text(_y.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    return {"deleted": True, "account_id": account_id}


@router.post("/api-accounts/add")
async def api_account_add(request: Request) -> Dict[str, Any]:
    """WIP: store an official API account without exposing its key.

    The key is kept in data/creds/ and the account is marked as pending until
    its provider adapter is wired into the routing registry.
    """
    import re
    import yaml as _y
    from src.dashboard.config_io import config_path, backup, store_credentials, strip_inline_credentials

    body = await request.json()
    account_id = str(body.get("account_id") or "").strip()
    provider = str(body.get("provider") or "").strip()
    api_key = str(body.get("api_key") or "").strip()
    endpoint = str(body.get("endpoint") or "").strip()
    model = str(body.get("model") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", account_id):
        raise HTTPException(400, "Invalid account_id")
    if not provider or not api_key:
        raise HTTPException(400, "provider and api_key required")
    p = config_path("accounts.yaml")
    backup("accounts.yaml") if p.exists() else None
    data = _y.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {"accounts": []}
    data = data or {"accounts": []}
    data.setdefault("accounts", [])
    if any(a.get("account_id") == account_id for a in data["accounts"]):
        raise HTTPException(409, f"Account '{account_id}' already exists")
    values = {"api_key": api_key, "api_provider": provider}
    if endpoint:
        values["endpoint"] = endpoint
    if model:
        values["model"] = model
    ref = store_credentials(account_id, values)
    account = {
        "account_id": account_id,
        "account_type": "personal",
        "provider": "official_api",
        "login_url": "",
        "success_selector": "",
        "credentials_ref": ref,
        "priority": len(data["accounts"]) + 1,
        "max_requests_per_hour": 100,
        "cooldown_seconds": 300,
        "mode": "official_api",
    }
    strip_inline_credentials(account)
    data["accounts"].append(account)
    p.write_text(_y.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    return {"ok": True, "wip": True, "account_id": account_id, "provider": provider,
            "credentials_ref": ref, "secret_exposed": False}


@router.post("/cascade/reset")
async def cascade_reset(request: Request, payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    """Reset circuit breakers.

    Without `provider`: all breakers are reset.
    With `provider`: only one, designated by its label ("Claude (web)"), by its
    technical key ("claude_web") or by its account_id ("claude-perso").

    An unknown target returns an explicit ERROR. A mute click (ok:true
    with reset:0) is worse than a click miss: we no longer know if the action has
    eu lieu.
    """
    cascade = _components(request)["cascade"]
    if cascade is None:
        return {"ok": False, "error": "cascade indisponible"}
    breaker = getattr(cascade, "breaker", None)
    if breaker is None:
        return {"ok": False, "error": "breaker indisponible"}
    from src.core.cascade import CircuitState

    metrics = getattr(breaker, "metrics", {}) or {}
    only = str(payload.get("provider") or "").strip()

    if only:
        # Index label / key / account_id -> metric name.
        index: Dict[str, str] = {}
        for label, prov in (getattr(cascade, "_providers", {}) or {}).items():
            index.setdefault(str(label).lower(), label)
            index.setdefault(str(getattr(prov, "provider_key", "")).lower(), label)
            index.setdefault(str(getattr(prov, "account_id", "")).lower(), label)
        for name in metrics:
            index.setdefault(str(name).lower(), name)
        matched = index.get(only.lower())
        if matched is None:
            return {
                "ok": False,
                "error": f"provider inconnu: {only}",
                "known": sorted({str(n) for n in metrics}),
                "reset": 0,
            }
        targets = [matched]
    else:
        targets = list(metrics.keys())

    reset: List[str] = []
    for name in targets:
        m = metrics.get(name)
        if m is None:
            continue
        if hasattr(m, "state"):
            m.state = CircuitState.CLOSED
            m.consecutive_failures = 0
            m.consecutive_successes = 0
            m.rate_limited_until = 0
            reset.append(str(name))
        elif isinstance(m, dict):
            m["state"] = CircuitState.CLOSED
            m["consecutive_failures"] = 0
            m["consecutive_successes"] = 0
            m["rate_limited_until"] = 0
            reset.append(str(name))
    return {"ok": True, "reset": len(reset), "providers": reset, "via": "manual"}


@router.post("/hunter/scan")
async def hunter_scan(request: Request) -> Dict[str, Any]:
    """Triggers an immediate scan of ALL sources.

    The scan is not a simple "refresh the list": it merges the
    results in the catalog, which ENRICHES the already known models
    (real context window, GGUF files, lab origin) and
    persiste sur disque.
    """
    hunter = _components(request)["hunter"]
    if hunter is None:
        return {"ok": False, "error": "hunter indisponible"}
    import asyncio as _aio

    async def _do_scan():
        try:
            found = await hunter.scan_all_sources()
            added = hunter.merge_discovered(found)
            try:
                await hunter.scan_news()
            except Exception:
                pass
            hunter.save_catalog()
            hunter.discovered_endpoints = [m.model_id for m in found]
            print(f"[hunter] scan: {len(found)} trouves, {added} ajoutes")
        except Exception as e:
            print(f"[hunter] scan failed: {e}")

    _aio.get_event_loop().create_task(_do_scan())
    return {"ok": True, "message": "scan launches (all sources)"}


@router.get("/providers/list")
async def providers_list_full(request: Request) -> Dict[str, Any]:
    """Full list of ALL known providers (web chat + API + desktop)."""
    web_chats = [
        {"name": "Claude (web)", "key": "claude_web", "type": "web", "login_url": "https://claude.ai/login", "needs": ["cookie", "org_id"]},
        {"name": "Gemini (web)", "key": "gemini_web", "type": "web", "login_url": "https://gemini.google.com", "needs": ["auth_token"]},
        {"name": "ChatGPT (web)", "key": "chatgpt_web", "type": "web", "login_url": "https://chat.openai.com", "needs": ["cookie"]},
        {"name": "Qwen (web)", "key": "qwen_web", "type": "web", "login_url": "https://chat.qwenlm.ai", "needs": ["cookie"]},
        {"name": "Copilot (web)", "key": "copilot_web", "type": "web", "login_url": "https://copilot.microsoft.com", "needs": ["cookie"]},
        {"name": "Grok (web)", "key": "grok_web", "type": "web", "login_url": "https://grok.x.ai", "needs": ["cookie"]},
        {"name": "Perplexity (web)", "key": "perplexity_web", "type": "web", "login_url": "https://www.perplexity.ai", "needs": ["cookie"]},
        {"name": "DeepSeek (web)", "key": "deepseek_web", "type": "web", "login_url": "https://chat.deepseek.com", "needs": ["cookie"]},
        {"name": "Kimi (web)", "key": "kimi_web", "type": "web", "login_url": "https://kimi.moonshot.cn", "needs": ["cookie"]},
        {"name": "GLM (web)", "key": "glm_web", "type": "web", "login_url": "https://chatglm.cn", "needs": ["cookie"]},
        {"name": "Meta AI (web)", "key": "metaai_web", "type": "web", "login_url": "https://www.meta.ai", "needs": ["cookie"]},
        {"name": "Poe (web)", "key": "poe_web", "type": "web", "login_url": "https://poe.com", "needs": ["cookie"]},
        {"name": "HuggingChat (web)", "key": "huggingchat_web", "type": "web", "login_url": "https://huggingface.co/chat", "needs": ["cookie"]},
        {"name": "You.com (web)", "key": "you_web", "type": "web", "login_url": "https://you.com", "needs": ["cookie"]},
        {"name": "Lepton AI (web)", "key": "lepton_web", "type": "web", "login_url": "https://lepton.ai", "needs": ["cookie"]},
        {"name": "Mistral Le Chat (web)", "key": "mistral_web", "type": "web", "login_url": "https://chat.mistral.ai", "needs": ["cookie"]},
        {"name": "Cohere (web)", "key": "cohere_web", "type": "web", "login_url": "https://dashboard.cohere.com", "needs": ["api_key"]},
        {"name": "Anthropic Console (web)", "key": "anthropic_web", "type": "web", "login_url": "https://console.anthropic.com", "needs": ["api_key"]},
        {"name": "Google AI Studio (web)", "key": "aistudio_web", "type": "web", "login_url": "https://aistudio.google.com", "needs": ["api_key"]},
        {"name": "OpenRouter (web)", "key": "openrouter_web", "type": "web", "login_url": "https://openrouter.ai", "needs": ["api_key"]},
    ]
    api_providers = [
        {"name": "OpenRouter API", "key": "openrouter", "type": "api", "url": "https://openrouter.ai/api/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "HuggingFace API", "key": "huggingface", "type": "api", "url": "https://api-inference.huggingface.co", "needs": ["api_key"], "free_tier": True},
        {"name": "Groq API", "key": "groq", "type": "api", "url": "https://api.groq.com/openai/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "Cerebras API", "key": "cerebras", "type": "api", "url": "https://api.cerebras.ai/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "Mistral API", "key": "mistral", "type": "api", "url": "https://api.mistral.ai/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "Together AI API", "key": "together", "type": "api", "url": "https://api.together.xyz/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "Fireworks AI API", "key": "fireworks", "type": "api", "url": "https://api.fireworks.ai/inference/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "DeepSeek API", "key": "deepseek", "type": "api", "url": "https://api.deepseek.com/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "NVIDIA API", "key": "nvidia", "type": "api", "url": "https://integrate.api.nvidia.com/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "Cloudflare AI", "key": "cloudflare", "type": "api", "url": "https://api.cloudflare.com/client/v4", "needs": ["api_key"], "free_tier": True},
        {"name": "Cohere API", "key": "cohere", "type": "api", "url": "https://api.cohere.ai/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "ModelScope API", "key": "modelscope", "type": "api", "url": "https://api.modelscope.cn/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "SiliconFlow API", "key": "siliconflow", "type": "api", "url": "https://api.siliconflow.cn/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "GLM API", "key": "glm", "type": "api", "url": "https://open.bigmodel.cn/api/paas/v4", "needs": ["api_key"], "free_tier": True},
        {"name": "LLM7 API", "key": "llm7", "type": "api", "url": "https://api.llm7.io/v1", "needs": [], "free_tier": True},
        {"name": "SambaNova API", "key": "sambanova", "type": "api", "url": "https://api.sambanova.ai/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "AI21 Labs API", "key": "ai21", "type": "api", "url": "https://api.ai21.com/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "Aleph Alpha API", "key": "alephalpha", "type": "api", "url": "https://api.aleph-alpha.com/v1", "needs": ["api_key"], "free_tier": False},
        {"name": "Replicate API", "key": "replicate", "type": "api", "url": "https://api.replicate.com/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "OctoAI API", "key": "octoai", "type": "api", "url": "https://api.octoai.run/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "Baseten API", "key": "baseten", "type": "api", "url": "https://api.baseten.co/v1", "needs": ["api_key"], "free_tier": False},
        {"name": "Anyscale API", "key": "anyscale", "type": "api", "url": "https://api.endpoints.anyscale.com/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "Predibase API", "key": "predibase", "type": "api", "url": "https://serving.predibase.com/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "Databricks API", "key": "databricks", "type": "api", "url": "https://databricks.com/serving-endpoints", "needs": ["api_key"], "free_tier": False},
        {"name": "Lambda Labs API", "key": "lambdalabs", "type": "api", "url": "https://api.lambdalabs.com/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "RunPod API", "key": "runpod", "type": "api", "url": "https://api.runpod.ai/v2", "needs": ["api_key"], "free_tier": False},
        {"name": "Valyu API", "key": "valyu", "type": "api", "url": "https://api.valyu.ai/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "Glhf.chat API", "key": "glhf", "type": "api", "url": "https://glhf.chat/api/openai/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "Chutes AI API", "key": "chutes", "type": "api", "url": "https://api.chutes.ai/v1", "needs": ["api_key"], "free_tier": True},
        {"name": "Kilo API", "key": "kilo", "type": "api", "url": "https://api.kilo.ai/v1", "needs": ["api_key"], "free_tier": True},
    ]
    desktop = [
        {"name": "LM Studio", "key": "lmstudio", "type": "desktop", "url": "http://localhost:1234/v1", "needs": [], "free_tier": True},
        {"name": "Ollama", "key": "ollama", "type": "desktop", "url": "http://localhost:11434/v1", "needs": [], "free_tier": True},
        {"name": "Jan AI", "key": "jan", "type": "desktop", "url": "http://localhost:1337/v1", "needs": [], "free_tier": True},
        {"name": "GPT4All", "key": "gpt4all", "type": "desktop", "url": "http://localhost:4891/v1", "needs": [], "free_tier": True},
        {"name": "KoboldCpp", "key": "koboldcpp", "type": "desktop", "url": "http://localhost:5001/v1", "needs": [], "free_tier": True},
        {"name": "Text Generation WebUI", "key": "textgen", "type": "desktop", "url": "http://localhost:5000/v1", "needs": [], "free_tier": True},
        {"name": "Llamafile", "key": "llamafile", "type": "desktop", "url": "http://localhost:8080/v1", "needs": [], "free_tier": True},
        {"name": "vLLM", "key": "vllm", "type": "desktop", "url": "http://localhost:8000/v1", "needs": [], "free_tier": True},
        {"name": "Custom Endpoint", "key": "custom", "type": "desktop", "url": "", "needs": [], "free_tier": True},
    ]
    return {"web_chats": web_chats, "api_providers": api_providers, "desktop": desktop, "total": len(web_chats)+len(api_providers)+len(desktop)}


@router.get("/hunter/sources")
async def hunter_sources(request: Request) -> Dict[str, Any]:
    """All sources the Hunter scans worldwide."""
    hunter = _components(request)["hunter"]
    if hunter is None:
        return {"available": False}
    return {
        "available": True,
        "api_sources": list(hunter.SOURCES.keys()),
        "desktop_apps": [a.strip() for a in hunter.DESKTOP_APPS],
        "scan_interval": hunter.scan_interval,
        "running": getattr(hunter, "_running", False),
    }

# ─── Structured config (button-based, no raw editing) ──────────


@router.get("/config/{name}/structured")
async def config_structured(name: str) -> Dict[str, Any]:
    """Return parsed config as structured dict for form rendering."""
    name = config_io._safe_name(name)
    kind = "yaml" if name.endswith((".yaml", ".yml")) else "json"
    path = config_io.config_path(name)
    if not path.exists():
        tmpl = config_io.default_templates().get(name, {})
        return {"name": name, "kind": kind, "data": tmpl, "exists": False}
    raw = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw) if kind == "yaml" else json.loads(raw)
    except Exception as e:
        return {"name": name, "kind": kind, "data": {}, "error": str(e), "exists": True}
    return {"name": name, "kind": kind, "data": data or {}, "exists": True}


@router.put("/config/{name}/structured")
async def config_structured_save(name: str, payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    """Save structured config dict — serialized to YAML/JSON with backup."""
    name = config_io._safe_name(name)
    kind = "yaml" if name.endswith((".yaml", ".yml")) else "json"
    path = config_io.config_path(name)
    data = payload.get("data", payload)
    # Backup (copy, never delete original)
    if path.exists():
        config_io.backup(name)
    # Serialize
    if kind == "yaml":
        content = yaml.safe_dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    else:
        content = json.dumps(data, indent=2, ensure_ascii=False)
    # Atomic write
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    return {"name": name, "bytes": len(content), "kind": kind, "saved": True}


# ══════════════════════════════════════════════════════════════════════
# SECURITY — state of guarantees. No secrets, no real IP.
# ══════════════════════════════════════════════════════════════════════

@router.get("/security/summary")
async def security_summary(request: Request) -> Dict[str, Any]:
    """Status of router security guarantees.

    NEVER returns the real IP of the machine, nor a credential value,
    nor a cookie. Only the state: which has an exit IP, which is discarded,
    and why.
    """
    from src.providers.providers import build_providers
    comps = _components(request)
    sessions = comps.get("sessions")
    pool = comps.get("egress_pool")

    routing = []
    skipped = []
    if sessions is not None:
        try:
            contexts = sessions.get_provider_contexts()
            providers, skipped = build_providers(contexts)
            routing = [p.describe() for p in providers]
        except Exception as e:
            skipped = [{"account_id": "—", "provider": "—", "reason": "contexte indisponible: " + str(e)}]

    lanes = []
    if pool is not None:
        for account_id, lane in getattr(pool, "lanes", {}).items():
            proxy = getattr(lane, "proxy", None)
            lanes.append({
                "account_id": account_id,
                "tls_profile": getattr(lane, "tls_profile", ""),
                "egress": bool(getattr(proxy, "url", "")),
                "public_ip": getattr(proxy, "public_ip", "") or "",
                "country": getattr(proxy, "country", "") or "",
                "state": getattr(lane.state, "value", str(getattr(lane, "state", ""))),
                "burns": getattr(proxy, "burns", 0),
            })

    return {
        "fail_closed": True,
        "real_ip_exposed": False,
        "credentials_exposed": False,
        "routing": routing,
        "skipped": skipped,
        "lanes": lanes,
        "guarantees": [
            "No provider is called without an exit proxy (fail-closed).",
            "The IP of the machine is never transmitted: everything goes through the account lane.",
            "The credentials never leave the machine: they are read at the time of the request.",
            "No cookie values ​​are returned by the API.",
        ],
    }

