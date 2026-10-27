# Sécurité — ViaRoma

Ce projet manipule des **identités de session** (cookies, jetons, empreinte TLS) et
des **IP de sortie jetables**. C'est une surface sensible : une fuite ici ne se voit
pas, elle se sent quand un compte se fait bannir ou qu'une adresse se met à circuler.

Les règles ci-dessous ne sont pas des intentions : elles sont **codées dans le
noyau** et vérifiées par `tests/test_security_context.py`.

---

## 🔒 Garanties du noyau

| Garantie | Mécanisme | Test |
|---|---|---|
| **L'IP de la machine n'est jamais transmise** | Aucun provider n'est exécuté sans proxy de sortie : `build_providers()` **écarte** le compte (*fail-closed*). Le proxy vient de la lane **du compte**, jamais d'un réglage global. | `test_security_context.py` |
| **L'IP réelle n'est jamais lue ni affichée** | L'API ne renvoie que l'IP de sortie (`lane.proxy.public_ip`). L'adresse locale n'est ni lue, ni journalisée, ni exposée. | idem |
| **Les credentials ne quittent jamais la machine** | Résolution à la volée (`env:VAR` / `file:chemin`) au moment de la requête. Aucune valeur n'est journalisée, retournée par l'API, ni versionnée. | idem |
| **Aucune valeur de cookie n'est renvoyée** | Les endpoints de session renvoient un **nombre** de cookies, jamais leurs valeurs. | idem |
| **Les jetons ne voyagent pas en cookie** | Le champ `cookie` est une *chaîne* : elle est cassée en jar. Les jetons partent en `Authorization` ; les méta (`org_id`, `device_id`) dans l'URL ou un header dédié. | idem |
| **Le dashboard n'écoute que sur la boucle locale** | `VIAROMA_HOST` vaut `127.0.0.1` par défaut. | — |
| **Le dépôt ne contient aucun secret** | `data/` est gitignoré. Les comptes ne pointent que vers des références (`env:` / `file:`). | scan pré-push |
| **stdout est réservé au protocole MCP** | Les logs du cœur partent sur **stderr**, sinon ils cassent le JSON-RPC. | `test_mcp_server.py` |

---

## 🧭 Modèle de menace — ce que le projet protège, et de qui

| Acteur | Capacité | Ce qui le protège |
|---|---|---|
| **Un service tiers** (front web du modèle) | Voit l'IP de sortie, le `User-Agent`, le JA3/JA4, les cookies de session | Cohérence de l'identité : IP + TLS + UA + locale viennent du **même** compte. Une incohérence (requête depuis une autre IP, ou avec un autre profil TLS) est le signal de bannissement le plus classique. |
| **Un observateur réseau** | Voit le trafic TLS, mais pas le contenu | Le TLS est spoofé (`curl_cffi`, profils JA3/JA4 par compte), la sortie est un proxy disposable. |
| **Un tiers non autorisé** lit le dépôt | Voit le code | La licence [`LICENSE`](LICENSE) est **propriétaire** : redistribution, fork public et usage commercial sont interdits sans accord écrit. |
| **Un attaquant local** lit la machine | Accès au disque de l'utilisateur | `data/creds/` n'est ni versionné ni chiffré par le projet : c'est la responsabilité de l'opérateur (chiffrement de disque, compte OS dédié). |

---

## 📣 Signaler une faille

Si vous trouvez une faille de sécurité dans ViaRoma :

1. **N'ouvrez pas d'issue publique** tant que le correctif n'est pas livré.
2. Écrivez via les **issues privées** du dépôt GitHub, ou par DM à l'auteur.
3. Décrivez : le composant, la reproduction, l'impact (fuite d'IP ? fuite de
   credential ? contournement du fail-closed ?), et si possible un correctif.
4. Vous avez droit à une **publication** de la faille après correctif et
   mise à jour de cette page — sauf si la publication expose un secret en
   circulation, auquel cas l'accord sera discuté au cas par cas.

**Délai cible** : accusé de réception sous 7 jours, correctif ou plan de
correctif sous 30 jours.

---

## 🧾 Checklist avant publication (à faire à chaque push)

```powershell
# 1. Aucun secret dans l'historique ni dans le working tree
git log -p --all | Select-String -Pattern 'sk-|AIza|Bearer [A-Za-z0-9]{20,}|sessionKey='
git ls-files | Select-String -Pattern 'sk-|AIza|sessionKey='

# 2. data/ est bien ignoré
git check-ignore -v data/creds data/identities.json data/egress_lanes.json

# 3. Les 4 suites passent
.venv/Scripts/python.exe tests/test_burn_chain.py
.venv/Scripts/python.exe tests/test_identity.py
.venv/Scripts/python.exe tests/test_security_context.py
.venv/Scripts/python.exe tests/test_mcp_server.py
```

La CI (`.github/workflows/ci.yml`) rejoue les points 3 à chaque push.

---

## ⚠️ Limites assumées

* ViaRoma **ne chiffre pas** vos credentials : elles vivent en clair dans
  `data/creds/` (hors git). C'est le job du système d'exploitation, pas du projet.
* La récolte de session n'a encore jamais tourné contre un front réel : le
  chemin « cookies récoltés → jar fusionné » est prouvé par test unitaire, pas
  par une session réelle.
* Une complétion réelle n'a pas encore été observée : elle dépend de vos
  credentials.
* Le fail-closed protège contre la sortie non intentionnelle sur l'IP locale.
  Il ne protège pas contre un proxy qui ment sur sa propre adresse.

---

© 2026 MlkBlk-IT — Tous droits réservés. Voir [`LICENSE`](LICENSE).
