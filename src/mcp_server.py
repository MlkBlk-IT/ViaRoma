"""
Module: src/mcp_server.py
Role: Serveur MCP ViaRoma — la porte d'entree pour les agents (Hermes, Claude Code,
      tout client MCP). Expose le routage free-frontier, la connexion 'une fois',
      le catalogue de modeles gratuits et l'etat de sante du tunnel.

Le MCP partage le meme noyau que l'API HTTP (src/core, src/proxy, src/sessions):
memes cascades, memes lanes egress, memes sessions. L'etat est persiste sur disque
(data/), donc le dashboard et le MCP voient la meme realite.

Aucun secret n'est expose par un outil: les credentials restent dans le cookie jar
local et seuls des compteurs sont renvoyes.

Usage:
    python -m src.mcp_server                      # stdio (defaut, pour un client MCP)
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
from src.proxy.egress_lanes import EgressLanePool
from src.proxy.identity import IdentityManager
from src.schemas import ChatCompletionRequest
from src.sessions.session_manager import SessionManager

__version__ = "0.1.0"

# --- Noyau partage (memes objets que src/main.py) ---
egress_pool = EgressLanePool(lanes_path="data/egress_lanes.json")
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
    """Cycle de vie: comptes, lanes egress, catalogue, boucle de sante."""
    # Les lanes d'abord: sans lane, un compte n'a pas d'IP de sortie et la
    # cascade l'ecarte (fail-closed, l'IP reelle ne doit jamais sortir).
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
        "ViaRoma donne acces a des modeles frontier gratuits via un point unique.\n"
        "Utilise `chat` pour toute requete de texte: la cascade route en interne vers\n"
        "le meilleur provider disponible et gere seule les 403/429 (rotation d'IP).\n"
        "Un compte se connecte une seule fois via `connect_provider`.\n"
        "Ne demande jamais de credentials a l'utilisateur: lis les dans env:/file:."
    ),
    lifespan=_lifespan,
)


# ============================================================
# OUTIL 1 — chat (point unique de routage)
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
    """Envoie un message a l'IA et retourne la reponse texte.

    La cascade choisit seule le provider (le model n'est pas choisi par l'appelant):
    elle essaie les providers disponibles par ordre de sante, et sur 403/429 elle
    brule la lane egress du compte et rebascule sur un autre.

    Args:
        prompt: Le message a envoyer.
        system: Instruction systeme optionnelle.
        history: Messages precedents, liste de {"role": ..., "content": ...}.
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
        return "ERREUR: " + str(detail)
    out = "".join(parts).strip()
    return out or "ERREUR: reponse vide — aucun provider n'a repondu."


# ============================================================
# OUTIL 2 — connect_provider (le credential 'une fois')
# ============================================================

@server.tool()
async def connect_provider(provider: str) -> str:
    """Connecte un compte a un provider (une seule fois).

    Utilise les credentials deja configures dans accounts.yaml via
    credentials_ref (env:VARIABLE ou file:chemin) puis recolte la session
    (cookies) via Camoufox. Ne renvoie jamais la valeur des credentials.

    Args:
        provider: Cle du provider (ex: claude_web, gemini_web) ou son label.
    """
    from src.proxy.proxy_engine import PROVIDER_META

    key = (provider or "").strip()
    if key and key not in PROVIDER_META:
        for k, meta in PROVIDER_META.items():
            if str(meta.get("label", "")).lower() == key.lower():
                key = k
                break
    if key not in PROVIDER_META:
        return "ERREUR: provider inconnu: %s. Disponibles: %s" % (
            provider, ", ".join(sorted(PROVIDER_META.keys())))

    accounts = [a for a in sessions.accounts.values() if a.provider == key]
    if not accounts:
        return "ERREUR: aucun compte pour %s dans accounts.yaml" % key

    account = None
    for acc in accounts:
        if await sessions._resolve_credentials(acc.credentials_ref):
            account = acc
            break
    if account is None:
        return ("ERREUR: credentials non resolus pour %s. Attendu env:VARIABLE ou "
                "file:chemin (le secret reste chez l'utilisateur)." % key)

    try:
        session = await sessions.get_session(key)
    except Exception as e:
        return "ERREUR: harvest impossible: %s" % e
    if session is None:
        return ("ERREUR: harvest echoue (login/challenge non resolu) pour %s" % key)

    return json.dumps({
        "ok": True,
        "provider": key,
        "label": PROVIDER_META.get(key, {}).get("label", key),
        "account_id": account.account_id,
        "session_id": session.session_id,
        "state": session.state.value,
        "cookie_count": len(session.cookies),
        "login_url": account.login_url,
    }, ensure_ascii=False)


# ============================================================
# OUTIL 3 — list_providers (la matrice web / desktop / CLI)
# ============================================================

@server.tool()
async def list_providers() -> str:
    """Liste les providers connus et leur etat de connexion.

    Chaque provider est un point d'acces: web (frontends navigateur), desktop
    (clients locaux) ou api (passthrough). Renvoie la cle, le label, l'URL de
    connexion, les credentials requis et l'etat de la session.
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
# OUTIL 4 — list_free_models (l'acces gratuit)
# ============================================================

@server.tool()
async def list_free_models(tier: str = "frontier", limit: int = 50) -> str:
    """Liste les modeles gratuits decouverts, filtres par tier.

    Args:
        tier: frontier | large | medium | small (defaut: frontier).
        limit: nombre max de modeles renvoyes.
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
# OUTIL 5 — session_status (la sante du tunnel)
# ============================================================

@server.tool()
async def session_status() -> str:
    """Etat live du routage: providers, sessions, lanes egress, IPs, burns.

    C'est l'outil de diagnostic: si un chat echoue, on regarde ici pour savoir
    si le provider est en cooldown, si la lane est Morte, ou si le pool est vide.
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
# Cycle de vie
# ============================================================

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="via-roma-mcp", description="Serveur MCP ViaRoma")
    parser.add_argument("--transport", default="stdio",
                        choices=["stdio", "sse", "streamable-http"],
                        help="transport MCP (defaut: stdio)")
    parser.add_argument("--port", type=int, default=8001, help="port pour sse/streamable-http")
    parser.add_argument("--host", default="127.0.0.1", help="interface d'ecoute")
    args = parser.parse_args(argv)

    if args.transport == "stdio":
        # stdout est reserve au protocole MCP: rien d'autre ne doit y ecrire.
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
