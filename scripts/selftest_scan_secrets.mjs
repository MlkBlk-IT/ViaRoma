#!/usr/bin/env node
// Auto-test du scanner de secrets.
//
// Un garde-fou qu'on ne teste pas ne vaut rien: on verifie que le scanner
// DETECTE les formes de secrets connues (dont celle qui a deja echappe:
// `password: valeur` sans guillemets dans un YAML versionne) et qu'il ne
// signale pas les references legitimes (env:, file:, placeholders).
import { scanYamlSecrets, SECRET_PATTERNS } from "./_secret_patterns.mjs";

const eprint = (msg) => process.stderr.write(String(msg) + "\n");
let failures = 0;

function check(label, condition, detail = "") {
  const status = condition ? "PASS" : "FAIL";
  eprint("  [" + status + "] " + label + (detail ? " :: " + detail : ""));
  if (!condition) failures += 1;
}

// ── YAML: doivent etre detectes ─────────────────────────────────────────
const BAD_YAML = [
  ["password en clair sans guillemets", "accounts:\n  - account_id: a\n    password: REMOVED_SECRET\n"],
  ["password avec guillemets", 'accounts:\n  - password: "hunter2hunter2"\n'],
  ["api_key en clair", "provider:\n  api_key: ABCDEF0123456789ABCDEF\n"],
  ["cookie en clair", "account:\n  cookie: sk-session-abcdefghijklmnop\n"],
  ["token en clair", "account:\n  auth_token: eyJhbGciOiJIUzI1NiJ9abcdefgh\n"],
];

for (const [label, text] of BAD_YAML) {
  const found = scanYamlSecrets("fixture.yaml", text);
  check("detecte: " + label, found.length > 0, JSON.stringify(found));
}

// ── YAML: ne doivent PAS etre detectes ──────────────────────────────────
const GOOD_YAML = [
  ["reference env:", "account:\n  credentials_ref: env:CLAUDE_PASS\n"],
  ["reference file:", "account:\n  credentials_ref: file:data/creds/claude-perso.json\n"],
  ["cle sans valeur", "account:\n  password:\n"],
  ["placeholder", "account:\n  password: '***REDACTED***'\n"],
  ["cle non sensible", "account:\n  priority: 10\n  provider: claude_web\n"],
];

for (const [label, text] of GOOD_YAML) {
  const found = scanYamlSecrets("fixture.yaml", text);
  check("ne signale pas: " + label, found.length === 0, JSON.stringify(found));
}

// ── Expressions: doivent etre detectes ──────────────────────────────────
// Les echantillons sont assembles a l'execution: ce fichier ne doit PAS
// contenir lui-meme un motif detectable (sinon le scan se signale lui-meme).
const BAD_TOKENS = [
  ["GitHub token", "const t = 'gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345';"],
  ["Anthropic key", "const k = 'sk" + "-ant-api03-ABCDEFGHIJKLMNOPQRSTUV';"],
  ["AWS key", "const a = 'AK" + "IAIOSFODNN7EXAMPLE';"],
  ["Google key", "const g = 'AI" + "zaSyABCDEFGHIJKLMNOPQRSTUVWXYZ01234';"],
  ["cle privee", "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEow=="],
];

for (const [label, text] of BAD_TOKENS) {
  const hit = SECRET_PATTERNS.some((p) => p.re.test(text));
  check("detecte: " + label, hit);
}

eprint("");
if (failures) {
  eprint("ECHEC: " + failures + " verification(s) sur le scanner de secrets");
  process.exit(1);
}
eprint("OK: le scanner de secrets detecte les formes connues et ignore les references");
