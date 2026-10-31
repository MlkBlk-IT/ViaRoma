"""Test isolated from the "failure is a routing signal" chain.

Objective: prove that a 403/429 really goes up through the adapters
(proxy_engine throws NATIVE PermissionError / ResourceWarning exceptions)
triggers a lane burn with the RIGHT account_id, and the lane is
replaced without touching session cookies.

No network access. No production files edit.

Run:  .venv/Scripts/python.exe tests/test_burn_chain.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.cascade import CascadeManager, FallbackConfig
from src.schemas import ChatCompletionRequest

LABEL = "Claude (web)"


class FakeProvider:
    """Simulates an adapter: throws NATIVE exceptions, like proxy_engine."""

    def __init__(self, name, session_id, exc):
        self.name = name
        self.session_id = session_id
        self.exc = exc

    def stream_chat(self, request):
        async def gen():
            raise self.exc
            yield  # pragma: no cover
        return gen()


class FakeLanePool:
    """Simulates EgressLanePool: counts burns and replaces the lane."""

    def __init__(self, account_id):
        self.burns = []
        self.lanes = {account_id: {"proxy": "socks5://old", "cookies": {"session": "keep-me"}}}

    async def burn_lane(self, account_id, reason="403/429"):
        self.burns.append((account_id, reason))
        if account_id in self.lanes:
            self.lanes[account_id]["proxy"] = "socks5://fresh"
        return {"ok": True}


async def _run(exc, account_id="acct-1", load_yaml=False):
    burns = []
    pool = FakeLanePool(account_id)

    async def on_burn(acc, reason):
        burns.append((acc, reason))
        return await pool.burn_lane(acc, reason)

    cfg = FallbackConfig(
        providers=[LABEL],
        provider_accounts={LABEL: account_id},
        max_retries_per_provider=0,
    )
    cm = CascadeManager(config=cfg, on_burn=on_burn, load_yaml=load_yaml)
    cm._providers = {LABEL: FakeProvider(LABEL, account_id, exc)}

    try:
        async for _ in cm.execute_with_fallback(
            ChatCompletionRequest(messages=[{"role": "user", "content": "ping"}])
        ):
            pass
    except Exception:
        pass
    return burns, pool


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("  [{}] {}{}".format(status, label, (" :: " + detail) if detail else ""))
    if not condition:
        check.failures += 1


check.failures = 0


async def main():
    print("== 403 goes back to native PermissionError (real case of adapters) ==")
    burns, pool = await _run(PermissionError("Claude (web) auth expired (403)"))
    check("burn appele", len(burns) == 1, "burns={}".format(burns))
    check("account_id correct", bool(burns) and burns[0][0] == "acct-1",
          "attendu acct-1, obtenu {}".format(burns[0][0] if burns else None))
    check("raison 403", bool(burns) and "403" in burns[0][1],
          "raison={}".format(burns[0][1] if burns else None))
    check("lane remplacee", pool.lanes["acct-1"]["proxy"] == "socks5://fresh")
    check("cookies intacts", pool.lanes["acct-1"]["cookies"]["session"] == "keep-me")

    print("== 429 remonte en ResourceWarning native ==")
    burns, pool = await _run(ResourceWarning("Claude (web) rate-limit (429)"))
    check("burn appele", len(burns) == 1, "burns={}".format(burns))
    check("account_id correct", bool(burns) and burns[0][0] == "acct-1")
    check("raison 429", bool(burns) and "429" in burns[0][1],
          "raison={}".format(burns[0][1] if burns else None))
    check("lane remplacee", pool.lanes["acct-1"]["proxy"] == "socks5://fresh")

    print("== real mapping from accounts.yaml + cascade.yaml (load_yaml=True) ==")
    cm = CascadeManager(on_burn=None, load_yaml=True)
    accounts = cm.breaker.config.provider_accounts
    check("provider_accounts non vide", len(accounts) > 0, "mapping={}".format(accounts))
    check("claude_web -> claude-perso", accounts.get("Claude (web)") == "claude-perso",
          "obtenu={}".format(accounts.get("Claude (web)")))
    check("gemini_web -> gemini-perso", accounts.get("Gemini (web)") == "gemini-perso",
          "obtenu={}".format(accounts.get("Gemini (web)")))

    print("== explicit config of the caller remains priority ==")
    cfg = FallbackConfig(providers=[LABEL], provider_accounts={LABEL: "override-1"})
    cm2 = CascadeManager(config=cfg, on_burn=None, load_yaml=False)
    check("mapping appelant conserve",
          cm2.breaker.config.provider_accounts.get(LABEL) == "override-1",
          "obtenu={}".format(cm2.breaker.config.provider_accounts.get(LABEL)))

    print("")
    if check.failures:
        print("FAILED: {} check(s)".format(check.failures))
        return 1
    print("OK: burn chain cabled end to end")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
