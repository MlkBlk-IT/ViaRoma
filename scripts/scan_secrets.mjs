#!/usr/bin/env node
// Scan de secrets sur TOUT le depot (et pas seulement sur ce qui part dans
// le paquet). A faire tourner en CI: un credential committe doit casser la
// build, pas etre decouvert un mois plus tard.
//
// Exclusions: .git, .venv, node_modules, data/ (etat local), __pycache__.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  SECRET_PATTERNS,
  SECRET_EXTENSIONS,
  SKIP_DIRS,
  SCAN_EXCLUDE_FILES,
  scanYamlSecrets,
} from "./_secret_patterns.mjs";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const eprint = (msg) => process.stderr.write(String(msg) + "\n");

function walk(dir, out) {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue;
    const full = join(dir, entry);
    let st;
    try {
      st = statSync(full);
    } catch {
      continue;
    }
    if (st.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

const problems = [];
let scanned = 0;

for (const file of walk(ROOT, [])) {
  const rel = relative(ROOT, file).split(sep).join("/");
  if (SCAN_EXCLUDE_FILES.has(rel)) continue;
  const dot = rel.slice(rel.lastIndexOf("."));
  if (!SECRET_EXTENSIONS.has(dot.toLowerCase())) continue;
  let text;
  try {
    text = readFileSync(file, "utf8");
  } catch {
    continue;
  }
  scanned += 1;
  for (const { name, re } of SECRET_PATTERNS) {
    const match = text.match(re);
    if (match) {
      const at = text.slice(0, match.index).split("\n").length;
      problems.push(rel + ":" + at + "  (" + name + ")");
    }
  }
  if (dot === ".yaml" || dot === ".yml") {
    for (const p of scanYamlSecrets(rel, text)) problems.push(p);
  }
}

if (problems.length) {
  eprint("[via-roma] SECRETS DETECTES dans le depot:");
  for (const p of problems) eprint("  - " + p);
  eprint("[via-roma] Si c'est un faux positif (exemple de documentation),");
  eprint("             corrige la source plutot que de desactiver le scan.");
  process.exit(1);
}

eprint("[via-roma] scan de secrets OK (" + scanned + " fichiers, " + SECRET_PATTERNS.length + " signatures)");
