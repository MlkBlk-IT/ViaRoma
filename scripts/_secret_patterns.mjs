// Signatures de secrets partagees par le garde-fou de publication (prepack)
// et par le scan du depot (scan_secrets).
//
// Regle: un motif ne doit matcher que des formes de credentials REELLES.
// Un faux positif dans la CI fait ignorer la regle, donc on reste strict.

// Chaque entree: { name, re, exclude? }
// exclude: liste de chemins (relatifs a la racine) ou l'une occurrence est
// un faux positif connu et documente.
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
    // "api_key": "valeur_longue_ou_courte" / password = '...'
    re: /(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|pwd)["']?\s*[:=]\s*["'][A-Za-z0-9_\-]{16,}["']/i,
  },
];

// Fichiers qui ne doivent jamais contenir de credentials.
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

// Dossiers ignores par le scan (dependances, etat local, git).
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

// Fichiers exclus du scan, avec la raison: ce fichier contient les motifs
// eux-memes, il matche donc ses propres expressions.
export const SCAN_EXCLUDE_FILES = new Set(["scripts/_secret_patterns.mjs"]);

// ──────────────────────────────────────────────────────────────────────────
// YAML: un secret en clair sous une cle sensible.
// C'est la forme qui passe au travers des expressions: `password: xxx` SANS
// guillemets. Les references env:/file: et les placeholders sont legitimes.
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

// Retourne la liste des secrets en clair trouves dans un texte YAML.
export function scanYamlSecrets(rel, text) {
  const found = [];
  text.split("\n").forEach((line, i) => {
    // Une cle peut etre en tete d'item de liste YAML: "- password: xxx".
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
    found.push(rel + ":" + (i + 1) + "  (cle " + key + " en clair)");
  });
  return found;
}
