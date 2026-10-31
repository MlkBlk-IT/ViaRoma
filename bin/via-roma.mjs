#!/usr/bin/env node
// via-roma: launches the OpenAI-compatible HTTP API + the Roma Aeterna dashboard.
//
// Listening by default on 127.0.0.1 only (VIAROMA_HOST / VIAROMA_PORT
// to override). The dashboard shows the routing state of the account: it does not
// must not go to the local network by default.
import { spawn } from "node:child_process";
import { prepare, childEnv, homeDir, eprint } from "./_python.mjs";

const py = prepare();
const args = process.argv.slice(2);

const child = spawn(py.cmd, [...py.args, "-m", "src.main", ...args], {
  cwd: homeDir(),
  env: childEnv(),
  stdio: "inherit",
  windowsHide: true,
});

child.on("error", (err) => {
  eprint("[via-roma] Failed to launch HTTP server: " + err.message);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) process.exit(1);
  process.exit(code === null ? 0 : code);
});
