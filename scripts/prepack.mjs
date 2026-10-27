#!/usr/bin/env node
// prepack: garde-fou de publication.
//
// Avant de construire le paquet, on verifie que ce qui va partir sur npm /
// PyPI ne contient:
//   - aucun secret (token GitHub/OpenAI/Anthropic/AWS/Google, cle privee),
//   - aucune IP reelle de la machine (calculee a l'execution, jamais ecrite
//     en dur dans le depot),
//   - aucun fichier de donnees (data/, .env, credentials),
//   - et que les assets 3D (three.js) sont bien inclus.
//
// Une violation = exit(1), le paquet n'est pas construit.
import { readdirSync, readFileSync, statSync, existsSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { networkInterfaces } from "node:os";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { SECRET_PATTERNS, SKIP_DIRS } from "./_secret_patterns.mjs";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const eprint = (msg) => process.stderr.write(String(msg) + "\n");

// Ce qui part dans le paquet npm (miroir de package.json "files").
const INCLUDE_DIRS = ["bin", "src", "config"];
const INCLUDE_FILES = [
  "requirements.txt",
  "LICENSE",
  "README.md",
  "CREDITS.md",
  "SECURITY.md",
];

function walk(dir, out) {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue;
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

// IP reelles de la machine (hors loopback): elles ne doivent JAMAIS partir.
function localIPs() {
  const ips = new Set();
  for (const list of Object.values(networkInterfaces())) {
    for (const net of list || []) {
      if (net.family === "IPv4" && !net.internal) ips.add(net.address);
    }
  }
  return [...ips];
}

const problems = [];
const files = [];
for (const d of INCLUDE_DIRS) {
  const full = join(ROOT, d);
  if (existsSync(full)) walk(full, files);
}
for (const f of INCLUDE_FILES) {
  const full = join(ROOT, f);
  if (existsSync(full)) files.push(full);
}

if (!files.some((f) => f.endsWith(join("static", "vendor", "three", "three.module.js")))) {
  problems.push(
    "three.js absent du paquet: le dashboard 3D serait muet. " +
      "Relancer scripts/fetch_3d_assets.py ou re-vendre src/dashboard/static/vendor/three.",
  );
}

const ips = localIPs();
for (const file of files) {
  const rel = relative(ROOT, file).split(sep).join("/");
  let text;
  try {
    text = readFileSync(file, "utf8");
  } catch {
    continue;
  }
  for (const { name, re } of SECRET_PATTERNS) {
    if (re.test(text)) problems.push("secret potentiel (" + name + ") dans " + rel);
  }
  for (const ip of ips) {
    if (text.includes(ip)) problems.push("IP reelle de la machine (" + ip + ") dans " + rel);
  }
  if (/(^|[\\/])data[\\/]/.test(rel)) problems.push("fichier de donnees dans le paquet: " + rel);
}

if (problems.length) {
  eprint("[via-roma] PUBLICATION REFUSEE:");
  for (const p of problems) eprint("  - " + p);
  process.exit(1);
}

eprint(
  "[via-roma] garde-fou publication OK (" +
    files.length +
    " fichiers, " +
    ips.length +
    " IP(s) locale(s) protegees)",
);
