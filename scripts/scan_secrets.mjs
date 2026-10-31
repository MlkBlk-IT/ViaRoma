#!/usr/bin/env node
// Scanning secrets on the WHOLE repository (and not just on what goes into
// the package). To run in CI: a credential commit must break the
// build, not be discovered a month later.
//
// Exclusions: .git, .venv, node_modules, data/ (local state), __pycache__.
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
  eprint("[via-roma] SECRETS DETECTED in the repository:");
  for (const p of problems) eprint("  - " + p);
  eprint("[via-roma] If it's a false positive (documentation example),");
  eprint("             fixes the source rather than disabling scanning.");
  process.exit(1);
}

eprint("[via-roma] secrets scan OK (" + scanned + " files, " + SECRET_PATTERNS.length + " signatures)");
