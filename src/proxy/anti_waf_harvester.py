"""
Module: anti_waf_harvester.py
Role: Complete hybrid anti-WAF architecture
- Phase 1: Playwright with the installed Chrome browser to handle interactive
  login/challenge pages and extract cookies
- Phase 2: curl_cffi with full TLS JA3/JA4 spoofing (Chrome/Firefox/Safari profiles)
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
# TLS SPOOFING (since tls_spoof.py) — JA3/JA4 complets
# ============================================================

cffi_requests = None
BrowserType = None
_JA3_PROFILES = None
_curl_cffi_available = False
_import_error: Optional[str] = None


def _ensure_curl_cffi():
    """Attempts to import curl_cffi. If failure, activates stub mode (aiohttp)."""
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


# Headers per profile (also used in stub mode)
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
    """HTTP session with real browser TLS fingerprint (JA3/JA4).
    In stub mode (curl_cffi unavailable): aiohttp with same headers, without real fingerprint.
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
# CHALLENGE BYPASS - Playwright + installed Chrome
# ============================================================

ANTI_DETECT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
const _toDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function() {
    const ctx = this.getContext('2d');
    if (ctx) { ctx.fillStyle = 'rgba(0,0,0,0.001)'; ctx.fillRect(0, 0, 1, 1); }
    return _toDataURL.apply(this, arguments);
};
"""


@dataclass
class ChallengeResult:
    success: bool
    cookies: Dict[str, str]
    user_agent: str
    error: Optional[str] = None
    challenge_type: Optional[str] = None


class ChallengeBypasser:
    """Playwright browser helper for login and WAF challenge pages.
    - Masque navigator.webdriver
    - Bruit Canvas / WebRTC
    - Gere Turnstile (Cloudflare), Datadome, reCAPTCHA
    - Returns valid cookies for reuse in pure HTTP (curl_cffi)
    """

    def __init__(self, proxy=None, headless: bool = True, timeout: int = 30000, user_data_dir=None,
                 identity=None):
        self.proxy = proxy
        self.headless = headless
        self.timeout = timeout
        self.user_data_dir = user_data_dir
        self._identity = identity   # IdentityProfile: UA, locale, timezone, ecran, canvas
        self._pw = None  # Playwright instance for cleanup
        self._browser = None
        self._context = None
        self._active_page = None

    def _identity_script(self) -> str:
        """Anti-detection script PARAMETER by account identity.
        Otherwise, all accounts share the same browser fingerprint."""
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
        """Converts a proxy string to a Playwright proxy dict."""
        if not self.proxy:
            return None
        if isinstance(self.proxy, dict):
            return self.proxy
        # Format: socks5://user:pass@host:port or http://host:port
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
            from playwright.async_api import async_playwright
            proxy_dict = self._build_proxy_dict()

            # Use installed Chrome with a persistent profile.
            # Cloudflare passes real Chrome with real history easily.
            # Persistent context stores cookies/history between sessions = looks human.
            import os
            profile_dir = self.user_data_dir or os.path.join(
                os.environ.get("VIAROMA_HOME", os.getcwd()), "data", "chrome-profile"
            )
            os.makedirs(profile_dir, exist_ok=True)

            launch_kwargs = dict(
                channel="chrome",  # Real installed Chrome, not Chromium
                headless=self.headless,
                user_data_dir=profile_dir,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            if proxy_dict:
                launch_kwargs["proxy"] = proxy_dict

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch_persistent_context(**launch_kwargs)
            # launch_persistent_context returns a BrowserContext directly
            # (not a Browser) — use it as self._context
            self._context = self._browser
            await self._context.add_init_script(
                self._identity_script() if self._identity is not None else ANTI_DETECT_SCRIPT
            )
        return self._browser

    async def bypass(self, url: str, wait_selector: str, wait_timeout: int = 15000) -> ChallengeResult:
        """Launch the browser, wait for the challenge, return cookies + UA."""
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
            logger.exception("challenge_bypass_failed url=%s error=%s", url, str(e))
            return ChallengeResult(success=False, cookies={}, user_agent="", error=str(e))

    async def solve_challenge(self, url, wait_selector=None, wait_for_network_idle=True, custom_script=None):
        """Complete API to solve a WAF challenge."""
        try:
            await self._get_browser()
            # launch_persistent_context returns a BrowserContext; it has no
            # new_context() method. Reuse it so cookies and identity stay aligned.
            context = self._context
            page = await context.new_page()
            response = await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)

            if response and response.status >= 400:
                await page.close()
                return ChallengeResult(success=False, cookies={}, user_agent="", error="HTTP " + str(response.status), challenge_type="http_error")

            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=15000)
                except Exception:
                    detected = await self._detect_challenge(page)
                    if detected:
                        await page.close()
                        return ChallengeResult(success=False, cookies={}, user_agent="", error="Challenge detecte: " + detected, challenge_type=detected)

            if wait_for_network_idle:
                await page.wait_for_load_state("networkidle", timeout=10000)
            if custom_script:
                await page.evaluate(custom_script)

            cookies = await context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            ua = await page.evaluate("navigator.userAgent")
            await page.close()
            return ChallengeResult(success=True, cookies=cookie_dict, user_agent=ua)
        except Exception as e:
            logger.exception("solve_challenge_failed url=%s error=%s", url, str(e))
            return ChallengeResult(success=False, cookies={}, user_agent="", error=str(e), challenge_type="exception")

    async def _detect_challenge(self, page):
        """Detects what type of WAF challenge is present."""
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

    async def harvest_session(self, login_url, success_selector="", credentials=None, interactive=True):
        """Navigate to login_url, harvest cookies after login.

        Interactive mode (default): browser visible, user logs in manually.
        Auto-fill mode: credentials dict filled into standard login form fields.
        Success detection: success_selector if provided, else URL change or
        provider-specific post-login elements (never generic textarea to avoid
        matching h-captcha-response fields).
        """
        try:
            # _get_browser() creates self._context with account identity + anti-detect.
            # Using self._context (not a new context) ensures harvested cookies match
            # the account fingerprint (UA, locale, timezone, screen, canvas noise).
            await self._get_browser()
            page = self._active_page if self._active_page and not self._active_page.is_closed() else await self._context.new_page()
            self._active_page = page
            if page.url and page.url != "about:blank":
                await page.reload(wait_until="domcontentloaded", timeout=self.timeout)
            else:
                await page.goto(login_url, wait_until="domcontentloaded", timeout=self.timeout)

            # Detect and wait for Cloudflare challenge before proceeding.
            # In interactive mode, the user clicks the checkbox; we just wait.
            await self._wait_for_cloudflare(page, timeout_ms=180000 if interactive else 30000)

            if interactive:
                # User logs in manually (Google OAuth, 2FA, captcha, etc.)
                await self._wait_for_login_success(page, login_url, success_selector)
            elif credentials:
                # Auto-fill mode for simple login forms (API key providers)
                await self._auto_fill_login(page, credentials, login_url, success_selector)
            else:
                # No credentials, no interactive: just wait for challenge to pass
                await page.wait_for_load_state("networkidle", timeout=15000)

            await page.wait_for_load_state("networkidle", timeout=15000)
            cookies = await self._context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            ua = await page.evaluate("navigator.userAgent")
            await page.close()
            self._active_page = None
            return ChallengeResult(success=True, cookies=cookie_dict, user_agent=ua)
        except Exception as e:
            logger.exception("harvest_session_failed url=%s error=%s", login_url, str(e))
            # Keep the visible page/browser alive for an interactive retry.
            # The caller may retry Cloudflare/2FA without reopening everything.
            return ChallengeResult(success=False, cookies={}, user_agent="", error=str(e))

    async def _wait_for_cloudflare(self, page, timeout_ms=180000):
        """Detect Cloudflare/Turnstile challenge interstitial and wait for it to clear.

        In interactive mode (default 180s), the user clicks the checkbox manually.
        In headless mode, simple challenges may still require an interactive run.
        Does nothing if no challenge is present.
        """
        cf_selectors = [
            "iframe[src*='challenges.cloudflare.com']",
            "#cf-challenge-running",
            "#cf-please-wait",
            "#cf-spinner-please-wait",
            "div[id='challenge-form']",
        ]
        try:
            # Quick check: is there a challenge right now?
            found = False
            for sel in cf_selectors:
                try:
                    el = await page.wait_for_selector(sel, timeout=3000)
                    if el:
                        found = True
                        break
                except Exception:
                    continue

            if not found:
                return  # No challenge, proceed normally

            logger.info("cloudflare_challenge_detected url=%s", page.url)
            initial_url = page.url

            # Wait for the challenge to clear — either user clicks it (interactive)
            # Headless mode may still require an interactive run. Poll for the challenge
            # iframe to disappear.
            import asyncio
            deadline = asyncio.get_event_loop().time() + (timeout_ms / 1000)
            while asyncio.get_event_loop().time() < deadline:
                try:
                    # Turnstile's iframe can remain mounted after success. A
                    # cf_clearance cookie or a navigation is therefore a more
                    # reliable success signal than iframe disappearance alone.
                    cookies = await self._context.cookies()
                    if any(c.get("name") == "cf_clearance" for c in cookies):
                        logger.info("cloudflare_cookie_obtained url=%s", page.url)
                        return
                    if page.url != initial_url:
                        logger.info("cloudflare_redirect_cleared url=%s", page.url)
                        return

                    still_there = False
                    for sel in cf_selectors:
                        if await page.query_selector(sel):
                            still_there = True
                            break
                    if not still_there:
                        # Challenge cleared — wait for page to settle
                        await page.wait_for_load_state("networkidle", timeout=10000)
                        logger.info("cloudflare_challenge_cleared url=%s", page.url)
                        return
                except Exception:
                    pass
                await asyncio.sleep(1)

            raise TimeoutError(
                "Cloudflare challenge non resolu apres %ss; aucun cookie cf_clearance obtenu"
                % int(timeout_ms / 1000)
            )
        except TimeoutError:
            raise
        except Exception as e:
            logger.debug("cloudflare_check_skip error=%s", str(e))

    async def _wait_for_login_success(self, page, login_url, success_selector="", timeout_ms=120000):
        """Wait for login to complete. Uses success_selector if provided,
        otherwise auto-detects via URL change or generic post-login elements."""
        if success_selector:
            await page.wait_for_selector(success_selector, timeout=timeout_ms)
            return

        # Provider-specific post-login selectors (NOT generic textarea which
        # matches <textarea name="h-captcha-response"> — false success detection).
        generic_selectors = [
            "img[alt*='avatar']", "img[alt*='profile']",
            "[data-testid*='user-menu']", "[data-testid*='account']",
            "button[aria-label*='menu']", "button[aria-label*='account']",
            "div[aria-label='Write']",
            "div[contenteditable='true'][data-testid='composer-textarea']",
            "#prompt-textarea",
            "textarea#prompt-textarea",
            "[data-testid='conversation-turn']",
            ".ql-editor",
            "div[contenteditable='true'][data-placeholder*='Message']",
            ".chat-input",
        ]

        await page.wait_for_function(
            """(args) => {
                const loginUrl = args[0];
                const sels = args[1];
                // URL changed away from login page = login succeeded
                try {
                    const u = new URL(window.location.href);
                    const login = new URL(loginUrl);
                    if (u.origin + u.pathname !== login.origin + login.pathname) return true;
                } catch (e) {}
                // Generic post-login element detected
                for (const s of sels) {
                    if (document.querySelector(s)) return true;
                }
                return false;
            }""",
            arg=[login_url, generic_selectors],
            timeout=timeout_ms,
        )

    async def _auto_fill_login(self, page, credentials, login_url, success_selector=""):
        """Auto-fill login form with credentials dict {username, password}.
        Uses standard input selectors instead of treating dict keys as CSS selectors."""
        username = credentials.get("username", credentials.get("email", ""))
        password = credentials.get("password", "")

        if username:
            for sel in [
                'input[type="email"]', 'input[name="email"]',
                'input[name="username"]', 'input[id*="email"]', 'input[id*="user"]',
            ]:
                el = await page.query_selector(sel)
                if el:
                    await el.fill(username)
                    break

        if password:
            for sel in ['input[type="password"]', 'input[name="password"]', 'input[id*="password"]']:
                el = await page.query_selector(sel)
                if el:
                    await el.fill(password)
                    break

        # Click the first available submit button
        for sel in [
            'button[type="submit"]', 'input[type="submit"]',
            'button:has-text("Sign in")', 'button:has-text("Log in")', 'button:has-text("Continue")',
        ]:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                break

        if success_selector:
            await page.wait_for_selector(success_selector, timeout=30000)
        else:
            await self._wait_for_login_success(page, login_url, "", timeout_ms=30000)

    async def close(self):
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._browser = None
        self._context = None
        self._active_page = None
        self._pw = None


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
    - Phase 1: Playwright + installed Chrome to handle login/challenge pages
    - Phase 2: curl_cffi with TLS JA3/JA4 spoofing for pure HTTP streaming (optimized RAM)
    - X-Maximum-Latency / X-Request-Timing headers for realistic timing
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
        """Phase 1: Ephemeral extraction of session cookies via stealth browser."""
        result = await self.bypasser.bypass(login_url, success_selector, self.config.challenge_timeout)
        if result.success:
            self.session_cookies = result.cookies
            self.session_user_agent = result.user_agent
            self._token_validated = True
            logger.info("session_harvested", cookies_count=len(self.session_cookies))
            return True
        logger.error("session_harvest_failed error=%s", result.error)
        self._token_validated = False
        return False

    def _build_headers(self, extra=None):
        """Builds full headers with cookies, UA and WAF timing headers."""
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
        """Phase 2: Pure HTTP streaming with aligned TLS fingerprint.
        Args:
            request: ChatCompletionRequest
            endpoint: provider URL
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
                        raise PermissionError("Token invalid by WAF (403/401). Re-harvesting required.")
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
                        raise PermissionError("Token invalid by WAF (403/401). Re-harvesting required.")
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
            logger.exception("stream_chat_failed error=%s", str(e))
            raise

    async def close(self):
        await self.spinner.close()
        await self.bypasser.close()
