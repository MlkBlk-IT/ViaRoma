"""Test du module identite (src/proxy/identity.py).

Verifie les 3 invariants:
  1. STABLE   — un compte garde la meme identite d'un appel a l'autre.
  2. DISTINCTE — deux comptes n'ont jamais la meme identite.
  3. COHERENT — l'empreinte navigateur est coherente avec le profil TLS
     (Chrome sur Windows ne melange pas UA macOS et ecran Windows).

Aucun acces reseau. Aucun credential.

Run:  .venv/Scripts/python.exe tests/test_identity.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.proxy.identity import IdentityManager, derive_profile, LOCALES, BROWSER_TEMPLATES

failures = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("  [{}] {}{}".format(status, label, (" :: " + detail) if detail else ""))
    if not condition:
        failures.append(label)


def main():
    tmp = tempfile.mkdtemp(prefix="viaroma-id-")
    mgr = IdentityManager(path=os.path.join(tmp, "identities.json"))

    print("== derive_profile deterministe ==")
    a = derive_profile("claude-perso", "chrome120", seed=12345)
    b = derive_profile("claude-perso", "chrome120", seed=12345)
    check("meme seed -> meme UA", a.user_agent == b.user_agent)
    check("meme seed -> meme identity_id", a.identity_id == b.identity_id)
    c = derive_profile("claude-perso", "chrome120", seed=999)
    check("seed different -> identite differente", a.identity_id != c.identity_id)

    print("== coherence UA / TLS / plateforme ==")
    for tls in BROWSER_TEMPLATES:
        p = derive_profile("acct-" + tls, tls, seed=7)
        check("UA de la famille " + tls, p.user_agent == BROWSER_TEMPLATES[tls]["user_agent"])
        check("plateforme de la famille " + tls, p.platform == BROWSER_TEMPLATES[tls]["platform"])
        check("viewport <= ecran (" + tls + ")", p.viewport_w <= p.screen_w,
              "{}x{} vs {}x{}".format(p.viewport_w, p.viewport_h, p.screen_w, p.screen_h))

    print("== locale / timezone coherents ==")
    for acc in ("a", "b", "c", "d", "e", "f", "g", "h"):
        p = derive_profile(acc, "chrome120", seed=abs(hash(acc)) % 100000)
        check("timezone valide pour " + acc, p.timezone in LOCALES.get(p.locale, []),
              "{} / {}".format(p.locale, p.timezone))

    print("== stabilite (invariant 1) ==")
    first = mgr.get("claude-perso")
    second = mgr.get("claude-perso")
    check("get() est stable", first.identity_id == second.identity_id)
    check("get() ne recree pas", first.seed == second.seed)

    print("== distinction (invariant 2) ==")
    mgr.get("gemini-perso")
    ids = {p.identity_id for p in mgr.all()}
    check("2 comptes -> 2 identites", len(ids) == 2, "ids={}".format(len(ids)))
    check("pas de collision", not mgr.collisions(), "collisions={}".format(mgr.collisions()))
    check("UA distincts par defaut", mgr.distinct_ua_count() >= 1,
          "ua={}".format(mgr.distinct_ua_count()))
    check("empreintes navigateur distinctes", mgr.distinct_fingerprint_count() == 2,
          "fp={}".format(mgr.distinct_fingerprint_count()))
    check("fingerprint_hash = 16 chars",
          all(len(p.fingerprint_hash) == 16 for p in mgr.all()))

    print("== rotation ==")
    rotated = mgr.rotate("claude-perso", reason="403", tls_profile="firefox133")
    check("nouvelle identity_id", rotated.identity_id != first.identity_id)
    check("profil TLS change", rotated.tls_profile == "firefox133")
    check("compteur rotation", rotated.rotation == 1)
    check("raison memorisee", rotated.last_reason == "403")
    check("UA de la nouvelle famille", rotated.user_agent == BROWSER_TEMPLATES["firefox133"]["user_agent"])
    check("rotation n'affecte pas l'autre compte",
          mgr.get("gemini-perso").rotation == 0)

    print("== sortie exploitable (headers + contexte navigateur) ==")
    p = mgr.get("claude-perso")
    h = p.headers()
    check("header User-Agent", h.get("User-Agent") == p.user_agent)
    check("header Accept-Language", p.locale in h.get("Accept-Language", ""))
    ctx = p.context_kwargs()
    check("viewport navigateur", ctx["viewport"] == {"width": p.viewport_w, "height": p.viewport_h})
    check("locale navigateur", ctx["locale"] == p.locale)
    check("fuseau navigateur", ctx["timezone_id"] == p.timezone)
    check("UA navigateur", ctx["user_agent"] == p.user_agent)

    print("== persistance ==")
    mgr.save()
    mgr2 = IdentityManager(path=os.path.join(tmp, "identities.json"))
    check("identites rechargees", len(mgr2.all()) == len(mgr.all()),
          "{} vs {}".format(len(mgr2.all()), len(mgr.all())))
    check("seed conserve", mgr2.get("claude-perso").seed == p.seed)
    check("salt conserve", mgr2.salt == mgr.salt)

    print("")
    if failures:
        print("ECHEC: {} verification(s): {}".format(len(failures), ", ".join(failures)))
        return 1
    print("OK: module identite operationnel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
