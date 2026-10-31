"""Isolated testing of routing security and identity consistency.

Prouve 4 choses:
  1) FAIL-CLOSED: an account without an exit proxy is NEVER executed ->
     the real IP of the machine does not leave. The account is reported as sidelined.
  2) TLS CONSISTENCY: the TLS profile of the account identity reaches the
     HTTP layer (JA3/JA4), not a "chrome120" by default.
  3) COOKIES: the "cookie" field (a STRING of cookies) is jar case, and
     the Cookie header is well shaped. The tokens NEVER go into cookies.
  4) CREDENTIALS: the credentials that PROVIDER_META requires (auth_token Gemini,
     device_id ChatGPT) are actually sent.

No network access. No production files edit.

Run:  .venv/Scripts/python.exe tests/test_security_context.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.providers.providers import (
    build_providers, parse_cookie_string, split_credentials, get_active_providers,
)
from src.proxy.proxy_engine import get_adapter, NON_COOKIE_FIELDS


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("  [{}] {}{}".format(status, label, (" :: " + detail) if detail else ""))
    if not condition:
        check.failures += 1


check.failures = 0


def main():
    print("== 1) FAIL-CLOSED: no egress proxy -> no provider ==")
    ctxs = [
        {"account_id": "sans-egress", "provider": "claude_web", "proxy": "",
         "tls_profile": "chrome120", "user_agent": "UA/1", "locale": "fr-CA", "creds": {}},
        {"account_id": "avec-egress", "provider": "claude_web", "proxy": "http://1.2.3.4:8080",
         "tls_profile": "firefox133", "user_agent": "UA/1", "locale": "fr-CA", "creds": {}},
    ]
    providers, skipped = build_providers(ctxs)
    check("a single provider built", len(providers) == 1, "n={}".format(len(providers)))
    check("the account without egress is discarded", len(skipped) == 1, "skipped={}".format(skipped))
    check("the right account is discarded", bool(skipped) and skipped[0]["account_id"] == "sans-egress")
    check("the provider keeps its egress",
          bool(providers) and providers[0]._proxy == "http://1.2.3.4:8080")
    check("no provider without proxy",
          all(p._proxy for p in providers), "proxy vide = fuite d'Real IP")

    print("== 1b) account in cooldown (rate limit) -> skipped ==")
    ctx2 = [{"account_id": "cooldown", "provider": "gemini_web", "proxy": "http://1.2.3.4:8080",
             "tls_profile": "chrome120", "user_agent": "UA", "locale": "", "creds": {},
             "healthy": False}]
    p2, s2 = build_providers(ctx2)
    check("aucun provider", len(p2) == 0, "n={}".format(len(p2)))
    check("account reported", len(s2) == 1 and "cooldown" in s2[0]["reason"].lower(),
          "reason={}".format(s2[0]["reason"] if s2 else None))

    print("== 2) TLS CONSISTENCY: the account profile goes up to the HTTP layer ==")
    prov = providers[0]
    check("profile carried by the provider", prov._tls_profile == "firefox133", prov._tls_profile)
    ad = get_adapter("claude_web", "acct", cookies={}, creds={},
                     user_agent=prov._user_agent, proxy=prov._proxy,
                     tls_profile=prov._tls_profile, locale=prov._locale)
    check("profil recu par l'adaptateur", ad.tls_profile == "firefox133", ad.tls_profile)
    check("spoofer JA3 on the right profile", ad._spoofer.profile_name == "firefox133",
          ad._spoofer.profile_name)
    check("user-agent aligne", ad.user_agent == "UA/1", ad.user_agent)
    check("locale aligne", ad.locale == "fr-CA", ad.locale)

    print("== 3) COOKIES: broken string in jar, well-formed header ==")
    jar = parse_cookie_string("sessionKey=abc123; __session=xyz")
    check("jar of 2 cookies", len(jar) == 2, str(jar))
    check("sessionKey value", jar.get("sessionKey") == "abc123", str(jar))
    jar2, full = split_credentials({"cookie": "sessionKey=abc; __session=xyz", "org_id": "org-7"})
    check("cookie -> jar", jar2.get("sessionKey") == "abc", str(jar2))
    check("org_id stays out of the jar", "org_id" not in jar2, str(jar2))
    check("org_id remains in creds", full.get("org_id") == "org-7", str(full))

    ad2 = get_adapter("claude_web", "acct", cookies=jar2, creds=full, tls_profile="chrome120")
    headers = ad2._build_headers(ad2._extra_headers())
    cookie_hdr = headers.get("Cookie", "")
    check("en-tete Cookie present", bool(cookie_hdr), cookie_hdr)
    check("no nested 'cookie='", "cookie=" not in cookie_hdr, cookie_hdr)
    check("sessionKey in plain text in the jar", "sessionKey=abc" in cookie_hdr, cookie_hdr)
    check("org_id missing from Cookie", "org_id" not in cookie_hdr, cookie_hdr)
    check("URL with the correct org_id",
          "/api/organizations/org-7/chat_conversations" in ad2.chat_path, ad2.chat_path)

    print("== 3b) tokens NEVER go into the Cookie header ==")
    jar3, full3 = split_credentials({"cookie": "a=1", "access_token": "SECRET-AT",
                                     "token": "SECRET-TOK", "api_key": "SECRET-KEY"})
    ad3 = get_adapter("chatgpt_web", "acct", cookies=jar3, creds=full3)
    h3 = ad3._build_headers(ad3._extra_headers())
    check("access_token missing from Cookie", "SECRET-AT" not in h3.get("Cookie", ""), h3.get("Cookie", ""))
    check("token missing from Cookie", "SECRET-TOK" not in h3.get("Cookie", ""), h3.get("Cookie", ""))
    check("api_key missing from Cookie", "SECRET-KEY" not in h3.get("Cookie", ""), h3.get("Cookie", ""))
    check("NON_COOKIE_FIELDS covers tokens",
          {"access_token", "token", "api_key", "auth_token", "cookie"} <= NON_COOKIE_FIELDS)

    print("== 4) CREDENTIALS reellement envoyes (gemini / chatgpt) ==")
    adg = get_adapter("gemini_web", "acct", cookies={}, creds={"auth_token": "GTOK"})
    hg = adg._build_headers(adg._extra_headers())
    check("gemini: Authorization Bearer", hg.get("Authorization") == "Bearer GTOK", str(hg.get("Authorization")))
    adc = get_adapter("chatgpt_web", "acct", cookies={},
                      creds={"access_token": "CAT", "device_id": "DEV-1"})
    hc = adc._build_headers(adc._extra_headers())
    check("chatgpt: Authorization Bearer", hc.get("Authorization") == "Bearer CAT", str(hc.get("Authorization")))
    check("chatgpt: oai-device-id envoye", hc.get("oai-device-id") == "DEV-1", str(hc.get("oai-device-id")))

    print("== 5) Accept-Language follows account locale ==")
    adl = get_adapter("claude_web", "acct", cookies={}, creds={}, locale="fr-CA")
    check("Accept-Language fr-CA", adl._build_headers().get("Accept-Language", "").startswith("fr-CA"),
          adl._build_headers().get("Accept-Language", ""))

    print("== 6) no secret value in routing description ==")
    d = prov.describe()
    blob = " ".join(str(v) for v in d.values())
    check("no cookie in describe()", "sessionKey" not in blob and "abc" not in blob, blob)
    check("no token in describe()", "SECRET" not in blob, blob)
    check("describe() annonce l'egress", d.get("egress") is True, str(d.get("egress")))
    check("describe() gives the number of cookies", d.get("cookie_count") == 0, str(d.get("cookie_count")))

    print("== 7) YAML alone does not create a proxy (no leak) ==")
    legacy = get_active_providers()
    check("aucun proxy invente", all(not p._proxy for p in legacy),
          "a YAML provider without a proxy must not go live")

    print("== 8) CREDENTIALS: never in a versioned file ==")
    import json as _json
    import tempfile as _tempfile
    from pathlib import Path as _Path
    from src.dashboard import config_io as _cio

    # a) the accounts file MUST NOT contain any plaintext secrets
    accounts_file = _cio.CONFIG_DIR / "accounts.yaml"
    if accounts_file.exists():
        raw = accounts_file.read_text(encoding="utf-8")
        leak_keys = [k for k in ("password:", "username:", "cookie:", "api_key:",
                                 "access_token:", "auth_token:", "token:") if k in raw]
        check("accounts.yaml without secret in plain text", not leak_keys, "trouve={}".format(leak_keys))
    else:
        print("  (config/accounts.yaml missing: verification ignored)")

    # b) storage goes through data/creds/ (gitignore) + credentials_ref
    with _tempfile.TemporaryDirectory() as tmp:
        old_root = _cio.ROOT
        old_creds = _cio.CREDS_DIR
        _cio.ROOT = _Path(_tempfile.mkdtemp(prefix="viaroma-creds-"))
        _cio.CREDS_DIR = _cio.ROOT / "data" / "creds"
        try:
            ref = _cio.store_credentials("account-test", {"username": "u", "password": "p-secret"})
            check("the ref points to data/creds/", ref.startswith("file:data/creds/"), ref)
            written = (_cio.ROOT / "data" / "creds" / "account-test.json")
            check("the credentials file exists", written.exists(), str(written))
            payload = _json.loads(written.read_text(encoding="utf-8"))
            check("the values ​​are in the file", payload.get("password") == "p-secret",
                  "cles={}".format(sorted(payload.keys())))
            acc = {"account_id": "x", "username": "u", "password": "p-secret",
                   "credentials_ref": ref}
            changed = _cio.strip_inline_credentials(acc)
            check("the secret is removed from the YAML account", changed and "password" not in acc
                  and "username" not in acc, str(acc))
            check("the ref remains in the YAML account", acc.get("credentials_ref") == ref)
        finally:
            _cio.ROOT = old_root
            _cio.CREDS_DIR = old_creds

    # c) the credentials folder is well out of git tracking
    import subprocess as _sp
    try:
        out = _sp.run(["git", "check-ignore", "data/creds/x.json"],
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       capture_output=True, text=True, timeout=20)
        check("data/creds/ is ignored by git", "data/creds" in out.stdout, out.stdout.strip())
    except Exception as e:
        check("data/creds/ is ignored by git", False, str(e))

    print("")
    if check.failures:
        print("FAILED: {} check(s)".format(check.failures))
        return 1
    print("OK: routing security and identity consistency verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
