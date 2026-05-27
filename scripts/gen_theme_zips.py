#!/usr/bin/env python3
"""Generate HyperSpin theme zip files for synthetic wheels.

Run from the repo root:
    python3 scripts/gen_theme_zips.py

Produces spindoctor/assets/theme_{Favorites,Most_Played,Recently_Played}.zip
each containing only Theme.xml — matching the reference Favorites.zip provided
by the cabinet owner.

Theme.xml layout
----------------
  w="1024" h="768" x="512" y="384"  — full-screen, centred on 1024×768 canvas
  forceaspect="both"                — maintain video aspect ratio
  type/start/rest="none"            — no animations

The zip contains ONLY Theme.xml (no Info.txt, no SWF files, no Video.png),
exactly matching the reference theme structure.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

ASSETS_DIR = Path(__file__).parent.parent / "spindoctor" / "assets"

SYSTEMS = [
    "Favorites",
    "Most Played",
    "Recently Played",
]

# ── Theme.xml ─────────────────────────────────────────────────────────────────

# Copied verbatim from the reference Favorites.zip provided by the cabinet owner.
# Full-screen (1024×768), centred at (512, 384), aspect-ratio preserved.
THEME_XML = """\
<Theme>
    <video w="1024"
           h="768"
           x="512"
           y="384"
           r="0"
           rx="0"
           ry="0"
           below="false"
           overlaybelow="false"
           overlayoffsetx="0"
           overlayoffsety="0"
           forceaspect="both"
           time="0"
           delay="0"
           bsize="0"
           bsize2="0"
           bsize3="0"
           bcolor="0"
           bcolor2="0"
           bcolor3="0"
           bshape="false"
           type="none"
           start="none"
           rest="none"/>
</Theme>
"""

# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    for system_name in SYSTEMS:
        safe_name = system_name.replace(" ", "_")
        zip_path  = ASSETS_DIR / f"theme_{safe_name}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Theme.xml", THEME_XML)

        size = zip_path.stat().st_size
        print(f"  {zip_path.name}  ({size:,} bytes)")
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                print(f"    {info.filename:20s}  {info.file_size:>8,} bytes")
        print()


if __name__ == "__main__":
    main()
