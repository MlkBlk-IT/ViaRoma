"""
Module: src/dashboard/config_io.py
Role: Lecture/ecriture de la configuration Roma depuis le dashboard.
Securite: toute ecriture cree d'abord une copie horodatee <fichier>.<YYYYmmdd-HHMMSS>.bak
          puis ecrit dans un fichier temporaire et remplace atomiquement.
Aucune suppression: uniquement creation/modification.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Racine de travail: la racine du paquet (checkout source, paquet npm) ou
# VIAROMA_HOME si defini (installation PyPI: les fichiers de config et de
# data doivent atterrir dans un dossier inscriptible par l'utilisateur, pas
# dans site-packages).
ROOT = Path(os.environ.get("VIAROMA_HOME") or Path(__file__).resolve().parents[2])
CONFIG_DIR = ROOT / "config"
BACKUP_DIR = ROOT / "data" / "config_backups"
# Les credentials ne doivent JAMAIS atterrir dans config/accounts.yaml: ce
# fichier est versionne par git. Un secret ecrit la-bas part sur GitHub.
# Ils vivent dans data/creds/ (gitignore) et sont designes par credentials_ref.
CREDS_DIR = ROOT / "data" / "creds"
# Champs considers comme secrets: ils ne doivent pas rester dans le YAML.
SECRET_FIELDS = (
    "username",
    "password",
    "cookie",
    "cookies",
    "api_key",
    "access_token",
    "auth_token",
    "token",
)
BACKSLASH = chr(92)  # backslash Windows, teste sans echappement litteral

# Fichiers exposables au dashboard (nom -> type)
EDITABLE_FILES = {
    "accounts.yaml": "yaml",
    "cascade.yaml": "yaml",
    "egress_pool.yaml": "yaml",
    "hunter.yaml": "yaml",
    "dashboard.json": "json",
}


def _safe_name(name: str) -> str:
    # Refuse tout chemin hors de config/ (anti path-traversal)
    if not name or "/" in name or '\\\\' in name or ".." in name:
        raise ValueError("Nom de fichier invalide: " + repr(name))
    if name not in EDITABLE_FILES:
        raise ValueError("Fichier non exposable: " + repr(name))
    return name


def _parser(kind: str):
    if kind == "yaml":
        import yaml
        return yaml
    return json


def config_path(name: str) -> Path:
    return CONFIG_DIR / _safe_name(name)


def read_config(name: str) -> Dict[str, Any]:
    # Retourne {name, kind, exists, content, parsed, error}
    name = _safe_name(name)
    kind = EDITABLE_FILES[name]
    path = CONFIG_DIR / name
    if not path.exists():
        return {"name": name, "kind": kind, "exists": False, "content": "", "parsed": None, "error": None}
    raw = path.read_text(encoding="utf-8")
    parsed, error = None, None
    try:
        parser = _parser(kind)
        parsed = parser.safe_load(raw) if kind == "yaml" else json.loads(raw)
    except Exception as e:
        error = str(e)
    return {"name": name, "kind": kind, "exists": True, "content": raw, "parsed": parsed, "error": error}


def read_all() -> List[Dict[str, Any]]:
    return [read_config(n) for n in EDITABLE_FILES]


def backup(name: str) -> Optional[str]:
    # Copie horodatee dans data/config_backups/ (jamais de suppression)
    path = config_path(name)
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / (name + "." + stamp + ".bak")
    shutil.copy2(path, dest)
    return str(dest)


def validate(name: str, content: str) -> Optional[str]:
    # Valide le contenu AVANT ecriture. Retourne un message d'erreur ou None.
    kind = EDITABLE_FILES[_safe_name(name)]
    try:
        if kind == "yaml":
            import yaml
            yaml.safe_load(content)
        else:
            json.loads(content)
    except Exception as e:
        return str(e)
    return None


def write_config(name: str, content: str) -> Dict[str, Any]:
    # Backup -> validation -> ecriture atomique. Retourne un rapport.
    name = _safe_name(name)
    err = validate(name, content)
    if err:
        return {"ok": False, "name": name, "error": "contenu invalide: " + err, "backup": None}
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    bak = backup(name)
    path = CONFIG_DIR / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
    return {"ok": True, "name": name, "error": None, "backup": bak, "bytes": len(content)}


def list_backups() -> List[Dict[str, Any]]:
    if not BACKUP_DIR.exists():
        return []
    out = []
    for f in sorted(BACKUP_DIR.glob("*.bak"), key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
        out.append({"file": f.name, "bytes": f.stat().st_size, "mtime": f.stat().st_mtime})
    return out


def default_templates() -> Dict[str, str]:
    """Squelettes crees si absents (aucune donnee sensible, refs env:/file:)."""
    return {
        "accounts.yaml": "# Comptes frontier. credentials_ref: env:VAR | file:chemin\naccounts:\n  - account_id: claude-perso\n    account_type: personal\n    provider: claude_web\n    login_url: https://claude.ai/login\n    success_selector: \"textarea, [contenteditable=true]\"\n    credentials_ref: file:data/creds/claude-perso.json\n    priority: 10\n    max_requests_per_hour: 100\n    cooldown_seconds: 300\n  - account_id: gemini-perso\n    account_type: personal\n    provider: gemini_web\n    login_url: https://gemini.google.com/app\n    success_selector: \"rich-textarea, [contenteditable=true]\"\n    credentials_ref: file:data/creds/gemini-perso.json\n    priority: 5\n",
        "cascade.yaml": "# Cascade de fallback + circuit breaker\nproviders: [claude_web, gemini_web]\nprovider_accounts:\n  claude_web: claude-perso\n  gemini_web: gemini-perso\nmax_retries_per_provider: 2\nbase_backoff_seconds: 0.5\nmax_backoff_seconds: 30\nbackoff_multiplier: 2.0\ncircuit_breaker_threshold: 5\nhalf_open_test_requests: 3\n",
        "egress_pool.yaml": "# Pool egress IP jetables\nlanes_path: data/egress_lanes.json\nprobe_interval: 120\nprobe_timeout: 8\nquarantine_seconds: 600\nenable_tor: true\nstatic_proxies: []\n",
        "hunter.yaml": "# Free-Hunter: decouverte de modeles frontier gratuits\ncatalog_path: data/free_models_catalog.json\nscan_interval: 300\nmin_tier: frontier\n",
        "dashboard.json": "{\n  \"refresh_ms\": 2000,\n  \"port\": 8000,\n  \"theme\": \"roma-eterna\",\n  \"effects\": {\"dust\": true, \"halo\": true, \"columns\": true}\n}\n",
    }


def creds_path(account_id: str) -> Path:
    """Chemin du fichier de credentials d'un compte (dans data/, gitignore)."""
    safe = "".join(c for c in str(account_id) if c.isalnum() or c in "-_.") or "account"
    return CREDS_DIR / (safe + ".json")


def store_credentials(account_id: str, values: Dict[str, Any]) -> str:
    """Ecrit les credentials dans data/creds/ et rend la credentials_ref.

    Regle de securite: config/accounts.yaml est VERSIONNE. Tout secret ecrit
    dedans finit sur GitHub. Les credentials vont donc dans data/creds/
    (gitignore) et le YAML ne porte que la reference.
    """
    path = creds_path(account_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    current: Dict[str, Any] = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            current = {}
    for key, value in values.items():
        if value:
            current[key] = value
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    return "file:data/creds/" + path.name


def read_credentials(ref: str) -> Dict[str, Any]:
    """Lit un credentials_ref (env:VAR | file:chemin) sans l'afficher."""
    if not ref:
        return {}
    if ref.startswith("file:"):
        path = Path(ref[5:])
        if not path.is_absolute():
            path = ROOT / path
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                return {}
    return {}


def strip_inline_credentials(account: Dict[str, Any]) -> bool:
    """Retire les secrets en clair d'un compte. Retourne True si modifie."""
    changed = False
    for field in SECRET_FIELDS:
        if account.get(field):
            account.pop(field, None)
            changed = True
    return changed


def ensure_defaults() -> List[str]:
    # Cree les squelettes manquants. Ne touche jamais un fichier existant.
    created = []
    for name, content in default_templates().items():
        path = CONFIG_DIR / name
        if not path.exists():
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            created.append(name)
    return created
