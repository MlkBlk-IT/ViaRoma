
import asyncio
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import AsyncGenerator, Dict, List, Optional, Any, Callable

import logging
import os

import yaml
from fastapi import HTTPException
from src.config_loader import CONFIG_DIR
from src.providers.providers import get_active_providers, build_providers
from src.proxy.proxy_engine import PROVIDER_META
from src.schemas import ChatCompletionRequest, ChatChunk

logger = logging.getLogger(__name__)


# ============================================================
# CIRCUIT BREAKER (merged since controllers/circuit_breaker.py)
# ============================================================

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class ProviderMetrics:
    name: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_success_time: float = 0
    last_failure_time: float = 0
    avg_latency_ms: float = 0
    rate_limited_until: float = 0
    state: CircuitState = CircuitState.CLOSED

    @property
    def success_rate(self):
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests

    @property
    def is_available(self):
        if self.state == CircuitState.OPEN:
            return time.time() > self.rate_limited_until
        return True

    def record_success(self, latency_ms):
        self.total_requests += 1
        self.successful_requests += 1
        self.consecutive_failures = 0
        self.consecutive_successes += 1
        self.last_success_time = time.time()
        self.avg_latency_ms = 0.9 * self.avg_latency_ms + 0.1 * latency_ms
        if self.state == CircuitState.HALF_OPEN and self.consecutive_successes >= 3:
            self.state = CircuitState.CLOSED

    def record_failure(self, is_rate_limit=False, retry_after=60):
        self.total_requests += 1
        self.failed_requests += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_failure_time = time.time()
        if is_rate_limit:
            self.rate_limited_until = time.time() + retry_after
            self.state = CircuitState.OPEN
        elif self.consecutive_failures >= 5:
            self.state = CircuitState.OPEN
            self.rate_limited_until = time.time() + 300


class ProviderExecutionError(Exception):
    pass


class RateLimitError(ProviderExecutionError):
    def __init__(self, message, retry_after=60):
        super().__init__(message)
        self.retry_after = retry_after


class ChallengeError(ProviderExecutionError):
    pass


class PermissionError403(ProviderExecutionError):
    """403 WAF/permission -> lane egress burn signal."""
    pass


class AllProvidersFailedError(Exception):
    pass


def load_cascade_yaml(path: str = None) -> Dict[str, Any]:
    """Charge config/cascade.yaml. Tolerant: file missing/unreadable -> {}."""
    path = path or os.path.join(CONFIG_DIR, "cascade.yaml")
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("cascade.yaml illisible (%s): %s", path, e)
        return {}


@dataclass
class FallbackConfig:
    providers: List[str] = field(default_factory=list)
    provider_accounts: Dict[str, str] = field(default_factory=dict)  # provider -> account_id (lane egress)
    max_retries_per_provider: int = 2
    base_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 30
    backoff_multiplier: float = 2.0
    circuit_breaker_threshold: int = 5
    half_open_test_requests: int = 3


class CircuitBreaker:
    """Circuit Breaker by provider + fallback cascade."""

    def __init__(self, config=None, on_burn=None):
        self.config = config or FallbackConfig()
        self.metrics = {name: ProviderMetrics(name=name) for name in self.config.providers}
        self.on_burn = on_burn  # async callable(account_id, reason) sur 403/429
        self.active = None  # None = all known providers; otherwise whitelist
        self._lock = asyncio.Lock()

    async def burn_lane(self, account_id, reason):
        """Notifies the egress pool that a lane must be burned (403/429)."""
        if not self.on_burn or not account_id:
            return None
        try:
            result = self.on_burn(account_id, reason)
            if asyncio.iscoroutine(result):
                return await result
            return result
        except Exception:
            return None

    def _account_for(self, provider):
        return self.config.provider_accounts.get(provider)

    def ensure_provider(self, name):
        if name not in self.metrics:
            self.metrics[name] = ProviderMetrics(name=name)
        return self.metrics[name]

    def get_provider_health(self, provider):
        return self.metrics.get(provider)

    def set_active_providers(self, names):
        """Restricts the cascade to actually active providers (routing context).

        A provider without an exit IP is not "inactive by mistake": it is
        deliberately excluded, otherwise the request would go to the real IP.
        """
        self.active = list(names) if names is not None else None

    def _pool(self):
        if self.active is None:
            return self.metrics
        return {n: m for n, m in self.metrics.items() if n in self.active}

    def get_available_providers(self):
        available = [(n, m) for n, m in self._pool().items() if m.is_available]
        available.sort(key=lambda x: (x[1].state != CircuitState.CLOSED, -x[1].success_rate, x[1].avg_latency_ms))
        return [n for n, _ in available]

    async def execute_with_fallback(self, request, executor, on_provider_change=None):
        """executor(provider, request) -> AsyncGenerator[chunks]. Yield of the first successful provider."""
        providers = self.get_available_providers()
        if not providers:
            pool = self._pool()
            providers = sorted(pool.keys(), key=lambda n: (-pool[n].success_rate, pool[n].avg_latency_ms))[:3]
            for p in providers:
                self.metrics[p].state = CircuitState.HALF_OPEN

        last_error = None
        for provider in providers:
            metrics = self.metrics[provider]
            retries = 0
            backoff = self.config.base_backoff_seconds
            while retries <= self.config.max_retries_per_provider:
                try:
                    start = time.time()
                    chunk_count = 0
                    async for chunk in executor(provider, request):
                        yield chunk
                        chunk_count += 1
                    latency = (time.time() - start) * 1000
                    if chunk_count > 0:
                        metrics.record_success(latency)
                        return
                    raise ProviderExecutionError(provider + ": empty response")
                except RateLimitError as e:
                    last_error = e
                    metrics.record_failure(is_rate_limit=True, retry_after=e.retry_after)
                    # The burn is done by the executor, with the exact account_id
                    # of the account which has been rate-limited.
                    break
                except PermissionError403 as e:
                    last_error = e
                    metrics.record_failure()
                    # Same: burn done by the executor (exact account_id).
                    break
                except ChallengeError as e:
                    last_error = e
                    metrics.record_failure()
                    await self.burn_lane(self._account_for(provider), "challenge")
                    break
                except Exception as e:
                    last_error = e
                    metrics.record_failure()
                    retries += 1
                    if retries <= self.config.max_retries_per_provider:
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * self.config.backoff_multiplier, self.config.max_backoff_seconds)
                    continue
            if on_provider_change:
                nxt = [p for p in providers if p != provider]
                on_provider_change(provider, nxt[0] if nxt else "none")
        raise AllProvidersFailedError(
            "All the " + str(len(providers)) + " providers failed. Latest error: " + str(last_error)
        ) from last_error

    def force_reset(self, provider):
        if provider in self.metrics:
            self.metrics[provider].state = CircuitState.CLOSED
            self.metrics[provider].consecutive_failures = 0
            self.metrics[provider].rate_limited_until = 0

    def get_global_stats(self):
        return {
            provider: {
                "state": m.state.value,
                "success_rate": round(m.success_rate, 3),
                "total_requests": m.total_requests,
                "avg_latency_ms": round(m.avg_latency_ms, 1),
                "consecutive_failures": m.consecutive_failures,
                "rate_limited_until": m.rate_limited_until,
            }
            for provider, m in self.metrics.items()
        }


# ============================================================
# CASCADE MANAGER (Roma entry point, connected to CircuitBreaker)
# ============================================================

def _contexts_signature(contexts) -> tuple:
    """Compact signature of contexts: says if a refresh is necessary."""
    out = []
    for ctx in contexts or []:
        creds = ctx.get("creds") or {}
        out.append((
            str(ctx.get("account_id", "")), str(ctx.get("provider", "")),
            str(ctx.get("proxy", "")), str(ctx.get("tls_profile", "")),
            str(ctx.get("user_agent", ""))[:48], str(ctx.get("locale", "")),
            len(creds), bool(ctx.get("has_session", False)),
            bool(ctx.get("healthy", True)),
        ))
    return tuple(sorted(out))


class CascadeManager:
    """Historic entry point to Roma, backing onto the CircuitBreaker.
    Keeps the original signature: execute_with_fallback(request).

    Routing starts from the CONTEXT of each account: exit IP (lane egress),
    TLS profile, User-Agent/locale and cookies. These elements come from the same
    account, otherwise it appears to "change machines" from one request to another.

    FAIL-CLOSED: an account without an exit proxy is removed from the cascade.
    The real IP of the machine will never go to a provider.
    """

    def __init__(self, config=None, on_burn=None, load_yaml: bool = True,
                 context_provider=None, on_rotate=None):
        providers = get_active_providers()
        names = [p.name for p in providers]
        provided_accounts = dict((config.provider_accounts or {})) if config is not None else {}
        if config is None:
            config = FallbackConfig(providers=names)

        raw = load_cascade_yaml() if load_yaml else {}
        label_by_key = {k: PROVIDER_META.get(k, {}).get("label", k) for k in PROVIDER_META}

        # --- provider -> account_id (lane burn key) ---
        # 1) derives from accounts.yaml: each active provider carries its account_id.
        derived = {p.name: p.session_id for p in providers}
        # 2) cascade.yaml can explicitly override (key = provider_key or label).
        explicit = {}
        for k, v in (raw.get("provider_accounts") or {}).items():
            if v:
                explicit[label_by_key.get(k, k)] = v
        # 3) a config explicitly passed through the caller remains priority.
        config.provider_accounts = {**derived, **explicit, **provided_accounts}

        # --- circuit breaker parameters ---
        for fname in ("max_retries_per_provider", "base_backoff_seconds", "max_backoff_seconds",
                      "backoff_multiplier", "circuit_breaker_threshold", "half_open_test_requests"):
            if fname in raw:
                setattr(config, fname, raw[fname])

        # --- providers declared in cascade.yaml ---
        declared = raw.get("providers") or []
        if declared:
            allowed = {label_by_key.get(k, k) for k in declared}
            active = [n for n in names if n in allowed]
            if active:
                config.providers = active

        self.breaker = CircuitBreaker(config, on_burn=on_burn)
        self.context_provider = context_provider
        self.on_rotate = on_rotate
        # Without context_provider (history mode / tests), YAML providers
        # remain in place. With this, only valid contexts are executable.
        self._providers = {} if context_provider is not None else {p.name: p for p in providers}
        self._extra_accounts = {}   # label -> [additional accounts from the same provider]
        self._skipped = []          # skipped accounts (fail-closed / cooldown)
        self._ctx_sig = None

    # --- routing context ---

    def refresh(self, contexts=None, user_agents: Dict[str, str] = None):
        """Reloads active providers from routing contexts.

        Each context carries the complete identity of the account (IP, TLS, UA,
        cookies). Without context, we fall back on the derivation accounts.yaml.
        """
        if contexts is None and self.context_provider is not None:
            contexts = self.context_provider()
        if contexts is not None:
            providers, skipped = build_providers(contexts)
            self._skipped = skipped
            by_label = {}
            for p in providers:
                by_label.setdefault(p.name, []).append(p)
            self._providers = {label: lst[0] for label, lst in by_label.items()}
            self._extra_accounts = {label: lst[1:] for label, lst in by_label.items() if len(lst) > 1}
            for label in self._providers:
                self.breaker.ensure_provider(label)
            # The cascade only runs on providers that have an exit IP.
            self.breaker.set_active_providers(list(self._providers.keys()))
            self.breaker.config.providers = list(self._providers.keys())
            self._ctx_sig = _contexts_signature(contexts)
            return len(self._providers)
        providers = get_active_providers(user_agents)
        for p in providers:
            self.breaker.ensure_provider(p.name)
            self._providers[p.name] = p
        return len(self._providers)

    def _ensure_fresh(self):
        """Reloads contexts if routing has changed (account added, lane
        reburned, identity turned, account put on cooldown)."""
        if not self.context_provider:
            return
        try:
            contexts = self.context_provider()
        except Exception:
            return
        if _contexts_signature(contexts) != self._ctx_sig:
            self.refresh(contexts)

    async def _rotate_account(self, provider):
        """Switch to another account with the same provider (rate limit)."""
        if not self.on_rotate:
            return None
        try:
            result = self.on_rotate(getattr(provider, "account_id", "") or "")
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception:
            return None

    def get_skipped(self):
        """Accounts removed from the cascade (no exit IP, cooldown...)."""
        return list(self._skipped)

    async def execute_with_fallback(self, request):
        self._ensure_fresh()
        # ensure that all active providers are tracked
        for p in self._providers.values():
            self.breaker.ensure_provider(p.name)

        async def executor(name, req):
            provider = self._providers.get(name)
            candidates = []
            if provider is not None:
                candidates.append(provider)
            candidates.extend(self._extra_accounts.get(name, []))
            if not candidates:
                raise ProviderExecutionError("Provider inconnu: " + name)
            last_exc = None
            for candidate in candidates:
                account_id = getattr(candidate, "account_id", "") or getattr(candidate, "session_id", "")
                try:
                    async for chunk in candidate.stream_chat(req):
                        yield chunk
                    return
                except PermissionError as e:
                    # 401/403 goes up through the adapters -> lane burn
                    # of the account concerned (the burn carries the exact account_id).
                    await self.breaker.burn_lane(account_id, "403 permission")
                    raise PermissionError403(str(e)) from e
                except ResourceWarning as e:
                    # 429 -> rate limit: we burn the lane and switch to a
                    # another account from the same provider if one remains.
                    await self.breaker.burn_lane(account_id, "429 rate_limit")
                    await self._rotate_account(candidate)
                    last_exc = RateLimitError(str(e), retry_after=60)
                    continue
            raise last_exc or ProviderExecutionError(name + ": no usable account")

        try:
            async for chunk in self.breaker.execute_with_fallback(request, executor):
                # synchronize the historical score of the provider with the successful status
                yield chunk
        except AllProvidersFailedError as e:
            raise HTTPException(status_code=503, detail="All border endpoints have failed. Last log: " + str(e))

    def get_stats(self):
        """Statistics by provider. The list of rejected accounts lives in
        get_skipped(): it must not mix with providers."""
        return self.breaker.get_global_stats()
