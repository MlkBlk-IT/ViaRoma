// Resolution of the Python interpreter + checking dependencies.
// ABSOLUTE RULE: stdout is RESERVED for the MCP protocol (JSON-RPC line by
// line). Any diagnosis therefore goes through stderr, never through stdout.
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const PKG_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));

export const eprint = (msg) => process.stderr.write(String(msg) + "\n");

const MIN_VERSION = [3, 12];

// Dependencies declared in pyproject.toml. The launcher refuses to start
// if one is missing: better a clear failure than a half-configured startup.
const DEPS = [
  "fastapi",
  "uvicorn",
  "pydantic",
  "curl_cffi",
  "aiohttp",
  "mcp",
  "yaml",
];

function candidates() {
  const list = [];
  const forced = process.env.VIAROMA_PYTHON;
  if (forced) list.push({ cmd: forced, args: [] });
  if (process.platform === "win32") {
    list.push({ cmd: "py", args: ["-3.12"] });
    list.push({ cmd: "python", args: [] });
    list.push({ cmd: "python3", args: [] });
  } else {
    list.push({ cmd: "python3.12", args: [] });
    list.push({ cmd: "python3", args: [] });
    list.push({ cmd: "python", args: [] });
  }
  return list;
}

function probe(candidate) {
  let res;
  try {
    res = spawnSync(
      candidate.cmd,
      [...candidate.args, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
      { encoding: "utf8", windowsHide: true },
    );
  } catch {
    return null;
  }
  if (!res || res.status !== 0 || !res.stdout) return null;
  const [maj, min] = res.stdout.trim().split(".").map(Number);
  if (!maj) return null;
  if (maj < MIN_VERSION[0] || (maj === MIN_VERSION[0] && min < MIN_VERSION[1])) return null;
  return { cmd: candidate.cmd, args: candidate.args, version: maj + "." + min };
}

export function findPython() {
  for (const candidate of candidates()) {
    const found = probe(candidate);
    if (found) return found;
  }
  return null;
}

export function missingDeps(py) {
  const script =
    "import importlib.util\n" +
    "missing = [m for m in " +
    JSON.stringify(DEPS) +
    " if importlib.util.find_spec(m) is None]\n" +
    'print(",".join(missing))';
  let res;
  try {
    res = spawnSync(py.cmd, [...py.args, "-c", script], { encoding: "utf8", windowsHide: true });
  } catch {
    return DEPS.slice();
  }
  if (!res || res.status !== 0) return DEPS.slice();
  const out = (res.stdout || "").trim();
  return out ? out.split(",") : [];
}

export function depsHint(py) {
  const req = join(PKG_ROOT, "requirements.txt");
  const pip = py.args.length ? "py -3.12 -m pip" : py.cmd + " -m pip";
  return [
    "[via-roma] Installing dependencies:",
    "  " + pip + " install -r \"" + req + "\"",
    "  (Or: " + pip + " install via-roma  -> paquet PyPI)",
  ].join("\n");
}

export function fail(message) {
  eprint("[via-roma] " + message);
  process.exit(1);
}

// Common entry point: find a usable Python, check the
// dependencies, then return control to the specific launcher.
export function prepare() {
  const py = findPython();
  if (!py) {
    fail(
      "Python 3.12+ not found. Install Python 3.12 or set " +
        "VIAROMA_PYTHON=/chemin/vers/python",
    );
  }
  const missing = missingDeps(py);
  if (missing.length) {
    eprint("[via-roma] Missing dependencies: " + missing.join(", "));
    eprint(depsHint(py));
    process.exit(1);
  }
  return py;
}

export function childEnv() {
  const sep = process.platform === "win32" ? ";" : ":";
  const paths = [PKG_ROOT, process.env.PYTHONPATH].filter(Boolean);
  return {
    ...process.env,
    PYTHONPATH: paths.join(sep),
    PYTHONUNBUFFERED: "1",
    VIAROMA_HOME: homeDir(),
  };
}

// Working directory: package root (config/book + data/cree) or
// VIAROMA_HOME if the user wants to move the state to a given disk.
// The folder is created here: Node fails in ENOENT on a non-existent cwd.
export function homeDir() {
  const dir = process.env.VIAROMA_HOME || PKG_ROOT;
  try {
    mkdirSync(dir, { recursive: true });
  } catch {
    /* the launch will fail lower with a clear message */
  }
  return dir;
}
