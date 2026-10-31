#!/usr/bin/env node
// Self-test of the secrets scanner.
//
// A safeguard that is not tested is worthless: we check that the scanner
// DETECTS known forms of secrets (including one that has already escaped:
// `password: valeur` without quotation marks in a versioned YAML) and that it does not
// does not report legitimate references (env:, file:, placeholders).
import { scanYamlSecrets, SECRET_PATTERNS } from "./_secret_patterns.mjs";

const eprint = (msg) => process.stderr.write(String(msg) + "\n");
let failures = 0;

function check(label, condition, detail = "") {
  const status = condition ? "PASS" : "FAIL";
  eprint("  [" + status + "] " + label + (detail ? " :: " + detail : ""));
  if (!condition) failures += 1;
}

// ── YAML: must be detected ──────────────────── ─────────────────────
const BAD_YAML = [
  ["password in plain text without quotes", "accounts:\n  - account_id: a\n    password: REMOVED_SECRET\n"],
  ["password with quotes", 'accounts:\n  - password: "hunter2hunter2"\n'],
  ["api_key en clair", "provider:\n  api_key: ABCDEF0123456789ABCDEF\n"],
  ["cookie en clair", "account:\n  cookie: sk-session-abcdefghijklmnop\n"],
  ["token en clair", "account:\n  auth_token: eyJhbGciOiJIUzI1NiJ9abcdefgh\n"],
];

for (const [label, text] of BAD_YAML) {
  const found = scanYamlSecrets("fixture.yaml", text);
  check("detecte: " + label, found.length > 0, JSON.stringify(found));
}

// ── YAML: should NOT be detected ──────────────────────────────────
const GOOD_YAML = [
  ["reference env:", "account:\n  credentials_ref: env:CLAUDE_PASS\n"],
  ["reference file:", "account:\n  credentials_ref: file:data/creds/claude-perso.json\n"],
  ["worthless key", "account:\n  password:\n"],
  ["placeholder", "account:\n  password: '***REDACTED***'\n"],
  ["non-sensitive key", "account:\n  priority: 10\n  provider: claude_web\n"],
];

for (const [label, text] of GOOD_YAML) {
  const found = scanYamlSecrets("fixture.yaml", text);
  check("does not report: " + label, found.length === 0, JSON.stringify(found));
}

// ── Expressions: must be detected ──────────────────────────────────
// Samples are assembled at runtime: this file should NOT
// itself contain a detectable pattern (otherwise the scan signals itself).
const BAD_TOKENS = [
  ["GitHub token", "const t = 'gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345';"],
  ["Anthropic key", "const k = 'sk" + "-ant-api03-ABCDEFGHIJKLMNOPQRSTUV';"],
  ["AWS key", "const a = 'AK" + "IAIOSFODNN7EXAMPLE';"],
  ["Google key", "const g = 'AI" + "zaSyABCDEFGHIJKLMNOPQRSTUVWXYZ01234';"],
  ["private key", "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEow=="],
];

for (const [label, text] of BAD_TOKENS) {
  const hit = SECRET_PATTERNS.some((p) => p.re.test(text));
  check("detecte: " + label, hit);
}

eprint("");
if (failures) {
  eprint("FAILURE: " + failures + " verification(s) on the secrets scanner");
  process.exit(1);
}
eprint("OK: secrets scanner detects known forms and ignores references");
