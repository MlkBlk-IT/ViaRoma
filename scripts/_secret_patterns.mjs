// Secret signatures shared by the release guardrail (prepack)
// and by scanning the repository (scan_secrets).
//
// Rule: a pattern must only match REAL credential forms.
// A false positive in the CI causes the rule to be ignored, so we remain strict.

// Each entry: { name, re, exclude? }
// exclude: list of paths (relative to the root) where one occurrence is
// a known and documented false positive.
export const SECRET_PATTERNS = [
  { name: "GitHub token", re: /ghp_[A-Za-z0-9]{20,}/ },
  { name: "GitHub PAT", re: /github_pat_[A-Za-z0-9_]{20,}/ },
  { name: "Anthropic key", re: /sk-ant-[A-Za-z0-9\-_]{20,}/ },
  { name: "OpenAI-style key", re: /\bsk-[A-Za-z0-9]{24,}/ },
  { name: "AWS access key", re: /\bAKIA[0-9A-Z]{16}\b/ },
  { name: "Google API key", re: /\bAIza[0-9A-Za-z\-_]{30,}/ },
  { name: "Slack token", re: /\bxox[baprs]-[A-Za-z0-9-]{10,}/ },
  { name: "GitLab token", re: /\bglpat-[A-Za-z0-9\-_]{15,}/ },
  { name: "NPM token", re: /\bnpm_[A-Za-z0-9]{30,}/ },
  { name: "PyPI token", re: /\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9\-_]{50,}/ },
  { name: "Private key", re: /-----BEGIN (RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----/ },
  {
    name: "Secret assigne en dur",
    // "api_key": "long_or_short_value" / password = '...'
    re: /(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|pwd)["']?\s*[:=]\s*["'][A-Za-z0-9_\-]{16,}["']/i,
  },
];

// Files that should never contain credentials.
export const SECRET_EXTENSIONS = new Set([
  ".py",
  ".js",
  ".mjs",
  ".cjs",
  ".ts",
  ".yaml",
  ".yml",
  ".json",
  ".toml",
  ".cfg",
  ".ini",
  ".env",
  ".sh",
  ".ps1",
  ".txt",
  ".md",
  ".html",
  ".css",
]);

// Folders ignored by the scan (dependencies, local state, git).
export const SKIP_DIRS = new Set([
  ".git",
  ".venv",
  "venv",
  "node_modules",
  "__pycache__",
  "data",
  "dist",
  "build",
  ".pytest_cache",
  ".mypy_cache",
  "htmlcov",
]);

// Files excluded from scanning, with reason: this file contains patterns
// themselves, he therefore matches his own expressions.
export const SCAN_EXCLUDE_FILES = new Set(["scripts/_secret_patterns.mjs"]);

// ──────────────────────────────────────────────────────────────────────────
// YAML: a secret in plain text under a sensitive key.
// It is the form that passes through the expressions: `password: xxx` WITHOUT
// quotation marks. The env:/file: references and placeholders are legitimate.
// ──────────────────────────────────────────────────────────────────────────
export const YAML_SECRET_KEYS = new Set([
  "password",
  "passwd",
  "pwd",
  "secret",
  "client_secret",
  "api_key",
  "apikey",
  "access_token",
  "auth_token",
  "token",
  "cookie",
  "cookies",
  "private_key",
  "session",
]);

export const YAML_PLACEHOLDERS = new Set([
  "",
  "***",
  "***redacted***",
  "null",
  "none",
  "~",
  "changeme",
  "redacted",
  "x",
]);

// Returns the list of plaintext secrets found in a YAML text.
export function scanYamlSecrets(rel, text) {
  const found = [];
  text.split("\n").forEach((line, i) => {
    // A key can be at the head of a YAML list item: "- password: xxx".
    const m = line.match(/^\s*(?:-\s+)?([A-Za-z0-9_-]+)\s*:\s*(.*)$/);
    if (!m) return;
    const key = m[1].toLowerCase();
    if (!YAML_SECRET_KEYS.has(key)) return;
    let value = m[2].trim();
    if (value.startsWith("#")) return;
    value = value.replace(/\s+#.*$/, "").trim();
    value = value.replace(/^["']|["']$/g, "").trim();
    if (!value) return;
    const low = value.toLowerCase();
    if (low.startsWith("env:") || low.startsWith("file:")) return;
    if (YAML_PLACEHOLDERS.has(low)) return;
    found.push(rel + ":" + (i + 1) + " (key " + key + " plain)");
  });
  return found;
}
