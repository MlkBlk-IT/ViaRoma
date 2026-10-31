"""
Module: src/mcp_server.py
Role: MCP ViaRoma server — the front door for agents (Hermes, Claude Code,
      any MCP customer). Exposes free-frontier routing, 'one-time' connection,
      the catalog of free models and the health status of the tunnel.

The MCP shares the same core as the HTTP API (src/core, src/proxy, src/sessions):
same stunts, same egress lanes, same sessions. State persists on disk
(data/), so the dashboard and the MCP see the same reality.

No secrets are exposed by a tool: credentials remain in the cookie jar
local and only counters are returned.

Usage:
    python -m src.mcp_server # stdio (default, for an MCP client)
    python -m src.mcp_server --transport streamable-http --port 8001
    python -m src.mcp_server --transport sse --port 8001
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys

from mcp.server.mcpserver import MCPServer

from src.core.cascade import CascadeManager
from src.hunter.hunter import FreeHunter
from src.proxy.egress_lanes import create_egress_pool
from src.proxy.identity import IdentityManager
from src.schemas import ChatCompletionRequest
from src.sessions.session_manager import SessionManager

__version__ = "0.1.0"

# --- Shared core (same objects as src/main.py) ---
egress_pool = create_egress_pool()
identities = IdentityManager(path="data/identities.json")
sessions = SessionManager(egress_pool=egress_pool, identity_manager=identities)
cascade = CascadeManager(
    on_burn=sessions.burn_lane,
    context_provider=sessions.get_provider_contexts,
    on_rotate=sessions.rotate_to_next_account,
)
hunter = FreeHunter()

@contextlib.asynccontextmanager
async def _lifespan(_server):
    """Lifecycle: accounts, egress lanes, catalog, health loop."""
    # Lanes first: without a lane, an account has no exit IP and the
    # to remove it (fail-closed, the real IP must never come out).
    try:
        egress_pool.load()
        egress_pool.start(interval_seconds=120)
    except Exception as e:
        print("[mcp] egress indisponible: %s" % e, file=sys.stderr)
    try:
        await sessions.initialize()
    except Exception as e:
        print("[mcp] sessions indisponibles: %s" % e, file=sys.stderr)
    try:
        cascade.refresh()
    except Exception:
        pass
    hunter.load_catalog()
    hunter.start(interval_seconds=300)
    try:
        yield {}
    finally:
        hunter.stop()
        egress_pool.stop()
        egress_pool.save()


server = MCPServer(
    name="via-roma",
    version=__version__,
    instructions=(
        "ViaRoma provides access to free frontier models via a single point.\n"
        "Use `chat` for any text request: the cascade routes internally to\n"
        "the best provider available and manages 403/429 (IP rotation) alone.\n"
        "An account connects only once via `connect_provider`.\n"
        "Never ask the user for credentials: read them in env:/file:."
    ),
    lifespan=_lifespan,
)


# ============================================================
# TOOL 1 — chat (single point of routing)
# ============================================================

def _chunk_text(chunk) -> str:
    try:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return ""
        delta = getattr(choices[0], "delta", None)
        return (getattr(delta, "content", None) or "")
    except Exception:
        return ""


@server.tool()
async def chat(prompt: str, system: str = "", history: list | None = None) -> str:
    """Sends a message to the AI ​​and returns the text response.

    The cascade chooses the provider alone (the model is not chosen by the caller):
    she tries the available providers by order of health, and on 403/429 she
    burns the egress lane of the account and switches back to another.

    Args:
        prompt: The message to send.
        system: Instruction systeme optionnelle.
        history: Previous messages, list of {"role": ..., "content": ...}.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    for item in (history or []):
        if isinstance(item, dict) and item.get("content") is not None:
            messages.append({"role": str(item.get("role", "user")), "content": str(item.get("content", ""))})
    messages.append({"role": "user", "content": prompt})

    request = ChatCompletionRequest(messages=messages, stream=True)
    parts = []
    try:
        async for chunk in cascade.execute_with_fallback(request):
            text = _chunk_text(chunk)
            if text:
                parts.append(text)
    except Exception as e:
        detail = getattr(e, "detail", None) or str(e)
        return "ERROR: " + str(detail)
    out = "".join(parts).strip()
    return out or "ERROR: empty response — no provider responded."


# ============================================================
# TOOL 2 — connect_provider (the 'once' credential)
# ============================================================

@server.tool()
async def connect_provider(provider: str) -> str:
    """Connect an account to a provider (only once).

    Uses the credentials already configured in accounts.yaml via
    credentials_ref (env:VARIABLE or file:path) then harvests the session
    (cookies) via Playwright/Chrome. Never returns the value of credentials.

    Args:
        provider: Provider key (eg: claude_web, gemini_web) or its label.
    """
    from src.proxy.proxy_engine import PROVIDER_META

    key = (provider or "").strip()
    if key and key not in PROVIDER_META:
        for k, meta in PROVIDER_META.items():
            if str(meta.get("label", "")).lower() == key.lower():
                key = k
                break
    if key not in PROVIDER_META:
        return "ERROR: unknown provider: %s. Disponibles: %s" % (
            provider, ", ".join(sorted(PROVIDER_META.keys())))

    accounts = [a for a in sessions.accounts.values() if a.provider == key]
    if not accounts:
        return "ERROR: no account for %s in accounts.yaml" % key

    try:
        # MCP connection is a manual, visible login. Credentials are optional;
        # requiring them here made the advertised one-click flow impossible.
        session = await sessions.get_session(key, interactive=True)
    except Exception as e:
        return "ERROR: harvest impossible: %s" % e
    if session is None:
        return "ERROR: %s" % (sessions.last_error or ("harvest fails for %s" % key))

    return json.dumps({
        "ok": True,
        "provider": key,
        "label": PROVIDER_META.get(key, {}).get("label", key),
        "account_id": session.account_id,
        "session_id": session.session_id,
        "state": session.state.value,
        "cookie_count": len(session.cookies),
        "login_url": next((a.login_url for a in accounts if a.account_id == session.account_id), ""),
    }, ensure_ascii=False)


# ============================================================
# TOOL 3 — list_providers (the web / desktop / CLI matrix)
# ============================================================

@server.tool()
async def list_providers() -> str:
    """Lists known providers and their connection status.

    Each provider is an access point: web (browser frontends), desktop
    (local clients) or api (passthrough). Returns the key, label, URL of
    connection, required credentials and session state.
    """
    from src.proxy.proxy_engine import PROVIDER_META

    by_provider = {}
    for acc in sessions.accounts.values():
        by_provider.setdefault(acc.provider, []).append(acc.account_id)

    session_state = {}
    for s in sessions.sessions.values():
        session_state.setdefault(s.provider, []).append({
            "session_id": s.session_id,
            "account_id": s.account_id,
            "state": s.state.value,
        })

    out = []
    for key, meta in PROVIDER_META.items():
        out.append({
            "provider_key": key,
            "label": meta.get("label", key),
            "category": "web" if key.endswith("_web") else "api",
            "login_url": meta.get("login_url", ""),
            "needs_credentials": meta.get("credentials", []),
            "configured_accounts": by_provider.get(key, []),
            "sessions": session_state.get(key, []),
        })
    return json.dumps({"providers": out, "total": len(out)}, ensure_ascii=False)


# ============================================================
# TOOL 4 — list_free_models (the free access)
# ============================================================

@server.tool()
async def list_free_models(tier: str = "frontier", limit: int = 50) -> str:
    """List of free models discovered, filtered by tier.

    Args:
        tier: frontier | wide | medium | small (default: border).
        limit: maximum number of models returned.
    """
    wanted = (tier or "frontier").strip().lower()
    rows = []
    for model in hunter.catalog.values():
        model_tier = model.tier.value if hasattr(model.tier, "value") else str(model.tier)
        if wanted and wanted != "all" and model_tier != wanted:
            continue
        if not model.is_active:
            continue
        rows.append({
            "model_id": model.model_id,
            "provider": model.provider,
            "tier": model_tier,
            "context_window": model.context_window,
        })
    rows.sort(key=lambda r: (-(r.get("context_window") or 0), r["model_id"]))
    rows = rows[: max(1, int(limit or 50))]
    return json.dumps({
        "tier": wanted,
        "count": len(rows),
        "total_catalog": len(hunter.catalog),
        "models": rows,
    }, ensure_ascii=False)


# ============================================================
# TOOL 5 — session_status (tunnel health)
# ============================================================

@server.tool()
async def session_status() -> str:
    """Live routing status: providers, sessions, egress lanes, IPs, burns.

    This is the diagnostic tool: if a cat fails, we look here to find out
    if the provider is in cooldown, if the lane is Dead, or if the pool is empty.
    """
    pool_stats = egress_pool.get_stats()
    cascade_stats = cascade.get_stats()
    lanes = []
    for account_id, lane in egress_pool.lanes.items():
        lanes.append({
            "account_id": account_id,
            "lane_id": lane.lane_id,
            "tls_profile": lane.tls_profile,
            "state": lane.state.value,
            "proxy": lane.proxy.url,
            "public_ip": lane.proxy.public_ip,
            "country": lane.proxy.country,
            "latency_ms": round(lane.proxy.latency_ms, 1),
            "rotate_count": lane.rotate_count,
            "burns": lane.proxy.burns,
        })
    return json.dumps({
        "sessions": sessions.get_stats(),
        "egress": pool_stats,
        "cascade": cascade_stats,
        "skipped": cascade.get_skipped(),
        "lanes": lanes,
        "identities": {
            "total": len(identities.all()),
            "distinct_user_agents": identities.distinct_ua_count(),
            "collisions": identities.collisions(),
            "accounts": [
                {
                    "account_id": p.account_id,
                    "identity_id": p.identity_id,
                    "tls_profile": p.tls_profile,
                    "user_agent": p.user_agent,
                    "locale": p.locale,
                    "timezone": p.timezone,
                    "rotation": p.rotation,
                }
                for p in identities.all()
            ],
        },
        "hunter": hunter.get_stats(),
    }, ensure_ascii=False, default=str)


# ============================================================
# Life cycle
# ============================================================

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="via-roma-mcp", description="Serveur MCP ViaRoma")
    parser.add_argument("--transport", default="stdio",
                        choices=["stdio", "sse", "streamable-http"],
                        help="MCP transport (default: stdio)")
    parser.add_argument("--port", type=int, default=8001, help="port for sse/streamable-http")
    parser.add_argument("--host", default="127.0.0.1", help="interface d'ecoute")
    args = parser.parse_args(argv)

    if args.transport == "stdio":
        # stdout is reserved for the MCP protocol: nothing else should be written there.
        server.run(transport="stdio")
        return 0

    import uvicorn
    if args.transport == "sse":
        app = server.sse_app()
    else:
        app = server.streamable_http_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
