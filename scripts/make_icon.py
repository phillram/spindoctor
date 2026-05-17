"""Generate the SpinDoctor window icon from the source PNG.

Source artwork lives at ``scripts/icon-source.png`` — a 512x512 RGBA PNG
of the chibi arcade-cabinet mark. This script downsamples it to the
package's runtime icon files:

* ``spindoctor/assets/icon.png`` — 256x256 PNG for the cross-platform
  ``iconphoto`` loader (macOS / Linux).
* ``spindoctor/assets/icon.ico`` — multi-resolution Windows ICO
  (16 / 24 / 32 / 48 / 64 / 128 / 256) for the ``iconbitmap`` loader.

Usage:
    python scripts/make_icon.py --preview    # writes /tmp/spindoctor-icon-preview-*.png
    python scripts/make_icon.py --commit     # writes spindoctor/assets/icon.{png,ico}

Resampling: LANCZOS at every size. The source has both pixel-art
elements (CRT scanlines, ghost, marquee bulbs) and antialiased shapes
(buttons, joystick) — LANCZOS preserves both without the heavy jaggies
that NEAREST would introduce on the curves.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


SOURCE = Path(__file__).resolve().parent / "icon-source.png"

# Multi-res sizes baked into the Windows .ico. Windows Explorer picks
# the closest match for the current view (small thumbnails / details /
# tiles / extra-large), so shipping the full ladder avoids the OS
# rescaling on the fly and looking blurry.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _load_source() -> Image.Image:
    if not SOURCE.exists():
        raise SystemExit(
            f"Source PNG missing: {SOURCE}\n"
            "Drop the master artwork at this path and re-run."
        )
    with Image.open(SOURCE) as src:
        if src.mode != "RGBA":
            return src.convert("RGBA")
        return src.copy()


def _resample(src: Image.Image, size: int) -> Image.Image:
    if src.size == (size, size):
        return src.copy()
    return src.resize((size, size), resample=Image.LANCZOS)


def _write_png(src: Image.Image, out: Path, size: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    _resample(src, size).save(out, format="PNG")


def _write_ico(src: Image.Image, out: Path) -> None:
    layers = [_resample(src, s) for s in ICO_SIZES]
    out.parent.mkdir(parents=True, exist_ok=True)
    # Pillow expects the base image to carry every sub-size via the
    # `sizes=` arg; the others get embedded as additional .ico frames.
    layers[-1].save(out, format="ICO", sizes=[(s, s) for s in ICO_SIZES])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true",
                    help="write previews to /tmp instead of the repo")
    ap.add_argument("--commit", action="store_true",
                    help="overwrite spindoctor/assets/icon.{png,ico}")
    args = ap.parse_args()

    if not args.preview and not args.commit:
        ap.error("pass --preview or --commit")

    src = _load_source()
    repo_root = Path(__file__).resolve().parent.parent

    if args.preview:
        for s in (32, 64, 128, 256):
            out = Path(f"/tmp/spindoctor-icon-preview-{s}.png")
            _write_png(src, out, s)
            print(f"preview written: {out}")

    if args.commit:
        assets = repo_root / "spindoctor" / "assets"
        _write_png(src, assets / "icon.png", size=256)
        _write_ico(src, assets / "icon.ico")
        print(f"icons written to {assets}")


if __name__ == "__main__":
    main()
