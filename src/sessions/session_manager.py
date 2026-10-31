
"""
Module: src/sessions/session_manager.py
Role: Multi-account management, session rotation, cookie isolation.
Resout: Rate limits per account/IP -> basculement auto (Perso -> Ecole -> Travail).
        Persistence of HttpOnly/Secure cookies to avoid WAF re-auth.
Fusion: managers/session_manager.py (llm-spoofing-system) adapte a Roma:
  - harvest via src.proxy.anti_waf_harvester.ChallengeBypasser (more than utils.bypass_challenge)
  - persistance JSON sur disque (cookie jar isolated per account)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

from src.proxy.anti_waf_harvester import ChallengeBypasser


logger = logging.getLogger(__name__)


class AccountType(Enum):
    PERSONAL = "personal"
    SCHOOL = "school"
    WORK = "work"


class SessionState(Enum):
    ACTIVE = "active"
    RATE_LIMITED = "rate_limited"
    EXPIRED = "expired"
    ERROR = "error"
    CHALLENGE_REQUIRED = "challenge_required"


@dataclass
class AccountConfig:
    account_id: str
    account_type: AccountType
    provider: str
    login_url: str
    success_selector: str
    credentials_ref: str
    priority: int = 0
    max_requests_per_hour: int = 100
    cooldown_seconds: int = 300


@dataclass
class Session:
    session_id: str
    account_id: str
    provider: str
    cookies: Dict[str, str]
    user_agent: str
    state: SessionState = SessionState.ACTIVE
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    request_count: int = 0
    error_count: int = 0
    rate_limit_reset_at: Optional[float] = None
    challenge_count: int = 0

    def is_healthy(self) -> bool:
        if self.state != SessionState.ACTIVE:
            return False
        if self.rate_limit_reset_at and time.time() < self.rate_limit_reset_at:
            return False
        return True

    def mark_rate_limited(self, reset_in_seconds: int = 3600):
        self.state = SessionState.RATE_LIMITED
        self.rate_limit_reset_at = time.time() + reset_in_seconds

    def mark_error(self):
        self.error_count += 1
        if self.error_count >= 3:
            self.state = SessionState.ERROR

    def mark_success(self):
        self.request_count += 1
        self.last_used = time.time()
        self.error_count = max(0, self.error_count - 1)

    def mark_challenge(self):
        self.challenge_count += 1
        if self.challenge_count >= 2:
            self.state = SessionState.CHALLENGE_REQUIRED


class SessionManager:
    """Manages the multi-account session pool.
    - Automatic rotation on rate limit / error / challenge
    - Disk persistence (JSON) for restart survival
    - Strict isolation: cookies never shared between accounts
    """

    def __init__(self, config_path="config/accounts.yaml", sessions_dir="data/sessions", default_proxy=None,
                 egress_pool=None, identity_manager=None):
        self.config_path = self._resolve_config(config_path)
        self.sessions_dir = Path(sessions_dir)
        self.default_proxy = default_proxy
        self.egress_pool = egress_pool   # EgressLanePool: binding lane 1:1 per account
        self.identity_manager = identity_manager  # IdentityManager: fingerprint per account
        self.accounts = {}
        self.sessions = {}
        self.account_sessions = {}
        self._lock = asyncio.Lock()
        self.last_error = ""
        self._interactive_browsers = {}

    def _resolve_config(self, config_path):
        """Where is located accounts.yaml ?

        1) as is (absolute path or relative to the current directory);
        2) otherwise VIAROMA_HOME (PyPI/npm installation);
        3) otherwise the root of the package (checkout source).

        Without this, the dashboard (which reads config/ at the root of the package) and the
        server (which read it relative to the cwd) did not see the same
        file as soon as the process starts somewhere other than in the repository.
        """
        path = Path(config_path)
        if path.is_absolute() or path.exists():
            return path
        import os
        roots = []
        home = os.environ.get("VIAROMA_HOME")
        if home:
            roots.append(Path(home))
        roots.append(Path(__file__).resolve().parents[2])
        for root in roots:
            candidate = root / path
            if candidate.exists():
                return candidate
        return path

    async def load_accounts(self):
        """Load the account config from YAML."""
        import yaml
        if not self.config_path.exists():
            raise FileNotFoundError("Accounts config not found: " + str(self.config_path))
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        for acc_data in data.get("accounts", []):
            acc = AccountConfig(
                account_id=acc_data["account_id"],
                account_type=AccountType(acc_data["account_type"]),
                provider=acc_data["provider"],
                login_url=acc_data["login_url"],
                success_selector=acc_data["success_selector"],
                credentials_ref=acc_data["credentials_ref"],
                priority=acc_data.get("priority", 0),
                max_requests_per_hour=acc_data.get("max_requests_per_hour", 100),
                cooldown_seconds=acc_data.get("cooldown_seconds", 300),
            )
            self.accounts[acc.account_id] = acc
            self.account_sessions.setdefault(acc.account_id, [])

    async def load_persisted_sessions(self):
        """Restores sessions from disk."""
        if not self.sessions_dir.exists():
            return
        for session_file in self.sessions_dir.glob("*.json"):
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
                data["state"] = SessionState(data["state"])
                session = Session(**data)
                if session.state == SessionState.ACTIVE and time.time() - session.created_at < 86400:
                    self.sessions[session.session_id] = session
                    self.account_sessions.setdefault(session.account_id, []).append(session.session_id)
            except Exception:
                continue

    async def initialize(self):
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        await self.load_accounts()
        await self.load_persisted_sessions()

    async def get_session(self, provider, prefer_account_type=None, interactive=False, account_id=None,
                          allow_direct=False):
        """Returns the best session available for a provider.
        Order: account priority > preferred type > health session.
        """
        async with self._lock:
            candidates = [acc for acc in self.accounts.values() if acc.provider == provider]
            if account_id:
                candidates = [acc for acc in candidates if acc.account_id == account_id]
            if not candidates:
                return None
            candidates.sort(key=lambda a: -a.priority)
            if prefer_account_type:
                candidates.sort(key=lambda a: a.account_type != prefer_account_type)
            for account in candidates:
                for sid in self.account_sessions.get(account.account_id, []):
                    session = self.sessions.get(sid)
                    if session and session.is_healthy():
                        return session
                new_session = await self._create_new_session(
                    account, interactive=interactive, allow_direct=allow_direct)
                if new_session:
                    return new_session
            return None

    async def _create_new_session(self, account, interactive=False, allow_direct=False):
        """Create a new session via ChallengeBypasser (login + harvest cookies).
        The egress lane of the account (if pool present) is used as an output proxy.
        The browser carries the identity of the account (UA, locale, timezone, screen):
        this makes each account look like ONE distinct machine, not several accounts
        sharing one fingerprint.

        interactive=True: browser visible, user logs in manually, no credentials needed.
        interactive=False: headless auto-fill using stored credentials.

        FAIL-CLOSED: if no proxy is configured (no egress lane + no default_proxy),
        the browser is NOT opened — the real IP must NEVER be exposed.
        """
        proxy = self._lane_proxy(account.account_id)
        if not proxy and not allow_direct:
            self.last_error = (
                "Connexion bloquee : aucun proxy de sortie valide. "
                "Ajoutez un proxy HTTP/SOCKS5 ou demarrez Tor (127.0.0.1:9050). "
                "L'IP reelle ne sera jamais utilisee."
            )
            logger.error("create_session_blocked_no_proxy account_id=%s", account.account_id)
            return None

        if not proxy and allow_direct:
            self.last_error = ""

        # A lane can exist on disk while its proxy is dead. Probe it before
        # opening Chrome; otherwise the browser could connect directly after a
        # proxy failure, which violates the fail-closed guarantee.
        if self.egress_pool is not None:
            lane = self.egress_pool.get_lane(account.account_id)
            if lane is not None and not lane.proxy.public_ip:
                if not await self.egress_pool.probe_endpoint(lane.proxy):
                    self.last_error = (
                        "Proxy de sortie indisponible : %s. "
                        "Aucun navigateur n'a ete ouvert pour proteger l'IP reelle."
                    ) % lane.proxy.url
                    return None
        credentials = None
        if not interactive:
            credentials = await self._resolve_credentials(account.credentials_ref)
            if not credentials:
                self.last_error = (
                    "Credentials absentes ou invalides pour %s. "
                    "Utilisez la connexion interactive du dashboard."
                ) % account.account_id
                return None
        identity = None
        if self.identity_manager is not None:
            lane = self.egress_pool.get_lane(account.account_id) if self.egress_pool else None
            identity = self.identity_manager.get(
                account.account_id, lane.tls_profile if lane else "chrome120")
        profile_root = self.sessions_dir.parent / "browser-profiles" / account.account_id
        bypasser = self._interactive_browsers.pop(account.account_id, None) if interactive else None
        if bypasser is None:
            bypasser = ChallengeBypasser(
                proxy=proxy,
                identity=identity,
                headless=not interactive,
                user_data_dir=str(profile_root),
            )
        try:
            result = await bypasser.harvest_session(
                login_url=account.login_url,
                success_selector=account.success_selector or "",
                credentials=credentials,
                interactive=interactive,
            )
        finally:
            # Interactive failures keep Chrome open so Cloudflare/2FA can be
            # completed and retried. Successful sessions and headless runs are
            # closed normally.
            if not interactive or ("result" in locals() and result.success):
                await bypasser.close()
            elif "result" in locals() and not result.success:
                self._interactive_browsers[account.account_id] = bypasser
        if not result.success:
            self.last_error = result.error or "La page de connexion n'a pas ete validee."
            return None
        if not result.cookies:
            self.last_error = (
                "Connexion non confirmee : aucun cookie n'a ete capture. "
                "Le navigateur a ete ferme et aucune session n'a ete stockee."
            )
            return None
        session = Session(
            session_id=account.account_id + "_" + str(int(time.time())),
            account_id=account.account_id,
            provider=account.provider,
            cookies=result.cookies,
            user_agent=result.user_agent,
        )
        self.sessions[session.session_id] = session
        self.account_sessions.setdefault(account.account_id, []).append(session.session_id)
        await self._persist_session(session)
        self.last_error = ""
        return session

    def _lane_proxy(self, account_id):
        """Returns the account lane proxy URL, or the default proxy.
        Creates the lane if absent (1:1 persistent binding)."""
        if self.egress_pool is None:
            return self.default_proxy
        lane = self.egress_pool.bind(
            account_id,
            require_browser=True,
            provider=self.accounts.get(account_id).provider if account_id in self.accounts else None,
        )
        if lane is None:
            return self.default_proxy
        return lane.proxy.url

    async def burn_lane(self, account_id, reason="403/429"):
        """Burn lane egress of account on 403/429 (session cookies intact).

        Browser identity runs WITH IP: change IP while keeping the
        same fingerprint, it's an account that "jumps machine" -> detection.
        """
        if self.egress_pool is None:
            return None
        result = await self.egress_pool.burn_lane(account_id, reason)
        if self.identity_manager is not None:
            lane = self.egress_pool.get_lane(account_id)
            tls_profile = lane.tls_profile if lane else "chrome120"
            self.identity_manager.rotate(account_id, reason=reason, tls_profile=tls_profile)
        return result

    def get_user_agents(self):
        """{account_id: user_agent} accounts with a harvested session.
        Used to align the HTTP fingerprint (curl_cffi) with that of the browser."""
        out = {}
        for s in self.sessions.values():
            if s.user_agent:
                out[s.account_id] = s.user_agent
        return out

    def _session_for(self, account_id):
        """Most recent session of an account (cookies + UA harvests)."""
        best = None
        for s in self.sessions.values():
            if s.account_id != account_id:
                continue
            if best is None or s.last_used > best.last_used:
                best = s
        return best

    def get_provider_contexts(self) -> List[Dict[str, Any]]:
        """Routing context by account: everything that identifies the request.

        The 4 elements come from the SAME account, otherwise it "changes machine":
          - Exit IP: lane egress of the account. Absent -> proxy="" -> the
            provider is DISCOUNTED (fail-closed, the real IP never comes out).
          - TLS profile: account identity profile (same family as the
            browser that harvested the session).
          - User-Agent: UA collected by the browser, otherwise that of the identity.
          - cookies      : jar recolte + credentials resolus.
        """
        out: List[Dict[str, Any]] = []
        ordered = sorted(self.accounts.items(), key=lambda kv: -getattr(kv[1], "priority", 0))
        for account_id, acc in ordered:
            lane = self.egress_pool.get_lane(account_id) if self.egress_pool else None
            proxy = ""
            lane_tls = "chrome120"
            if lane is not None:
                proxy = getattr(lane.proxy, "url", "") or ""
                lane_tls = getattr(lane, "tls_profile", "chrome120") or "chrome120"

            identity = None
            if self.identity_manager is not None:
                identity = self.identity_manager.get(account_id, lane_tls)
            tls_profile = (identity.tls_profile if identity is not None else lane_tls) or lane_tls

            session = self._session_for(account_id)
            user_agent = (session.user_agent if session is not None else "") or \
                         (identity.user_agent if identity is not None else "")

            creds = self.resolve_credentials(acc.credentials_ref) or {}
            if session is not None and session.cookies:
                merged = dict(session.cookies)
                merged.update(creds)
                creds = merged

            healthy = True if session is None else session.is_healthy()

            out.append({
                "account_id": account_id,
                "provider": acc.provider,
                "proxy": proxy,
                "tls_profile": tls_profile,
                "user_agent": user_agent,
                "locale": (identity.locale if identity is not None else "") or "",
                "creds": creds,
                "lane_id": getattr(lane, "lane_id", "") or "",
                "has_session": session is not None,
                "healthy": healthy,
            })
        return out

    async def rotate_to_next_account(self, account_id):
        """Switch to another account with the same provider (rate limit / 429).

        The session of the overloaded account is put into cooldown, then the next
        provider account is chosen. Returns the target account_id or None.
        """
        acc = self.accounts.get(account_id)
        if acc is None:
            return None
        for sid in self.account_sessions.get(account_id, []):
            session = self.sessions.get(sid)
            if session is not None:
                session.mark_rate_limited(reset_in_seconds=acc.cooldown_seconds)
                await self._persist_session(session)
        siblings = [a for a in self.accounts.values()
                    if a.provider == acc.provider and a.account_id != account_id]
        if not siblings:
            return None
        siblings.sort(key=lambda a: -a.priority)
        return siblings[0].account_id

    async def _resolve_credentials(self, ref):
        """Resolves a credentials reference. Format: env:VAR | file:path"""
        return self.resolve_credentials(ref)

    def resolve_credentials(self, ref) -> Dict[str, str]:
        """Synchronous version of the resolution (read env/file).

        The secret never leaves the machine: it is read here and placed in the
        routing context, never logged or returned by the API.
        """
        if not ref:
            return {}
        if ref.startswith("env:"):
            val = os.getenv(ref[4:], "")
            if val:
                try:
                    return json.loads(val)
                except json.JSONDecodeError:
                    return None
        elif ref.startswith("file:"):
            path = Path(ref[5:])
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    return None
        return None

    async def _persist_session(self, session):
        payload = asdict(session)
        payload["state"] = session.state.value
        path = self.sessions_dir / (session.session_id + ".json")
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    async def release_session(self, session_id, success=True):
        async with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return
            if success:
                session.mark_success()
            else:
                session.mark_error()
            await self._persist_session(session)

    async def report_rate_limit(self, session_id, reset_in_seconds=3600):
        async with self._lock:
            session = self.sessions.get(session_id)
            if session:
                session.mark_rate_limited(reset_in_seconds)
                await self._persist_session(session)

    async def report_challenge(self, session_id):
        async with self._lock:
            session = self.sessions.get(session_id)
            if session:
                session.mark_challenge()
                await self._persist_session(session)

    async def rotate_account(self, current_session_id):
        current = self.sessions.get(current_session_id)
        if not current:
            return None
        current.state = SessionState.ERROR
        await self._persist_session(current)
        return await self.get_session(current.provider)

    def get_stats(self):
        return {
            "total_accounts": len(self.accounts),
            "total_sessions": len(self.sessions),
            "by_state": {st.value: sum(1 for s in self.sessions.values() if s.state == st) for st in SessionState},
            "by_provider": {
                p: sum(1 for s in self.sessions.values() if s.provider == p)
                for p in set(s.provider for s in self.sessions.values())
            },
        }
