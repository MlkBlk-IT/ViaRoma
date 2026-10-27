"""
Module: src/proxy/identity.py
Role: Identite de navigateur PAR COMPTE — rotation d'IP + masquage de fingerprint.

Probleme resolu: les services type Z.Code limitent une personne a 1 ou 2 comptes.
Reponse: chaque compte recoit une identite de machine COMPLETE et DISTINCTE
(IP de sortie + empreinte TLS + empreinte navigateur), et la conserve.

Deux invariants:
  1. STABLE  — un compte garde la meme identite d'un bout a l'autre. Changer
     d'identite en cours de session, c'est se faire bannir.
  2. DISTINCTE — deux comptes ne partagent ni IP, ni empreinte. Un service qui
     compte les comptes ne voit qu'une seule personne par identite.

L'identite est DERIVEE d'un seed deterministe = hash(account_id + salt d'install
+ compteur de rotation). Donc:
  - reproductible: le meme seed redonne la meme identite (pas besoin de stocker
    30 champs, on stocke le seed);
  - unique par compte;
  - rotable: un nouveau seed = une nouvelle identite coherente.

Aucun secret ici: ce sont des caracteristiques de navigateur, pas des credentials.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional

# ── Plaques de fingerprint : un profil TLS = une famille de navigateur ──────────
# UA, sec-ch-ua, WebGL, ecran, memoire, coeurs doivent etre COHERENTS entre eux.
# (Chrome 120 sur Windows avec un UA macOS = detection immediate.)

LOCALES = {
    "en-US": ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"],
    "en-GB": ["Europe/London"],
    "fr-CA": ["America/Toronto", "America/Montreal"],
    "de-DE": ["Europe/Berlin", "Europe/Vienna"],
    "es-ES": ["Europe/Madrid"],
}

BROWSER_TEMPLATES = {
    "chrome120": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "platform": "Win32",
        "sec_ch_ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "sec_ch_ua_platform": '"Windows"',
        "webgl_variants": [
            ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) Iris Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ],
        "screens": [(1920, 1080), (1536, 864), (1600, 900), (2560, 1440), (1366, 768)],
        "device_memory": [8, 16, 4],
        "hardware_concurrency": [8, 12, 4, 6, 16],
        "viewports": [(1920, 1080), (1536, 864), (1600, 900), (1440, 900)],
    },
    "chrome119": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "platform": "Win32",
        "sec_ch_ua": '"Not_A Brand";v="8", "Chromium";v="119", "Google Chrome";v="119"',
        "sec_ch_ua_platform": '"Windows"',
        "webgl_variants": [
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ],
        "screens": [(1920, 1080), (2560, 1440), (1680, 1050), (1600, 900)],
        "device_memory": [8, 16, 32],
        "hardware_concurrency": [8, 12, 16, 6],
        "viewports": [(1920, 1080), (2560, 1440), (1680, 1050)],
    },
    "firefox133": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "platform": "Win32",
        "sec_ch_ua": "",
        "sec_ch_ua_platform": "",
        "webgl_variants": [
            ("Mozilla", "Mozilla (Windows; AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Mozilla", "Mozilla (Windows; Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ],
        "screens": [(1920, 1080), (1536, 864), (1440, 900), (2560, 1440)],
        "device_memory": [8, 16],
        "hardware_concurrency": [8, 12, 4],
        "viewports": [(1920, 1080), (1536, 864), (1440, 900)],
    },
    "safari17": {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "platform": "MacIntel",
        "sec_ch_ua": "",
        "sec_ch_ua_platform": "",
        "webgl_variants": [
            ("Apple Inc.", "Apple M2 Pro"),
            ("Apple Inc.", "Apple M1 Pro"),
        ],
        "screens": [(1512, 982), (1728, 1117), (1440, 900), (2560, 1440)],
        "device_memory": [8, 16],
        "hardware_concurrency": [8, 10, 12],
        "viewports": [(1512, 982), (1728, 1117), (1440, 900)],
    },
}

DEFAULT_TLS_PROFILE = "chrome120"


def _hash_seed(*parts: str) -> int:
    raw = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16], 16)


@dataclass
class IdentityProfile:
    """Identite complete d'un compte. Derivee, jamais stockee en clair comme secret."""
    identity_id: str
    account_id: str
    seed: int
    tls_profile: str
    user_agent: str
    platform: str
    sec_ch_ua: str = ""
    sec_ch_ua_platform: str = ""
    webgl_vendor: str = ""
    webgl_renderer: str = ""
    locale: str = "en-US"
    timezone: str = "America/New_York"
    screen_w: int = 1920
    screen_h: int = 1080
    viewport_w: int = 1920
    viewport_h: int = 1080
    device_memory: int = 8
    hardware_concurrency: int = 8
    canvas_seed: int = 0
    noise: float = 0.00002
    rotation: int = 0
    created_at: float = field(default_factory=time.time)
    rotated_at: float = 0.0
    last_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def fingerprint_hash(self) -> str:
        """Empreinte complete (tout ce qui distingue une machine d'une autre).
        Le UA seul ne suffit pas: beaucoup de vrais utilisateurs partagent la
        meme version de Chrome. Ce qui compte: canvas, ecran, fuseau, WebGL,
        memoire, coeurs + l'IP de sortie."""
        raw = "|".join([
            self.user_agent, self.platform, self.locale, self.timezone,
            "{}x{}".format(self.screen_w, self.screen_h),
            "{}x{}".format(self.viewport_w, self.viewport_h),
            self.webgl_vendor, self.webgl_renderer,
            str(self.device_memory), str(self.hardware_concurrency),
            str(self.canvas_seed), self.tls_profile,
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def from_dict(cls, data: dict) -> "IdentityProfile":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def headers(self) -> Dict[str, str]:
        """Headers HTTP coherents avec l'empreinte (UA + langue + client hints)."""
        h = {
            "User-Agent": self.user_agent,
            "Accept-Language": self.locale + ",en;q=0.9",
        }
        if self.sec_ch_ua:
            h["Sec-CH-UA"] = self.sec_ch_ua
            h["Sec-CH-UA-Platform"] = self.sec_ch_ua_platform
            h["Sec-CH-UA-Mobile"] = "?0"
        return h

    def context_kwargs(self) -> dict:
        """Arguments pour Playwright/Camoufox new_context()."""
        return {
            "viewport": {"width": self.viewport_w, "height": self.viewport_h},
            "screen": {"width": self.screen_w, "height": self.screen_h},
            "locale": self.locale,
            "timezone_id": self.timezone,
            "user_agent": self.user_agent,
            "device_scale_factor": 1,
            "has_touch": False,
            "is_mobile": False,
        }

    def summary(self) -> dict:
        """Resume affichable (pas de secret dedans)."""
        return {
            "identity_id": self.identity_id,
            "fingerprint_hash": self.fingerprint_hash,
            "account_id": self.account_id,
            "tls_profile": self.tls_profile,
            "user_agent": self.user_agent,
            "platform": self.platform,
            "locale": self.locale,
            "timezone": self.timezone,
            "screen": "{}x{}".format(self.screen_w, self.screen_h),
            "device_memory": self.device_memory,
            "hardware_concurrency": self.hardware_concurrency,
            "rotation": self.rotation,
            "rotated_at": self.rotated_at,
            "last_reason": self.last_reason,
        }


def derive_profile(account_id: str, tls_profile: str = DEFAULT_TLS_PROFILE,
                   seed: Optional[int] = None, rotation: int = 0) -> IdentityProfile:
    """Derive une identite coherente et reproductible pour un compte."""
    tls_profile = tls_profile if tls_profile in BROWSER_TEMPLATES else DEFAULT_TLS_PROFILE
    tpl = BROWSER_TEMPLATES[tls_profile]
    if seed is None:
        seed = _hash_seed(account_id, tls_profile, rotation)
    rng = random.Random(seed)

    locale = rng.choice(list(LOCALES.keys()))
    timezone = rng.choice(LOCALES[locale])
    screen = rng.choice(tpl["screens"])
    viewport = rng.choice(tpl["viewports"])
    if viewport[0] > screen[0]:
        viewport = (screen[0], min(viewport[1], screen[1]))
    webgl_vendor, webgl_renderer = rng.choice(tpl["webgl_variants"])

    return IdentityProfile(
        identity_id="id_" + hashlib.sha256(
            ("%s|%s" % (account_id, seed)).encode("utf-8")).hexdigest()[:10],
        account_id=account_id,
        seed=int(seed),
        tls_profile=tls_profile,
        user_agent=tpl["user_agent"],
        platform=tpl["platform"],
        sec_ch_ua=tpl["sec_ch_ua"],
        sec_ch_ua_platform=tpl["sec_ch_ua_platform"],
        webgl_vendor=webgl_vendor,
        webgl_renderer=webgl_renderer,
        locale=locale,
        timezone=timezone,
        screen_w=screen[0],
        screen_h=screen[1],
        viewport_w=viewport[0],
        viewport_h=viewport[1],
        device_memory=rng.choice(tpl["device_memory"]),
        hardware_concurrency=rng.choice(tpl["hardware_concurrency"]),
        canvas_seed=rng.randint(1, 999983),
        noise=round(rng.uniform(0.00001, 0.00004), 6),
        rotation=rotation,
    )


class IdentityManager:
    """Gestionnaire d'identites par compte. Persiste dans data/identities.json."""

    def __init__(self, path: str = "data/identities.json"):
        self.path = Path(path)
        self.identities: Dict[str, IdentityProfile] = {}
        self.salt = ""
        self._load()

    # --- persistance ---

    def _load(self):
        try:
            if not self.path.exists():
                self.salt = hashlib.sha256(
                    (str(self.path) + "|" + str(time.time())).encode("utf-8")).hexdigest()[:16]
                self.save()
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.salt = data.get("salt", "")
            for acc, prof in (data.get("identities") or {}).items():
                self.identities[acc] = IdentityProfile.from_dict(prof)
            if not self.salt:
                self.salt = hashlib.sha256(
                    (str(self.path) + "|" + str(time.time())).encode("utf-8")).hexdigest()[:16]
        except Exception:
            self.identities = {}
            self.salt = hashlib.sha256(str(time.time()).encode("utf-8")).hexdigest()[:16]

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "salt": self.salt,
                "identities": {k: v.to_dict() for k, v in self.identities.items()},
            }
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    # --- API ---

    def get(self, account_id: str, tls_profile: str = DEFAULT_TLS_PROFILE) -> IdentityProfile:
        """Renvoie l'identite du compte, en la creant si besoin. STABLE."""
        prof = self.identities.get(account_id)
        if prof is None:
            prof = derive_profile(account_id, tls_profile, seed=_hash_seed(self.salt, account_id))
            self.identities[account_id] = prof
            self.save()
        return prof

    def rotate(self, account_id: str, reason: str = "manual",
               tls_profile: str = DEFAULT_TLS_PROFILE) -> IdentityProfile:
        """Nouvelle identite pour le compte (nouveau seed). A appeler avec le burn
        de lane: IP ET empreinte changent ensemble, jamais l'une sans l'autre."""
        old = self.identities.get(account_id)
        rotation = (old.rotation + 1) if old else 1
        prof = derive_profile(
            account_id, tls_profile,
            seed=_hash_seed(self.salt, account_id, "rot", rotation, str(time.time())),
            rotation=rotation,
        )
        prof.rotated_at = time.time()
        prof.last_reason = reason
        self.identities[account_id] = prof
        self.save()
        return prof

    def all(self) -> List[IdentityProfile]:
        return list(self.identities.values())

    def status(self) -> dict:
        return {
            "total_identities": len(self.identities),
            "identities": [p.summary() for p in self.identities.values()],
        }

    def collisions(self) -> List[dict]:
        """Comptes qui partagent la meme empreinte (a corriger: ils se font bannir
        mutuellement). Repose sur l'identity_id, qui encode seed+compte."""
        seen: Dict[str, List[str]] = {}
        for acc, prof in self.identities.items():
            seen.setdefault(prof.identity_id, []).append(acc)
        return [{"identity_id": k, "accounts": v} for k, v in seen.items() if len(v) > 1]

    def distinct_ua_count(self) -> int:
        return len({p.user_agent for p in self.identities.values()})

    def distinct_fingerprint_count(self) -> int:
        """Nombre d'empreintes navigateur reellement distinctes (pas seulement l'UA)."""
        return len({p.fingerprint_hash for p in self.identities.values()})
