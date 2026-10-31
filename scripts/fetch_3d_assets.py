#!/usr/bin/env python3
"""Download the 3D models of the Colosseum (GLB) for the ViaRoma dashboard.

Sources (3D models published by Colosseum.how, free use including
commercial, subject to citing Colosseum.how with an active link):

  - colosseum-ad-80.glb (~24 MB) Colosseo from the year 80, with velarium
  - colosseum-today.glb (~8 MB) current state of Colosseo

See CREDITS-ATTRIBUTIONS.txt for allocation.

Files are written to ``data/models/`` et servis par l'application
via road ``/dashboard/static/models/{filename}``.

Usage :
    python scripts/fetch_3d_assets.py [--force] [--only NAME]

The script is idempotent: a file already present AND valid (magic glTF)
is not re-downloaded.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(REPO_ROOT, "data", "models")

#: Magic bytes of a binary glTF container (GLB): 0x67 0x6C 0x54 0x46 = "glTF".
GLTF_MAGIC = b"glTF"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 ViaRoma/1.0"
)

ASSETS = (
    (
        "colosseum-ad-80.glb",
        "https://www.colosseum.how/images/colosseum-3d/models/colosseum-ad-80.glb",
    ),
    (
        "colosseum-today.glb",
        "https://www.colosseum.how/images/colosseum-3d/models/colosseum-today.glb",
    ),
)

CHUNK = 1024 * 1024


def human_size(n: int) -> str:
    """Taille lisible (Mo/Ko/octets)."""
    step = float(n)
    for unit in ("octets", "Ko", "Mo", "Go"):
        if step < 1024.0 or unit == "Go":
            if unit == "octets":
                return f"{int(step)} {unit}"
            return f"{step:.2f} {unit}"
        step /= 1024.0
    return f"{step:.2f} Go"


def check_glb(path: str) -> bool:
    """True if the file exists, is non-empty and begins with the magic "glTF"."""
    if not os.path.isfile(path):
        return False
    if os.path.getsize(path) < 4:
        return False
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == GLTF_MAGIC
    except OSError:
        return False


def download(url: str, dest: str) -> int:
    """Download `url` vers `dest` (atomic writing). Returns the actual size."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest + ".part"
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            declared = response.headers.get("Content-Length")
            declared = int(declared) if declared and declared.isdigit() else 0
            print(f"    HTTP {response.status}  Content-Length={declared or '?'}")
            with open(tmp, "wb") as fh:
                while True:
                    block = response.read(CHUNK)
                    if not block:
                        break
                    fh.write(block)
                    total += len(block)
                    pct = f" ({total * 100 // declared}%)" if declared else ""
                    sys.stdout.write(f"\r    recu {human_size(total)}{pct}   ")
                    sys.stdout.flush()
        sys.stdout.write("\r" + " " * 70 + "\r")
        if total == 0:
            raise RuntimeError("empty answer")
        os.replace(tmp, dest)
        return total
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def fetch(name: str, url: str, force: bool = False) -> bool:
    dest = os.path.join(MODELS_DIR, name)
    print(f"\n>> {name}")
    print(f"    source : {url}")
    if not force and check_glb(dest):
        print(f"    already present and valid -> {human_size(os.path.getsize(dest))} (ignore)")
        return True
    if force and os.path.exists(dest):
        print("    --force : retelechargement")
    try:
        size = download(url, dest)
    except urllib.error.HTTPError as exc:
        print(f"    FAILED HTTP {exc.code} {exc.reason}", file=sys.stderr)
        return False
    except Exception as exc:  # noqa: BLE001 - we want a clear message
        print(f"    FAILED network : {exc}", file=sys.stderr)
        return False

    if not check_glb(dest):
        head = b""
        try:
            with open(dest, "rb") as fh:
                head = fh.read(4)
        except OSError:
            pass
        print(
            "    FAILURE: magic glTF absent (expected 67 6C 54 46, obtained "
            f"{head.hex(' ') or 'rien'})",
            file=sys.stderr,
        )
        return False
    print(f"    OK  {human_size(size)}  ({size} octets)  magic=glTF")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Download the GLBs from the Coliseum.")
    parser.add_argument("--force", action="store_true", help="redownload even if valid")
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        metavar="NAME",
        help="only processes this asset (repeatable)",
    )
    args = parser.parse_args(argv)

    selected = ASSETS
    if args.only:
        wanted = {name.lower() for name in args.only}
        selected = tuple(a for a in ASSETS if a[0].lower() in wanted)
        if not selected:
            print(f"aucun asset ne correspond a {args.only}", file=sys.stderr)
            return 2

    os.makedirs(MODELS_DIR, exist_ok=True)
    print(f"Repertoire cible : {MODELS_DIR}")

    failed = []
    for name, url in selected:
        if not fetch(name, url, force=args.force):
            failed.append(name)

    print("\n" + "=" * 66)
    for name, _ in selected:
        path = os.path.join(MODELS_DIR, name)
        ok = check_glb(path)
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        print(f"{'OK ' if ok else 'KO '} {name:<24} {human_size(size):>12}  magic={'glTF' if ok else '?'}")
    print("=" * 66)

    if failed:
        print(f"FAILED for: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("All models are in place.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
