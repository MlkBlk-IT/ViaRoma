"""
Module: src/providers/providers.py
Role: Web chat provider registry + adapter delegation.
Each provider delegates streaming to proxy_engine.ADAPTER_REGISTRY (real curl_cffi implementations).

IDENTITE: un provider porte l'identite COMPLETE d'un compte --
  IP de sortie (lane egress) + profil TLS (JA3/JA4) + User-Agent/locale + jar de cookies.
  Ces 4 elements viennent de la MEME source (le contexte de routage du compte) pour
  que le compte ne paraisse pas "changer de machine" d'une requete a l'autre.

FAIL-CLOSED: un compte sans proxy de sortie est EXCLU de la cascade. L'IP reelle de
la machine ne doit JAMAIS partir vers un provider.
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

    Le champ de credential "cookie" contient une CHAINE de cookies, pas un cookie
    unique: l'envoyer tel quel produirait l'en-tete invalide "cookie=sessionKey=...".
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
    """Retourne (jar de cookies, tous les credentials).

    Le champ "cookie" est casse et verse dans le jar. Les jetons (access_token,
    token, api_key, auth_token) et les meta (org_id, device_id) ne sont PAS des
    cookies: ils sortent de l'en-tete Cookie et vont dans le header Authorization
    ou l'URL de l'endpoint.
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

    Cohérence d'empreinte: le proxy, le profil TLS, l'User-Agent et la locale
    sont ceux du compte. Envoyer une requete depuis une autre IP que celle du
    navigateur (ou avec un autre profil TLS) est exactement ce qui fait
    bannir un compte.
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
        """Etat de routage du provider (aucun secret)."""
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
    """Construit les providers depuis les contextes de routage.

    FAIL-CLOSED: un compte sans proxy de sortie est EXCLU. On ne sortira JAMAIS
    sur l'IP reelle de la machine. Le compte est signale comme ecarte pour que
    le dashboard puisse l'afficher.

    Retourne (providers, ecartees).
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
                            "reason": "provider inconnu du registre"})
            continue
        if not proxy:
            skipped.append({
                "account_id": account_id, "provider": provider_key,
                "reason": "aucun proxy de sortie (fail-closed: l'IP reelle ne doit jamais sortir)",
            })
            continue
        if not ctx.get("healthy", True):
            skipped.append({
                "account_id": account_id, "provider": provider_key,
                "reason": "session en cooldown (rate limit) - compte mis de cote",
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

    - `contexts` fourni (chemin de production): les contextes de routage font foi
      (IP de la lane, profil TLS, UA, cookies recoltes) et le fail-closed s'applique.
    - sinon (YAML seul): derivation historique depuis accounts.yaml.

    user_agents: {account_id: user_agent} — l'empreinte HTTP doit etre la meme
    que celle du navigateur qui a recolte la session, sinon le compte se
    signale comme ayant change de machine.
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
