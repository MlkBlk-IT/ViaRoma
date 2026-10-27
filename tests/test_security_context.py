"""Test isole de la securite de routage et de la coherence d'identite.

Prouve 4 choses:
  1) FAIL-CLOSED: un compte sans proxy de sortie n'est JAMAIS execute ->
     l'IP reelle de la machine ne part pas. Le compte est signale ecarte.
  2) COHERENCE TLS: le profil TLS de l'identite du compte arrive jusqu'a la
     couche HTTP (JA3/JA4), pas un "chrome120" par defaut.
  3) COOKIES: le champ "cookie" (une CHAINE de cookies) est casse en jar, et
     l'en-tete Cookie est bien forme. Les jetons ne partent JAMAIS en cookie.
  4) CREDENTIALS: les credentials que PROVIDER_META exige (auth_token Gemini,
     device_id ChatGPT) sont reellement envoyes.

Aucun acces reseau. Aucun fichier de production modifie.

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
    print("== 1) FAIL-CLOSED: pas de proxy de sortie -> aucun provider ==")
    ctxs = [
        {"account_id": "sans-egress", "provider": "claude_web", "proxy": "",
         "tls_profile": "chrome120", "user_agent": "UA/1", "locale": "fr-CA", "creds": {}},
        {"account_id": "avec-egress", "provider": "claude_web", "proxy": "http://1.2.3.4:8080",
         "tls_profile": "firefox133", "user_agent": "UA/1", "locale": "fr-CA", "creds": {}},
    ]
    providers, skipped = build_providers(ctxs)
    check("un seul provider construit", len(providers) == 1, "n={}".format(len(providers)))
    check("le compte sans egress est ecarte", len(skipped) == 1, "skipped={}".format(skipped))
    check("le bon compte ecarte", bool(skipped) and skipped[0]["account_id"] == "sans-egress")
    check("le provider garde son egress",
          bool(providers) and providers[0]._proxy == "http://1.2.3.4:8080")
    check("aucun provider sans proxy",
          all(p._proxy for p in providers), "proxy vide = fuite d'IP reelle")

    print("== 1b) compte en cooldown (rate limit) -> ecarte ==")
    ctx2 = [{"account_id": "cooldown", "provider": "gemini_web", "proxy": "http://1.2.3.4:8080",
             "tls_profile": "chrome120", "user_agent": "UA", "locale": "", "creds": {},
             "healthy": False}]
    p2, s2 = build_providers(ctx2)
    check("aucun provider", len(p2) == 0, "n={}".format(len(p2)))
    check("compte signale", len(s2) == 1 and "cooldown" in s2[0]["reason"].lower(),
          "reason={}".format(s2[0]["reason"] if s2 else None))

    print("== 2) COHERENCE TLS: le profil du compte va jusqu'a la couche HTTP ==")
    prov = providers[0]
    check("profil porte par le provider", prov._tls_profile == "firefox133", prov._tls_profile)
    ad = get_adapter("claude_web", "acct", cookies={}, creds={},
                     user_agent=prov._user_agent, proxy=prov._proxy,
                     tls_profile=prov._tls_profile, locale=prov._locale)
    check("profil recu par l'adaptateur", ad.tls_profile == "firefox133", ad.tls_profile)
    check("spoofer JA3 sur le bon profil", ad._spoofer.profile_name == "firefox133",
          ad._spoofer.profile_name)
    check("user-agent aligne", ad.user_agent == "UA/1", ad.user_agent)
    check("locale aligne", ad.locale == "fr-CA", ad.locale)

    print("== 3) COOKIES: chaine cassee en jar, en-tete bien forme ==")
    jar = parse_cookie_string("sessionKey=abc123; __session=xyz")
    check("jar de 2 cookies", len(jar) == 2, str(jar))
    check("valeur sessionKey", jar.get("sessionKey") == "abc123", str(jar))
    jar2, full = split_credentials({"cookie": "sessionKey=abc; __session=xyz", "org_id": "org-7"})
    check("cookie -> jar", jar2.get("sessionKey") == "abc", str(jar2))
    check("org_id reste hors du jar", "org_id" not in jar2, str(jar2))
    check("org_id reste dans creds", full.get("org_id") == "org-7", str(full))

    ad2 = get_adapter("claude_web", "acct", cookies=jar2, creds=full, tls_profile="chrome120")
    headers = ad2._build_headers(ad2._extra_headers())
    cookie_hdr = headers.get("Cookie", "")
    check("en-tete Cookie present", bool(cookie_hdr), cookie_hdr)
    check("pas de 'cookie=' imbrique", "cookie=" not in cookie_hdr, cookie_hdr)
    check("sessionKey en clair dans le jar", "sessionKey=abc" in cookie_hdr, cookie_hdr)
    check("org_id absent du Cookie", "org_id" not in cookie_hdr, cookie_hdr)
    check("URL avec le bon org_id",
          "/api/organizations/org-7/chat_conversations" in ad2.chat_path, ad2.chat_path)

    print("== 3b) les jetons ne partent JAMAIS dans l'en-tete Cookie ==")
    jar3, full3 = split_credentials({"cookie": "a=1", "access_token": "SECRET-AT",
                                     "token": "SECRET-TOK", "api_key": "SECRET-KEY"})
    ad3 = get_adapter("chatgpt_web", "acct", cookies=jar3, creds=full3)
    h3 = ad3._build_headers(ad3._extra_headers())
    check("access_token absent du Cookie", "SECRET-AT" not in h3.get("Cookie", ""), h3.get("Cookie", ""))
    check("token absent du Cookie", "SECRET-TOK" not in h3.get("Cookie", ""), h3.get("Cookie", ""))
    check("api_key absent du Cookie", "SECRET-KEY" not in h3.get("Cookie", ""), h3.get("Cookie", ""))
    check("NON_COOKIE_FIELDS couvre les jetons",
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

    print("== 5) Accept-Language suit la locale du compte ==")
    adl = get_adapter("claude_web", "acct", cookies={}, creds={}, locale="fr-CA")
    check("Accept-Language fr-CA", adl._build_headers().get("Accept-Language", "").startswith("fr-CA"),
          adl._build_headers().get("Accept-Language", ""))

    print("== 6) aucune valeur de secret dans la description de routage ==")
    d = prov.describe()
    blob = " ".join(str(v) for v in d.values())
    check("pas de cookie dans describe()", "sessionKey" not in blob and "abc" not in blob, blob)
    check("pas de token dans describe()", "SECRET" not in blob, blob)
    check("describe() annonce l'egress", d.get("egress") is True, str(d.get("egress")))
    check("describe() donne le nombre de cookies", d.get("cookie_count") == 0, str(d.get("cookie_count")))

    print("== 7) le YAML seul ne fabrique pas de proxy (pas de fuite) ==")
    legacy = get_active_providers()
    check("aucun proxy invente", all(not p._proxy for p in legacy),
          "un provider YAML sans proxy ne doit pas partir en direct")

    print("== 8) CREDENTIALS: jamais dans un fichier versionne ==")
    import json as _json
    import tempfile as _tempfile
    from pathlib import Path as _Path
    from src.dashboard import config_io as _cio

    # a) le fichier de comptes NE DOIT PAS contenir de secret en clair
    accounts_file = _cio.CONFIG_DIR / "accounts.yaml"
    if accounts_file.exists():
        raw = accounts_file.read_text(encoding="utf-8")
        leak_keys = [k for k in ("password:", "username:", "cookie:", "api_key:",
                                 "access_token:", "auth_token:", "token:") if k in raw]
        check("accounts.yaml sans secret en clair", not leak_keys, "trouve={}".format(leak_keys))
    else:
        print("  (config/accounts.yaml absent: verification ignoree)")

    # b) le stockage passe par data/creds/ (gitignore) + credentials_ref
    with _tempfile.TemporaryDirectory() as tmp:
        old_root = _cio.ROOT
        old_creds = _cio.CREDS_DIR
        _cio.ROOT = _Path(_tempfile.mkdtemp(prefix="viaroma-creds-"))
        _cio.CREDS_DIR = _cio.ROOT / "data" / "creds"
        try:
            ref = _cio.store_credentials("compte-test", {"username": "u", "password": "p-secret"})
            check("la ref pointe vers data/creds/", ref.startswith("file:data/creds/"), ref)
            written = (_cio.ROOT / "data" / "creds" / "compte-test.json")
            check("le fichier de credentials existe", written.exists(), str(written))
            payload = _json.loads(written.read_text(encoding="utf-8"))
            check("les valeurs sont dans le fichier", payload.get("password") == "p-secret",
                  "cles={}".format(sorted(payload.keys())))
            acc = {"account_id": "x", "username": "u", "password": "p-secret",
                   "credentials_ref": ref}
            changed = _cio.strip_inline_credentials(acc)
            check("le secret est retire du compte YAML", changed and "password" not in acc
                  and "username" not in acc, str(acc))
            check("la ref reste dans le compte YAML", acc.get("credentials_ref") == ref)
        finally:
            _cio.ROOT = old_root
            _cio.CREDS_DIR = old_creds

    # c) le dossier des credentials est bien hors du suivi git
    import subprocess as _sp
    try:
        out = _sp.run(["git", "check-ignore", "data/creds/x.json"],
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       capture_output=True, text=True, timeout=20)
        check("data/creds/ est ignore par git", "data/creds" in out.stdout, out.stdout.strip())
    except Exception as e:
        check("data/creds/ est ignore par git", False, str(e))

    print("")
    if check.failures:
        print("ECHEC: {} verification(s)".format(check.failures))
        return 1
    print("OK: securite de routage et coherence d'identite verifiees")
    return 0


if __name__ == "__main__":
    sys.exit(main())
