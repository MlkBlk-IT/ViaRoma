#!/usr/bin/env node
// via-roma-mcp: lance le serveur MCP (stdio) de ViaRoma.
//
// Le protocole MCP parle sur stdout. Ce lanceur ne doit donc JAMAIS ecrire
// sur stdout: stdio est herite tel quel par le processus Python, et tous les
// diagnostics partent sur stderr.
import { spawn } from "node:child_process";
import { prepare, childEnv, homeDir, eprint } from "./_python.mjs";

const py = prepare();
const args = process.argv.slice(2);

const child = spawn(py.cmd, [...py.args, "-m", "src.mcp_server", ...args], {
  cwd: homeDir(),
  env: childEnv(),
  stdio: "inherit",
  windowsHide: true,
});

child.on("error", (err) => {
  eprint("[via-roma] Impossible de lancer le serveur MCP: " + err.message);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) process.exit(1);
  process.exit(code === null ? 0 : code);
});
