"""
Module: src/config_loader.py
Role: Load Roma config files (accounts.yaml, etc.) and resolve credentials_ref.
"""
from __future__ import annotations
import os
import json
import yaml
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Working root: package root, or VIAROMA_HOME if defined (install
# PyPI -> dossier inscriptible par l'utilisateur).
ROOT = os.environ.get("VIAROMA_HOME") or os.path.dirname(os.path.dirname(__file__))
CONFIG_DIR = os.path.join(ROOT, "config")


def load_config() -> Dict[str, Any]:
    """Load accounts.yaml and return config dict with resolved accounts."""
    accounts_path = os.path.join(CONFIG_DIR, "accounts.yaml")
    if not os.path.exists(accounts_path):
        return {"accounts": []}
    try:
        with open(accounts_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to load accounts.yaml: %s", e)
        return {"accounts": []}
    
    accounts = data.get("accounts", [])
    for acct in accounts:
        # Resolve credentials_ref -> actual credential values
        ref = acct.get("credentials_ref", "")
        if ref:
            resolved = _resolve_ref(ref)
            if resolved:
                # Merge resolved credentials into account dict
                for k, v in resolved.items():
                    if k not in acct:
                        acct[k] = v
    return data


def _resolve_ref(ref: str) -> Dict[str, str]:
    """Resolve a credentials_ref string -> dict of credential key/values.
    Formats: env:VAR_NAME | file:path/to/creds.json
    """
    if not ref:
        return {}
    if ref.startswith("env:"):
        var_name = ref[4:]
        value = os.environ.get(var_name, "")
        if value:
            try:
                return json.loads(value) if value.startswith("{") else {"token": value}
            except json.JSONDecodeError:
                return {"token": value}
    elif ref.startswith("file:"):
        path = ref[5:]
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)), path)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed to read credentials file %s: %s", path, e)
    return {}
