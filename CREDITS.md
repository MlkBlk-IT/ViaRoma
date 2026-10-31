# Credits & attributions

This project integrates third-party elements. Each attribution below is
OBLIGATORY.

## 3D Model of the Colosseum

- **Model**: 3D reconstruction of the Colosseum (Anfiteatro Flavio) — edition
  « 80 d.C. » et « aujourd'hui ».
- **Auteur / source** : [Colosseum.how](https://www.colosseum.how/it/modello-3d)
  — Artur Jakucewicz.
- **License**: free use, including commercial use, **on condition of quoting
  Colosseum.how with an active link**.
- **Files**: `data/models/colosseum-ad-80.glb` (24 Mo) et
  `data/models/colosseum-today.glb` (8 MB) — **missing from the repository** (too many
  large) and downloaded by `scripts/fetch_3d_assets.py`.
- **Attribution to display**:

  ```html
  <a href="https://www.colosseum.how/it/modello-3d">3D Model: Colosseum.how</a>
  ```

If the model is not present, the dashboard switches to a Coliseum
procedurally generated on the fly (no external dependencies).

## three.js

- **Library** : three.js r160 — <https://threejs.org>
- **License**: MIT — see `src/dashboard/static/vendor/three/`.
- three.js is **sold in the deposit** (file `vendor/three/`) so that the
  dashboard works without network access and without CDN at runtime.

## Colosseum.how — contexte

The geometry of the Colosseum follows the actual historical dimensions
(188 × 156 m, 48 m high). The positions of neighboring monuments come
from OpenStreetMap (contributors), via the model source.

## Catalog data sources

The Free Hunter catalog is created by direct scraping, at runtime,
d'API publiques :

- OpenRouter (`/api/v1/models`) — real context windows.
- Hugging Face (`/api/models`, `/api/models?filter=gguf`, `/api/daily_papers`)
  — including GGUF metadata (context window and context files)
  real quantification).
- Registre Ollama (`ollama.com/api/tags`).
- NVIDIA NIM, llm7, and OpenAI compatible APIs listed in
  `src/hunter/hunter.py` (SOURCES).

News feeds in the **Live** tab come from RSS/JSON feeds
audiences from Hugging Face, r/LocalLLaMA, Hacker News, OpenAI and Google AI.
