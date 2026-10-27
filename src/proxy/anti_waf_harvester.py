"""
Module: anti_waf_harvester.py
Rôle: Architecture hybride anti-WAF complète
- Phase 1: Camoufox headless pour franchir Turnstile/Cloudflare et extraire cookies
- Phase 2: curl_cffi avec spoofing TLS JA3/JA4 complet (profils Chrome/Firefox/Safari)
- Fallback aiohttp si curl_cffi indisponible (Python 3.14+)
- Bruit Canvas/WebRTC, masquage navigator.webdriver
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import AsyncGenerator, Optional, Dict, Any, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ============================================================
# TLS SPOOFING (depuis tls_spoof.py) — JA3/JA4 complets
# ============================================================

cffi_requests = None
BrowserType = None
_JA3_PROFILES = None
_curl_cffi_available = False
_import_error: Optional[str] = None


def _ensure_curl_cffi():
    """Tente d'importer curl_cffi. Si échec, active le mode stub (aiohttp)."""
    global cffi_requests, BrowserType, _JA3_PROFILES, _curl_cffi_available, _import_error
    if cffi_requests is not None:
        return
    try:
        from curl_cffi import requests as _cffi
        from curl_cffi.requests import BrowserType as _BT
    except ImportError as e:
        _import_error = str(e)
        logger.warning("tls_spoof_stub_active", reason="curl_cffi indisponible", detail=str(e))
        _curl_cffi_available = False
        return
    cffi_requests = _cffi
    BrowserType = _BT
    _curl_cffi_available = True
    _JA3_PROFILES = {
        "chrome120": {
            "browser": _BT.chrome120,
            "ja3": "771,4865-4867-4866-49195-49199-52393-52392-49196-49200-49162-49161-49171-49172-156-157-47-53,0-23-65281-10-11-35-16-5-13-18-51-45-43-27-21,29-23-24-25,0",
            "akamai_fp": "chrome_120_windows",
        },
        "chrome119": {
            "browser": _BT.chrome119,
            "ja3": "771,4865-4867-4866-49195-49199-52393-52392-49196-49200-49162-49161-49171-49172-156-157-47-53,0-23-65281-10-11-35-16-5-13-18-51-45-43-27-21,29-23-24-25,0",
            "akamai_fp": "chrome_119_windows",
        },
        "firefox133": {
            "browser": _BT.firefox133,
            "ja3": "771,4865-4867-4866-49195-49199-52393-52392-49196-49200-49162-49161-49171-49172-156-157-47-53,0-23-65281-10-11-35-16-5-13-18-51-45-43-27-21,29-23-24-25,0",
            "akamai_fp": "firefox_133_windows",
        },
        "safari17": {
            "browser": _BT.safari17_0,
            "ja3": "771,4865-4867-4866-49195-49199-52393-52392-49196-49200-49162-49161-49171-49172-156-157-47-53,0-23-65281-10-11-35-16-5-13-18-51-45-43-27-21,29-23-24-25,0",
            "akamai_fp": "safari_17_macos",
        },
    }


def get_ja3_profiles():
    _ensure_curl_cffi()
    return _JA3_PROFILES or {}


def is_stub_mode() -> bool:
    _ensure_curl_cffi()
    return not _curl_cffi_available


def get_import_error() -> Optional[str]:
    return _import_error


# Headers par profil (utilises aussi en mode stub)
DEFAULT_HEADERS = {
    "chrome120": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "sec-ch-ua-mobile": "?0",
        'sec-ch-ua-platform': '\"Windows\"',
    },
    "chrome119": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="119", "Google Chrome";v="119"',
        "sec-ch-ua-mobile": "?0",
        'sec-ch-ua-platform': '\"Windows\"',
    },
    "firefox133": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    },
    "safari17": {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    },
}


class TLSSpoofer:
    """Session HTTP avec fingerprint TLS de vrai navigateur (JA3/JA4).
    En mode stub (curl_cffi indisponible): aiohttp avec memes headers, sans fingerprint reel.
    """

    def __init__(self, profile: str = "chrome120", proxy: Optional[str] = None):
        _ensure_curl_cffi()
        profiles = get_ja3_profiles()
        if profile not in profiles and not is_stub_mode():
            raise ValueError(f"Profil inconnu: {profile}. Dispo: {list(profiles.keys())}")
        self.profile_name = profile
        self.profile = profiles.get(profile, {})
        self.proxy = proxy
        self._session = None
        self.is_stub = is_stub_mode()

    def _get_default_headers(self) -> dict:
        return DEFAULT_HEADERS.get(self.profile_name, DEFAULT_HEADERS["chrome120"]).copy()

    def create_session(self):
        headers = self._get_default_headers()
        if self.is_stub:
            import aiohttp
            return aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
                connector=aiohttp.TCPConnector(limit=100),
            )
        session = cffi_requests.AsyncSession(
            impersonate=self.profile["browser"], proxy=self.proxy, timeout=30
        )
        session.headers.update(headers)
        return session

    def get_session(self):
        if self._session is None:
            self._session = self.create_session()
        return self._session

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None


def get_spoofer(profile: str = "chrome120", proxy: Optional[str] = None) -> TLSSpoofer:
    return TLSSpoofer(profile=profile, proxy=proxy)


# ============================================================
# CHALLENGE BYPASS (depuis bypass_challenge.py) - Camoufox patche
# ============================================================

ANTI_DETECT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'fr'] });
const _toDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function() {
    const ctx = this.getContext('2d');
    if (ctx) { ctx.fillStyle = 'rgba(0,0,0,0.001)'; ctx.fillRect(0, 0, 1, 1); }
    return _toDataURL.apply(this, arguments);
};
window.RTCPeerConnection = undefined;
"""


@dataclass
class ChallengeResult:
    success: bool
    cookies: Dict[str, str]
    user_agent: str
    error: Optional[str] = None
    challenge_type: Optional[str] = None


class ChallengeBypasser:
    """Navigateur headless patche (Camoufox) pour franchir les challenges WAF.
    - Masque navigator.webdriver
    - Bruit Canvas / WebRTC
    - Gere Turnstile (Cloudflare), Datadome, reCAPTCHA
    - Retourne cookies valides pour reutilisation en HTTP pur (curl_cffi)
    """

    def __init__(self, proxy=None, headless: bool = True, timeout: int = 30000, user_data_dir=None,
                 identity=None):
        self.proxy = proxy
        self.headless = headless
        self.timeout = timeout
        self.user_data_dir = user_data_dir
        self._identity = identity   # IdentityProfile: UA, locale, timezone, ecran, canvas
        self._camoufox = None  # Instance AsyncCamoufox pour cleanup __aexit__
        self._browser = None
        self._context = None

    def _identity_script(self) -> str:
        """Script anti-detection PARAMETRE par l'identite du compte.
        Sans ca, tous les comptes partagent la meme empreinte navigateur."""
        fp = self._identity
        langs = ", ".join("'%s'" % lang for lang in [fp.locale, "en", "fr"])
        noise = ("%f" % fp.noise).rstrip("0")
        return (
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });\n"
            "window.chrome = { runtime: {} };\n"
            "Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });\n"
            "Object.defineProperty(navigator, 'languages', { get: () => [%s] });\n"
            "Object.defineProperty(navigator, 'platform', { get: () => '%s' });\n"
            "Object.defineProperty(navigator, 'deviceMemory', { get: () => %d });\n"
            "Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => %d });\n"
            "const _g = HTMLCanvasElement.prototype.toDataURL;\n"
            "HTMLCanvasElement.prototype.toDataURL = function() {\n"
            "  const c = document.createElement('canvas');\n"
            "  const x = c.getContext('2d');\n"
            "  if (x) { x.fillStyle = 'rgba(0,0,0,%s)'; x.fillRect(0, 0, 1, 1); }\n"
            "  return _g.apply(this, arguments);\n"
            "};\n"
            "window.RTCPeerConnection = undefined;\n"
        ) % (langs, fp.platform, fp.device_memory, fp.hardware_concurrency, noise)

    def _build_proxy_dict(self):
        """Convertit une string proxy en dict Camoufox/Playwright."""
        if not self.proxy:
            return None
        if isinstance(self.proxy, dict):
            return self.proxy
        # Format: socks5://user:pass@host:port ou http://host:port
        from urllib.parse import urlparse
        p = urlparse(self.proxy)
        proxy_dict = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
        if p.username:
            proxy_dict["username"] = p.username
        if p.password:
            proxy_dict["password"] = p.password
        return proxy_dict

    async def _get_browser(self):
        if self._browser is None:
            try:
                from camoufox.async_api import AsyncCamoufox
            except ImportError:
                raise RuntimeError(
                    "Camoufox non installe. Installez: pip install camoufox && camoufox fetch"
                )
            # Camoufox est base sur Firefox: pas d'args Chromium, pas de user_data_dir sans persistent_context
            proxy_dict = self._build_proxy_dict()
            launch_kwargs = dict(
                headless=self.headless,
                humanize=True,  # Mouvements de souris humains
                geoip=True if proxy_dict else None,  # Geolocation spoofs via proxy
            )
            if proxy_dict:
                launch_kwargs["proxy"] = proxy_dict
            self._camoufox = AsyncCamoufox(**launch_kwargs)
            self._browser = await self._camoufox.__aenter__()
            # AsyncCamoufox(persistent_context=False) retourne un Browser -> new_context valide
            # Le contexte porte l'identite du compte (UA, locale, fuseau, ecran).
            # Sans ca, tous les comptes se ressemblent -> detection immediate.
            if self._identity is not None:
                ctx_kwargs = self._identity.context_kwargs()
            else:
                ctx_kwargs = {
                    "viewport": {"width": 1920, "height": 1080},
                    "locale": "en-US",
                    "timezone_id": "America/Montreal",
                }
            self._context = await self._browser.new_context(**ctx_kwargs)
            await self._context.add_init_script(ANTI_DETECT_SCRIPT)
            if self._identity is not None:
                await self._context.add_init_script(self._identity_script())
        return self._browser

    async def bypass(self, url: str, wait_selector: str, wait_timeout: int = 15000) -> ChallengeResult:
        """Lance le navigateur, attend le challenge, retourne cookies + UA."""
        try:
            await self._get_browser()
            page = await self._context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
            await page.wait_for_selector(wait_selector, timeout=wait_timeout)
            await page.wait_for_load_state("networkidle", timeout=10000)
            cookies = await self._context.cookies()
            ua = await page.evaluate("navigator.userAgent")
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            await page.close()
            return ChallengeResult(
                success=True,
                cookies=cookie_dict,
                user_agent=ua,
                challenge_type="turnstile" if "cloudflare" in url.lower() else "generic",
            )
        except Exception as e:
            logger.exception("challenge_bypass_failed", url=url, error=str(e))
            return ChallengeResult(success=False, cookies={}, user_agent="", error=str(e))

    async def solve_challenge(self, url, wait_selector=None, wait_for_network_idle=True, custom_script=None):
        """API complete pour resoudre un challenge WAF."""
        try:
            await self._get_browser()
            context = await self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="America/Montreal",
                permissions=["clipboard-read", "clipboard-write"],
            )
            page = await context.new_page()
            await page.add_init_script(ANTI_DETECT_SCRIPT)
            response = await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)

            if response and response.status >= 400:
                await page.close()
                await context.close()
                return ChallengeResult(success=False, cookies={}, user_agent="", error="HTTP " + str(response.status), challenge_type="http_error")

            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=15000)
                except Exception:
                    detected = await self._detect_challenge(page)
                    if detected:
                        await page.close()
                        await context.close()
                        return ChallengeResult(success=False, cookies={}, user_agent="", error="Challenge detecte: " + detected, challenge_type=detected)

            if wait_for_network_idle:
                await page.wait_for_load_state("networkidle", timeout=10000)
            if custom_script:
                await page.evaluate(custom_script)

            cookies = await context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            ua = await page.evaluate("navigator.userAgent")
            await page.close()
            await context.close()
            return ChallengeResult(success=True, cookies=cookie_dict, user_agent=ua)
        except Exception as e:
            logger.exception("solve_challenge_failed", url=url, error=str(e))
            return ChallengeResult(success=False, cookies={}, user_agent="", error=str(e), challenge_type="exception")

    async def _detect_challenge(self, page):
        """Detecte quel type de challenge WAF est present."""
        checks = [
            ("iframe[src*='challenges.cloudflare.com']", "turnstile"),
            ("iframe[src*='datadome']", "datadome"),
            ("div[id*='recaptcha']", "recaptcha"),
            ("script[src*='challenge']", "generic_challenge"),
            ("#cf-challenge-running", "cloudflare_challenge"),
        ]
        for selector, ctype in checks:
            if await page.query_selector(selector):
                return ctype
        return None

    async def harvest_session(self, login_url, success_selector, credentials=None):
        """Navigue -> remplit login si credentials -> attend success_selector -> cookies."""
        try:
            await self._get_browser()
            context = await self._browser.new_context(viewport={"width": 1920, "height": 1080})
            page = await context.new_page()
            await page.add_init_script(ANTI_DETECT_SCRIPT)
            await page.goto(login_url, wait_until="domcontentloaded", timeout=self.timeout)
            if credentials:
                for selector, value in credentials.items():
                    await page.fill(selector, value)
                await page.click('button[type="submit"], input[type="submit"]')
            await page.wait_for_selector(success_selector, timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=10000)
            cookies = await context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            ua = await page.evaluate("navigator.userAgent")
            await page.close()
            await context.close()
            return ChallengeResult(success=True, cookies=cookie_dict, user_agent=ua)
        except Exception as e:
            logger.exception("harvest_session_failed", url=login_url, error=str(e))
            return ChallengeResult(success=False, cookies={}, user_agent="", error=str(e))

    async def close(self):
        if self._camoufox:
            await self._camoufox.__aexit__(None, None, None)
            self._camoufox = None
            self._browser = None
            self._context = None


# ============================================================
# FRONTIER SCRAPER - Architecture hybride Phase 1 + Phase 2
# ============================================================

@dataclass
class FrontierScraperConfig:
    proxy: Optional[str] = "http://127.0.0.1:8080"
    tls_profile: str = "chrome120"
    challenge_timeout: int = 30000
    headless: bool = True
    user_data_dir: Optional[str] = None


class FrontierScraper:
    """Architecture hybride anti-WAF complete:
    - Phase 1: Camoufox headless pour franchir Turnstile/Cloudflare et extraire cookies
    - Phase 2: curl_cffi avec spoofing TLS JA3/JA4 pour streaming HTTP pur (RAM optimisee)
    - Headers X-Maximum-Latency / X-Request-Timing pour timing realiste
    """

    def __init__(self, config=None):
        self.config = config or FrontierScraperConfig()
        self.session_cookies = {}
        self.session_user_agent = ""
        self.spinner = get_spoofer(profile=self.config.tls_profile, proxy=self.config.proxy)
        self.bypasser = ChallengeBypasser(
            proxy=self.config.proxy,
            headless=self.config.headless,
            timeout=self.config.challenge_timeout,
            user_data_dir=self.config.user_data_dir,
        )
        self._token_validated = False

    async def harvest_session(self, login_url, success_selector):
        """Phase 1: Extraction ephemere des cookies de session via navigateur furtif."""
        result = await self.bypasser.bypass(login_url, success_selector, self.config.challenge_timeout)
        if result.success:
            self.session_cookies = result.cookies
            self.session_user_agent = result.user_agent
            self._token_validated = True
            logger.info("session_harvested", cookies_count=len(self.session_cookies))
            return True
        logger.error("session_harvest_failed", error=result.error)
        self._token_validated = False
        return False

    def _build_headers(self, extra=None):
        """Construit les headers complets avec cookies, UA et headers timing WAF."""
        headers = self.spinner._get_default_headers()
        if self.session_cookies:
            headers["Cookie"] = "; ".join(k + "=" + v for k, v in self.session_cookies.items())
        if self.session_user_agent:
            headers["User-Agent"] = self.session_user_agent
        headers["X-Maximum-Latency"] = "150"
        headers["X-Request-Timing"] = "true"
        if extra:
            headers.update(extra)
        return headers

    async def stream_chat(self, request, endpoint, payload_builder):
        """Phase 2: Streaming HTTP pur avec empreinte TLS alignee.
        Args:
            request: ChatCompletionRequest
            endpoint: URL du provider
            payload_builder: callable(request) -> dict
        Yields:
            dict: chunks SSE decodes
        """
        if not self._token_validated:
            raise RuntimeError("Session non initialisee. Appelez harvest_session() d'abord.")

        headers = self._build_headers({"Accept": "text/event-stream", "Content-Type": "application/json"})
        payload = payload_builder(request)
        session = self.spinner.get_session()

        try:
            if self.spinner.is_stub:
                async with session.post(endpoint, json=payload, headers=headers, proxy=self.config.proxy) as resp:
                    if resp.status in (401, 403):
                        self._token_validated = False
                        raise PermissionError("Token invalide par le WAF (403/401). Re-harvesting requis.")
                    if resp.status == 429:
                        raise ResourceWarning("Rate-limit atteint (429). Cascade requise.")
                    async for raw in resp.content:
                        line = raw.decode("utf-8", "ignore").strip()
                        if line.startswith("data:"):
                            data = line[5:].strip()
                            if data and data != "[DONE]":
                                try:
                                    yield json.loads(data)
                                except json.JSONDecodeError:
                                    continue
            else:
                async with session.stream("POST", endpoint, json=payload, headers=headers) as resp:
                    if resp.status_code in (401, 403):
                        self._token_validated = False
                        raise PermissionError("Token invalide par le WAF (403/401). Re-harvesting requis.")
                    if resp.status_code == 429:
                        raise ResourceWarning("Rate-limit atteint (429). Cascade requise.")
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            data = line[5:].strip()
                            if data and data != "[DONE]":
                                try:
                                    yield json.loads(data)
                                except json.JSONDecodeError:
                                    continue
        except (PermissionError, ResourceWarning):
            raise
        except Exception as e:
            logger.exception("stream_chat_failed", error=str(e))
            raise

    async def close(self):
        await self.spinner.close()
        await self.bypasser.close()
