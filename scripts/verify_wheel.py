"""Verifie le contenu du wheel construit.

Un wheel sans les assets du dashboard s'installe mais le dashboard est muet
(HTML/CSS/JS manquants) ou la Colisee 3D ne s'affiche pas (three.js absent).
Ce controle attrape l'erreur AVANT publication.

Usage:  python scripts/verify_wheel.py [dist/*.whl]
"""
import glob
import os
import sys
import zipfile

REQUIRED = [
    "src/dashboard/static/index.html",
    "src/dashboard/static/style.css",
    "src/dashboard/static/app.js",
    "src/dashboard/static/colosseum3d.js",
    "src/dashboard/static/architecture.js",
    # three.js + addons: le renderer 3D est vendu, pas charge depuis un CDN.
    "src/dashboard/static/vendor/three/three.module.js",
    "src/dashboard/static/vendor/three/addons/loaders/GLTFLoader.js",
    "src/dashboard/static/vendor/three/addons/controls/OrbitControls.js",
]

FORBIDDEN_MARKERS = ["__pycache__/", ".pyc", "data/creds", "egress_lanes.json", "free_models_catalog.json"]


def main(argv):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pattern = argv[0] if argv else os.path.join(root, "dist", "*.whl")
    wheels = sorted(glob.glob(pattern))
    if not wheels:
        print("ECHEC: aucun wheel trouve (" + pattern + ")")
        return 1
    wheel = wheels[-1]
    names = zipfile.ZipFile(wheel).namelist()

    missing = [r for r in REQUIRED if not any(n.endswith(r) for n in names)]
    if missing:
        print("ECHEC: assets manquants dans " + os.path.basename(wheel))
        for m in missing:
            print("  - " + m)
        return 1

    dirty = []
    for n in names:
        for marker in FORBIDDEN_MARKERS:
            if marker in n:
                dirty.append(n)
                break
    if dirty:
        print("ECHEC: fichiers indesirables dans le wheel:")
        for d in sorted(set(dirty))[:20]:
            print("  - " + d)
        return 1

    size = sum(i.file_size for i in zipfile.ZipFile(wheel).infolist())
    print(
        "OK: wheel {0} - {1} fichiers, {2:.1f} Mo, assets dashboard + three.js inclus".format(
            os.path.basename(wheel), len(names), size / (1024 * 1024)
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
