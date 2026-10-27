# Crédits & attributions

Ce projet intègre des éléments tiers. Chaque attribution ci-dessous est
obligatoire.

## Modèle 3D du Colisée

- **Modèle** : reconstruction 3D du Colisée (Anfiteatro Flavio) — édition
  « 80 d.C. » et « aujourd'hui ».
- **Auteur / source** : [Colosseum.how](https://www.colosseum.how/it/modello-3d)
  — Artur Jakucewicz.
- **Licence** : usage libre, y compris commercial, **à condition de citer
  Colosseum.how avec un lien actif**.
- **Fichiers** : `data/models/colosseum-ad-80.glb` (24 Mo) et
  `data/models/colosseum-today.glb` (8 Mo) — **absents du dépôt** (trop
  volumineux) et téléchargés par `scripts/fetch_3d_assets.py`.
- **Attribution à afficher** :

  ```html
  <a href="https://www.colosseum.how/it/modello-3d">Modèle 3D : Colosseum.how</a>
  ```

Si le modèle n'est pas présent, le dashboard bascule sur un Colisée
procédural généré à la volée (aucune dépendance externe).

## three.js

- **Bibliothèque** : three.js r160 — <https://threejs.org>
- **Licence** : MIT — voir `src/dashboard/static/vendor/three/`.
- three.js est **vendu dans le dépôt** (dossier `vendor/three/`) pour que le
  dashboard fonctionne sans accès réseau et sans CDN au moment de l'exécution.

## Colosseum.how — contexte

La géométrie du Colisée suit les dimensions réelles historiques
(188 × 156 m, 48 m de haut). Les positions des monuments voisins viennent
d'OpenStreetMap (contributeurs), via la source du modèle.

## Sources de données du catalogue

Le catalogue du Free Hunter est constitué par scraping direct, au runtime,
d'API publiques :

- OpenRouter (`/api/v1/models`) — fenêtres de contexte réelles.
- Hugging Face (`/api/models`, `/api/models?filter=gguf`, `/api/daily_papers`)
  — y compris les métadonnées GGUF (fenêtre de contexte et fichiers de
  quantification réels).
- Registre Ollama (`ollama.com/api/tags`).
- NVIDIA NIM, llm7, et les API compatibles OpenAI listées dans
  `src/hunter/hunter.py` (SOURCES).

Les flux d'actualités de l'onglet **Live** proviennent des flux RSS/JSON
publics de Hugging Face, r/LocalLLaMA, Hacker News, OpenAI et Google AI.
