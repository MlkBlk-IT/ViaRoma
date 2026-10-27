# PROGRESS — ViaRoma

> **Statut : ALPHA — pas de release — développement actif.**
> État vérifié en exécutant, pas déduit de l'intention. Rien n'est caché ici.

---

## 🟢 Ce qui est vérifié (par exécution)

| Domaine | Preuve | Où |
|---|---|---|
| **Fail-closed** | Aucun provider n'est appelé sans proxy de sortie. 5 niveaux de preuve automatisés : structure, transport curl_cffi, transport aiohttp, cible ≠ proxy, IP locale absente du dépôt / des lanes / des logs. | `tests/test_ip_leak.py` |
| **Cascade** | 403/429 → burn de lane, le compte survit, backoff exponentiel, circuit breaker ouvert/fermé. | `tests/test_burn_chain.py` |
| **Identités** | Une empreinte navigateur stable et distincte par compte, propagée jusqu'à la couche TLS. | `tests/test_identity.py` |
| **Serveur MCP** | 5 outils exposés, stdout réservé au protocole JSON-RPC, aucune valeur de credential dans les réponses. | `tests/test_mcp_server.py` |
| **Routage** | TLS, cookies, credentials par provider, en-têtes corrects, fail-closed. | `tests/test_security_context.py` |
| **Credentials** | Jamais dans un fichier versionné : `data/creds/` (gitignoré) + `credentials_ref: env:VAR \| file:chemin`. Scanner de secrets + hook pre-commit + contrôle CI. | `scripts/scan_secrets.mjs` |
| **Empaquetage** | Paquet npm et wheel PyPI construits et contrôlés (assets 3D inclus) à chaque commit. | `scripts/verify_wheel.py`, CI |
| **Catalogue** | 2 094 entrées, fenêtres de contexte **réelles** ou « non publiées par la source », provenance tracée (`ctx_source`), 21 dépôts GGUF avec vrais fichiers, origines par pays. | `src/hunter/hunter.py` |
| **Dashboard** | 16 onglets, chaque action déclenche une vraie requête API. Un clic muet est un bug, pas un design. | `src/dashboard/static/` |

**5 suites · 142 vérifications · CI verte à chaque commit.**

---

## 🔴 Ce qui n'est PAS démontré

- **Une complétion réelle.** Un seul adapter (`claude_web`) a été validé contre son front. Les 14 autres
  ont une `chat_path`, un `sse_kind` et un payload corrects, mais **n'ont jamais répondu** : n'en tirez
  aucune conclusion.
- **Le contournement anti-WAF n'a jamais tourné** contre un vrai site (Camoufox non exercé).
- **Aucun credential n'est fourni.** Sans `data/creds/<compte>.json`, `chat` renvoie un 503 propre — c'est
  voulu : le secret ne touche jamais le dépôt.
- **Fronts web uniquement.** `PROVIDER_META` ne couvre ni desktop ni CLI.
- **La CI ne teste que le code hors-ligne.** Elle ne prouve aucun comportement réseau.

---

## 🧭 Prochaine étape

1. Poser un vrai compte (`data/creds/<compte>.json`) et valider les 15 adapters un par un contre leur front.
2. Exercer `ChallengeBypasser.harvest_session()` sur un site réel.
3. Étendre `PROVIDER_META` aux fronts desktop/CLI.
4. Publication officielle des paquets npm / PyPI (préparés, vérifiés en CI, en attente de tokens).

---

## 📐 État du dépôt

- Licence propriétaire, tous droits réservés — voir [`LICENSE`](LICENSE).
- Modèle de sécurité et procédure de signalement : [`SECURITY.md`](SECURITY.md).
- Attribution des assets tiers (three.js, modèle 3D) : [`CREDITS.md`](CREDITS.md).
- `data/` est un **état local** (identités, lanes, catalogue, sessions) : jamais versionné.
