"""MCP ViaRoma server test (stdio transport, no network access required).

Verifies that the server starts, exposes the 5 expected tools, and that the tools
diagnostics respond. The tool `chat` is NOT tested as a real answer
(credentials are required): we check that its failure path is clean.

Run:  .venv/Scripts/python.exe tests/test_mcp_server.py
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(REPO, ".venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable

EXPECTED_TOOLS = {
    "chat",
    "connect_provider",
    "list_providers",
    "list_free_models",
    "session_status",
}

# Starting catalog. The REAL catalog is local state (data/, gitignore):
# a CI checkout does not have it. We therefore sow a minimal and verifiable catalog
# in a temporary directory, to test the TOOL and not the presence of
# data on the machine running the test.
SEED_CATALOG = {
    "seed/frontier-a": {
        "model_id": "seed/frontier-a", "provider": "seed", "tier": "frontier",
        "context_window": 128000, "is_active": True, "metadata": {"ctx_source": "seed"},
    },
    "seed/frontier-b": {
        "model_id": "seed/frontier-b", "provider": "seed", "tier": "frontier",
        "context_window": 65536, "is_active": True, "metadata": {"ctx_source": "seed"},
    },
    "seed/small-c": {
        "model_id": "seed/small-c", "provider": "seed", "tier": "small",
        "context_window": 4096, "is_active": True, "metadata": {"ctx_source": "seed"},
    },
}

failures = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("  [{}] {}{}".format(status, label, (" :: " + detail) if detail else ""))
    if not condition:
        failures.append(label)


def make_workdir():
    """Isolated working directory: the server writes its states there (data/)."""
    workdir = tempfile.mkdtemp(prefix="viaroma-mcp-test-")
    os.makedirs(os.path.join(workdir, "data"), exist_ok=True)
    with open(os.path.join(workdir, "data", "free_models_catalog.json"),
              "w", encoding="utf-8") as fh:
        json.dump(SEED_CATALOG, fh, indent=2)
    return workdir


async def main():
    # The server's stdout is reserved for the protocol: any stray line
    # (print) breaks JSON-RPC reading from the client. We capture stderr for
    # detect, and we require that no parsing errors appear.
    workdir = make_workdir()
    err_path = os.path.join(workdir, "mcp_stderr.log")
    err_file = open(err_path, "w", encoding="utf-8", errors="replace")

    params = StdioServerParameters(
        command=PYTHON,
        args=["-m", "src.mcp_server"],
        cwd=workdir,
        env=dict(os.environ, PYTHONPATH=REPO),
        errlog=err_file,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            print("== exposed tools ==")
            check("5 exposed tools", names == EXPECTED_TOOLS,
                  "obtenu={}".format(sorted(names)))
            for t in tools.tools:
                description = (t.description or "").strip().splitlines()[0]
                # Windows consoles may use cp1252 and cannot print MCP
                # descriptions containing emoji or other Unicode characters.
                safe_description = description.encode(
                    sys.stdout.encoding or "utf-8", errors="replace"
                ).decode(sys.stdout.encoding or "utf-8", errors="replace")
                print("       - {} : {}".format(t.name, safe_description))

            print("== list_providers ==")
            res = await session.call_tool("list_providers", {})
            payload = json.loads(res.content[0].text)
            check("liste non vide", payload.get("total", 0) > 0, "total={}".format(payload.get("total")))
            check("claude_web present", any(p["provider_key"] == "claude_web" for p in payload["providers"]))
            check("derived categories", all(p.get("category") in ("web", "api") for p in payload["providers"]))

            # No secret VALUE should be released. needs_credentials does not contain
            # than field NAMES, this is the list of credentials to provide.
            SECRET_KEYS = {"cookies", "cookie", "password", "token", "access_token",
                           "api_key", "secret", "auth_token", "device_id", "org_id"}
            leaked = []

            def walk(node, path=""):
                if isinstance(node, dict):
                    for k, v in node.items():
                        if k in SECRET_KEYS and v:
                            leaked.append(path + "/" + k)
                        walk(v, path + "/" + str(k))
                elif isinstance(node, list):
                    for i, v in enumerate(node):
                        walk(v, path + "[{}]".format(i))

            walk(payload)
            check("no secret value exposed", not leaked, "trouve={}".format(leaked))
            check("needs_credentials = field names only",
                  all(isinstance(n, str) for p in payload["providers"] for n in p.get("needs_credentials", [])))

            print("== list_free_models ==")
            res = await session.call_tool("list_free_models", {"tier": "frontier", "limit": 5})
            payload = json.loads(res.content[0].text)
            check("JSON response", "models" in payload, "cles={}".format(list(payload.keys())))
            check("limite respectee", len(payload.get("models", [])) <= 5,
                  "n={}".format(len(payload.get("models", []))))
            check("catalogue charge (lifespan)", payload.get("total_catalog", 0) >= len(SEED_CATALOG),
                  "total_catalog={}".format(payload.get("total_catalog")))
            check("frontier models available", payload.get("count", 0) >= 2,
                  "count={}".format(payload.get("count")))
            check("filter by tier applied",
                  all(m.get("tier") == "frontier" for m in payload.get("models", [])),
                  "tiers={}".format(sorted({str(m.get("tier")) for m in payload.get("models", [])})))
            # Call without cutting limit: the sown models must be there.
            res_all = await session.call_tool("list_free_models", {"tier": "frontier", "limit": 500})
            all_models = json.loads(res_all.content[0].text).get("models", [])
            ids = {m.get("model_id") for m in all_models}
            check("the sown models are exposed",
                  {"seed/frontier-a", "seed/frontier-b"} <= ids,
                  "ids={}".format(sorted(ids)[:8]))
            check("a model from another party is filtered",
                  "seed/small-c" not in ids, "ids={}".format(sorted(ids)[:8]))

            print("== session_status ==")
            res = await session.call_tool("session_status", {})
            payload = json.loads(res.content[0].text)
            for key in ("sessions", "egress", "cascade", "lanes"):
                check("key " + key, key in payload)
            check("accounts loaded (lifespan)", payload["sessions"].get("total_accounts", 0) > 0,
                  "total_accounts={}".format(payload["sessions"].get("total_accounts")))

            print("== connect_provider (clean refusal without credentials) ==")
            res = await session.call_tool("connect_provider", {"provider": "claude_web"})
            text = res.content[0].text
            check("no traceback", "Traceback" not in text, text[:120])
            check("message explicite", text.startswith("ERROR:") or text.startswith("{"),
                  text[:120])

            print("== cat (clean failure path) ==")
            res = await session.call_tool("chat", {"prompt": "ping"})
            text = res.content[0].text
            check("no traceback", "Traceback" not in text, text[:120])
            check("message explicite", text.startswith("ERROR:") or len(text) > 0, text[:120])

    err_file.flush()
    err_file.close()
    stderr_text = ""
    try:
        with open(err_path, "r", encoding="utf-8", errors="replace") as fh:
            stderr_text = fh.read()
    except OSError:
        pass
    shutil.rmtree(workdir, ignore_errors=True)

    print("== clean stdout (MCP protocol) ==")
    check("no JSON-RPC parsing error", "Invalid JSON" not in stderr_text,
          stderr_text.strip().splitlines()[-1][:120] if stderr_text.strip() else "")
    check("no traceback", "Traceback" not in stderr_text)

    print("")
    if failures:
        print("FAILED: {} check(s): {}".format(len(failures), ", ".join(failures)))
        return 1
    print("OK: MCP server operational")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
