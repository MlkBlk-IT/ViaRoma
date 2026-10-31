#!/usr/bin/env node
// prepack: release guardrail.
//
// Before building the package, we check that what will go to npm /
// PyPI does not contain:
//   - no secrets (GitHub/OpenAI/Anthropic/AWS/Google token, private key),
//   - no real IP of the machine (calculated at runtime, never written
//     hard in the deposit),
//   - no data file (data/, .env, credentials),
//   - and that the 3D assets (three.js) are included.
//
// A violation = exit(1), the package is not built.
import { readdirSync, readFileSync, statSync, existsSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { networkInterfaces } from "node:os";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { SECRET_PATTERNS, SKIP_DIRS } from "./_secret_patterns.mjs";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const eprint = (msg) => process.stderr.write(String(msg) + "\n");

// What goes into the npm package (mirror of package.json "files").
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

// Real IPs of the machine (excluding loopback): they must NEVER leave.
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
    "three.js missing from the package: the 3D dashboard would be silent. " +
      "Relancer scripts/fetch_3d_assets.py or re-sell src/dashboard/static/vendor/three.",
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
    if (re.test(text)) problems.push("secret potentiel (" + name + ") In " + rel);
  }
  for (const ip of ips) {
    if (text.includes(ip)) problems.push("Real IP of the machine (" + ip + ") In " + rel);
  }
  if (/(^|[\\/])data[\\/]/.test(rel)) problems.push("data file in package: " + rel);
}

if (problems.length) {
  eprint("[via-roma] PUBLICATION REFUSEE:");
  for (const p of problems) eprint("  - " + p);
  process.exit(1);
}

eprint(
  "[via-roma] garde-fou publication OK (" +
    files.length +
    " files, " +
    ips.length +
    " IP(s) locale(s) protegees)",
);
