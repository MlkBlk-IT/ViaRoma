#!/usr/bin/env node
// via-roma: lance l'API HTTP OpenAI-compatible + le dashboard Roma Aeterna.
//
// Ecoute par defaut sur 127.0.0.1 uniquement (VIAROMA_HOST / VIAROMA_PORT
// pour overrider). Le dashboard expose l'etat de routage du compte: il ne
// doit pas partir sur le reseau local par defaut.
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
  eprint("[via-roma] Impossible de lancer le serveur HTTP: " + err.message);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) process.exit(1);
  process.exit(code === null ? 0 : code);
});
