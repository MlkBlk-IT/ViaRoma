import asyncio
import json
import os
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from src.core.cascade import CascadeManager, FallbackConfig
from src.schemas import ChatCompletionRequest
from src.hunter.hunter import FreeHunter
from src.proxy.egress_lanes import create_egress_pool
from src.proxy.identity import IdentityManager
from src.sessions.session_manager import SessionManager
from src.dashboard.routes import router as dashboard_router
from src.dashboard import config_io

app = FastAPI(title="Roma - Infinite Frontier Proxy")

# Pool egress: Disposable exit IP, persistent lanes 1:1 per account.
egress_pool = create_egress_pool()
# Browser identity by account (UA, local, zone, screen, canvas).
identities = IdentityManager(path="data/identities.json")
sessions = SessionManager(egress_pool=egress_pool, identity_manager=identities)
cascade = CascadeManager(
    on_burn=sessions.burn_lane,
    context_provider=sessions.get_provider_contexts,
    on_rotate=sessions.rotate_to_next_account,
)
hunter = FreeHunter()

# Components exposed to the dashboard (read only via app.state).
app.state.egress_pool = egress_pool
app.state.identities = identities
app.state.sessions = sessions
app.state.cascade = cascade
app.state.hunter = hunter

# --- ViaRoma Dashboard (control UI) ---
STATIC_DIR = os.path.join(os.path.dirname(__file__), "dashboard", "static")


def _chunk_text(chunk) -> str:
    """Extract text from a ChatChunk (delta.content)."""
    try:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return ""
        delta = getattr(choices[0], "delta", None)
        return (getattr(delta, "content", None) or "")
    except Exception:
        return ""

app.include_router(dashboard_router)

# 3D models of the Coliseum (GLB). They are large (8 MB / 24 MB): they do not
# are NOT in the repository, they are uploaded by scripts/fetch_3d_assets.py
# and served from data/models/. The dashboard falls on a version
# procedural if the file is missing.
# WARNING: this route must be declared BEFORE mount /dashboard/static,
# otherwise StaticFiles intercepts the path and returns 404.
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "models")


@app.get("/dashboard/static/models/{filename}", include_in_schema=False)
async def serve_3d_model(filename: str):
    """Serves a local 3D model (colosseum-today.glb / colosseum-ad-80.glb).

    Local file server only: no remote URLs, no leaks.
    """
    safe = os.path.basename(filename)
    if not safe.lower().endswith(".glb"):
        raise HTTPException(status_code=400, detail="format non servi")
    path = os.path.join(MODELS_DIR, safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="missing model: launch scripts/fetch_3d_assets.py")
    return FileResponse(path, media_type="model/gltf-binary")


if os.path.isdir(STATIC_DIR):
    app.mount("/dashboard/static", StaticFiles(directory=STATIC_DIR), name="dashboard-static")

@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/dashboard/")

@app.get("/dashboard", include_in_schema=False)
@app.get("/dashboard/", include_in_schema=False)
async def dashboard_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.on_event("startup")
async def startup_event():
    # Missing config skeletons (never overwrites an existing file).
    created = config_io.ensure_defaults()
    if created:
        print("[dashboard] config creee:", ",".join(created))
    # Egress: Loads persisted lanes BEFORE the cascade. Without lane, one
    # account has no exit IP -> it is failed (fail-closed).
    egress_pool.load()
    egress_pool.start(interval_seconds=120)
    # Sessions: accounts + persisted sessions. Lane burn prerequisites
    # (without charge accounts, provider_accounts remains empty and no burn takes place).
    try:
        await sessions.initialize()
        print("[sessions] accounts loaded:", len(sessions.accounts))
    except Exception as e:
        print("[sessions] init impossible:", e)
    # Routing contexts: IP (lane) + TLS (identity) + UA + account cookies.
    try:
        active = cascade.refresh()
        print("[cascade] providers actifs:", active)
    except Exception as e:
        print("[cascade] refresh providers impossible:", e)
    # Free-Hunter en arriere-plan.
    asyncio.create_task(hunter.run_discovery_loop(interval_seconds=300))

@app.on_event("shutdown")
async def shutdown_event():
    egress_pool.stop()
    egress_pool.save()

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible entry point.

    The FIRST chunk is consumed BEFORE opening the response: if the cascade
    fails (all providers down), we return a real 503 JSON instead of a
    200 with empty body (the response was already_started -> Starlette exception).
    """
    stream = request.stream is not False
    agen = cascade.execute_with_fallback(request)

    first = None
    try:
        async for chunk in agen:
            first = chunk
            break
    except HTTPException:
        await agen.aclose()
        raise
    except Exception as e:
        await agen.aclose()
        raise HTTPException(
            status_code=503,
            detail="All border endpoints have failed. Last log: " + str(e),
        )

    if not stream:
        parts = []
        if first is not None:
            parts.append(_chunk_text(first))
        try:
            async for chunk in agen:
                parts.append(_chunk_text(chunk))
        except Exception:
            pass
        await agen.aclose()
        content = "".join(parts)
        return {
            "id": "chatcmpl-roma",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model or "frontier-auto",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    async def event_stream():
        if first is not None:
            yield f"data: {first.model_dump_json()}\n\n"
        try:
            async for chunk in agen:
                yield f"data: {chunk.model_dump_json()}\n\n"
        except Exception as e:
            # The response is already open: the error goes into the SSE flow.
            yield "data: " + json.dumps(
                {"error": {"message": str(e), "type": "upstream_error"}}
            ) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.get("/v1/egress/stats")
async def egress_stats():
    return egress_pool.get_stats()

def main() -> int:
    """Console entry point: `via-roma` (API HTTP + dashboard Roma Aeterna)."""
    import uvicorn
    # By default we ONLY listen on the local loop: the dashboard exposes
    # routing state (accounts, lanes, exit IP) and should not be
    # exposed to the local network. VIAROMA_HOST=0.0.0.0 remains possible if the user
    # explicitly wants it.
    host = os.environ.get("VIAROMA_HOST", "127.0.0.1")
    port = int(os.environ.get("VIAROMA_PORT", "8000"))
    uvicorn.run("src.main:app", host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    main()
