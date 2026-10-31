#!/usr/bin/env node
// via-roma-mcp: launches the ViaRoma MCP (stdio) server.
//
// The MCP protocol speaks to stdout. This launcher must therefore NEVER write
// on stdout: stdio is inherited as is by the Python process, and all
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
  eprint("[via-roma] Unable to launch MCP server: " + err.message);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) process.exit(1);
  process.exit(code === null ? 0 : code);
});
