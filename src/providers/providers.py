"""
Module: src/providers/providers.py
Role: Web chat provider registry + adapter delegation.
Each provider delegates streaming to proxy_engine.ADAPTER_REGISTRY (real curl_cffi implementations).

IDENTITY: a provider carries the COMPLETE identity of an account --
  Exit IP (lane egress) + TLS profile (JA3/JA4) + User-Agent/locale + cookie jar.
  These 4 elements come from the SAME source (the account routing context) to
  that the account does not appear to "change machines" from one request to another.

FAIL-CLOSED: An account without an exit proxy is EXCLUDED from the cascade. The real IP of
the machine must NEVER go to a provider.
"""
from __future__ import annotations
import logging
from typing import AsyncGenerator, Dict, List, Tuple
from src.schemas import ChatCompletionRequest, ChatChunk
from src.proxy.proxy_engine import ADAPTER_REGISTRY, PROVIDER_META, NON_COOKIE_FIELDS, get_adapter

logger = logging.getLogger(__name__)

WEB_CHAT_REGISTRY = [
    {
        "name": meta["label"],
        "class_name": cls_name.replace("Adapter", ""),
        "login_url": meta["login_url"],
        "needs_credentials": meta["credentials"],
        "provider_key": cls_name,
    }
    for cls_name, meta in PROVIDER_META.items()
]


def parse_cookie_string(raw: str) -> Dict[str, str]:
    """'sessionKey=abc; __session=xyz' -> {'sessionKey': 'abc', '__session': 'xyz'}.

    The "cookie" credential field contains a STRING of cookies, not a cookie
    unique: sending it as is would produce the invalid header "cookie=sessionKey=...".
    """
    out: Dict[str, str] = {}
    if not raw:
        return out
    for part in str(raw).split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out


def split_credentials(creds: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Returns (cookie jar, all credentials).

    The "cookie" field is broken and put into the jar. Tokens (access_token,
    token, api_key, auth_token) and meta (org_id, device_id) are NOT
    cookies: they come out of the Cookie header and go into the Authorization header
    or the endpoint URL.
    """
    creds = dict(creds or {})
    jar = parse_cookie_string(creds.get("cookie", ""))
    for k, v in creds.items():
        if k in NON_COOKIE_FIELDS or v in (None, ""):
            continue
        jar[k] = v
    return jar, creds


class BaseProvider:
    """Wraps a proxy_engine adapter with health scoring.

    Fingerprint consistency: proxy, TLS profile, User-Agent and locale
    are those of the account. Send a request from an IP other than that of the
    browser (or with another TLS profile) is exactly what does
    ban an account.
    """

    def __init__(self, provider_key: str, session_id: str, credentials: dict = None,
                 cookie_jar: dict = None, proxy: str = None, user_agent: str = "",
                 tls_profile: str = "chrome120", locale: str = "", account_id: str = None):
        self.provider_key = provider_key
        self.session_id = session_id
        self.account_id = account_id or session_id
        self.name = PROVIDER_META.get(provider_key, {}).get("label", provider_key)
        self.score = 100
        self._credentials = credentials or {}
        self._cookie_jar = cookie_jar if cookie_jar is not None else split_credentials(self._credentials)[0]
        self._proxy = proxy
        self._user_agent = user_agent
        self._tls_profile = tls_profile or "chrome120"
        self._locale = locale
        self._adapter = None

    async def stream_chat(self, request: ChatCompletionRequest) -> AsyncGenerator[ChatChunk, None]:
        self._adapter = get_adapter(
            provider=self.provider_key,
            session_id=self.session_id,
            cookies=self._cookie_jar,
            creds=self._credentials,
            user_agent=self._user_agent,
            proxy=self._proxy,
            tls_profile=self._tls_profile,
            locale=self._locale,
        )
        try:
            async for chunk in self._adapter.stream_chat(request):
                self.register_success()
                yield chunk
        except (PermissionError, ResourceWarning):
            self.register_failure()
            raise
        except Exception:
            self.register_failure()
            raise

    def register_failure(self):
        self.score = max(0, self.score - 20)

    def register_success(self):
        self.score = min(100, self.score + 5)

    async def close(self):
        if self._adapter:
            await self._adapter.close()

    def describe(self) -> Dict[str, object]:
        """Routing state of the provider (no secret)."""
        return {
            "provider_key": self.provider_key,
            "label": self.name,
            "account_id": self.account_id,
            "tls_profile": self._tls_profile,
            "user_agent": self._user_agent,
            "locale": self._locale,
            "egress": bool(self._proxy),
            "cookie_count": len(self._cookie_jar),
            "score": self.score,
        }


def build_providers(contexts: List[Dict[str, object]]) -> Tuple[List[BaseProvider], List[Dict[str, str]]]:
    """Constructs providers from routing contexts.

    FAIL-CLOSED: an account without an exit proxy is EXCLUDED. We will NEVER go out
    on the real IP of the machine. The account is marked as excluded so that
    the dashboard can display it.

    Returns (providers, discarded).
    """
    providers: List[BaseProvider] = []
    skipped: List[Dict[str, str]] = []
    for ctx in contexts or []:
        account_id = str(ctx.get("account_id", "") or "")
        provider_key = str(ctx.get("provider", "") or "")
        proxy = str(ctx.get("proxy", "") or "")
        if not provider_key:
            continue
        if provider_key not in ADAPTER_REGISTRY:
            skipped.append({"account_id": account_id, "provider": provider_key,
                            "reason": "provider unknown to registry"})
            continue
        is_official_api = PROVIDER_META.get(provider_key, {}).get("transport") == "api"
        if not proxy and not is_official_api:
            skipped.append({
                "account_id": account_id, "provider": provider_key,
                "reason": "no exit proxy (fail-closed: the real IP should never exit)",
            })
            continue
        if not ctx.get("healthy", True):
            skipped.append({
                "account_id": account_id, "provider": provider_key,
                "reason": "cooldown session (rate limit) - account set aside",
            })
            continue
        creds = dict(ctx.get("creds") or {})
        jar, full = split_credentials(creds)
        providers.append(BaseProvider(
            provider_key=provider_key,
            session_id=account_id,
            account_id=account_id,
            credentials=full,
            cookie_jar=jar,
            proxy=proxy,
            user_agent=str(ctx.get("user_agent", "") or ""),
            tls_profile=str(ctx.get("tls_profile", "") or "chrome120"),
            locale=str(ctx.get("locale", "") or ""),
        ))
    return providers, skipped


def get_active_providers(user_agents: Dict[str, str] = None,
                         contexts: List[Dict[str, object]] = None) -> List[BaseProvider]:
    """Return active providers from config. Credentials resolved by SessionManager.

    - `contexts` provided (production path): routing contexts are binding
      (lane IP, TLS profile, UA, harvest cookies) and fail-closed applies.
    - otherwise (YAML only): historical derivation since accounts.yaml.

    user_agents: {account_id: user_agent} — HTTP fingerprint must be the same
    than that of the browser which collected the session, otherwise the account is
    reported as having changed machine.
    """
    if contexts is not None:
        providers, skipped = build_providers(contexts)
        for s in skipped:
            logger.warning("provider ecarte: %s (%s) - %s", s.get("account_id"),
                           s.get("provider"), s.get("reason"))
        return providers

    from src.config_loader import load_config
    user_agents = user_agents or {}
    try:
        config = load_config()
        accounts = config.get("accounts", [])
    except Exception:
        accounts = []

    providers = []
    for acct in accounts:
        provider_key = acct.get("provider", "")
        if provider_key not in ADAPTER_REGISTRY:
            continue
        credentials = {}
        for field in PROVIDER_META.get(provider_key, {}).get("credentials", []):
            credentials[field] = acct.get(field, "")
        account_id = acct.get("account_id", "unknown")
        jar, full = split_credentials(credentials)
        providers.append(BaseProvider(
            provider_key=provider_key,
            session_id=account_id,
            account_id=account_id,
            credentials=full,
            cookie_jar=jar,
            proxy=acct.get("proxy"),
            user_agent=user_agents.get(account_id, ""),
            tls_profile=acct.get("tls_profile", "chrome120"),
            locale=acct.get("locale", ""),
        ))
    return providers


def get_registry():
    return WEB_CHAT_REGISTRY
