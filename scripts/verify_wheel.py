"""Checks the contents of the constructed wheel.

A wheel without dashboard assets is installed but the dashboard is silent
(HTML/CSS/JS missing) or the Colisee 3D is not displayed (three.js absent).
This check catches the error BEFORE publishing.

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
    # three.js + addons: the 3D renderer is sold, not loaded from a CDN.
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
        print("FAILURE: no wheel found (" + pattern + ")")
        return 1
    wheel = wheels[-1]
    names = zipfile.ZipFile(wheel).namelist()

    missing = [r for r in REQUIRED if not any(n.endswith(r) for n in names)]
    if missing:
        print("FAILED: assets missing in " + os.path.basename(wheel))
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
        print("FAILED: unwanted files in wheel:")
        for d in sorted(set(dirty))[:20]:
            print("  - " + d)
        return 1

    size = sum(i.file_size for i in zipfile.ZipFile(wheel).infolist())
    print(
        "OK: wheel {0} - {1} files, {2:.1f} MB, assets dashboard + three.js included".format(
            os.path.basename(wheel), len(names), size / (1024 * 1024)
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
