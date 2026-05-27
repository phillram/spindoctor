#!/usr/bin/env python3
"""Generate HyperSpin theme zip files for synthetic wheels.

Run from the repo root:
    python3 scripts/gen_theme_zips.py

Produces spindoctor/assets/theme_{Favorites,Most_Played,Recently_Played}.zip
each containing only:
  Theme.xml   — 1×1 invisible video element (audio-only; background PNG provides visuals)
  Info.txt    — authorship metadata

Design rationale
----------------
HyperSpin shows two layers during attract mode:
  1. The background image  (Media\\Main Menu\\Images\\Backgrounds\\<System>.png)
  2. The video overlay     (Media\\Main Menu\\Video\\<System>.mp4, positioned by Theme.xml)

Both layers used to show the same image, producing a visible double-render artefact.
Setting w="1" h="1" makes the video element a single invisible pixel — HyperSpin
still plays the audio track of the MP4, which is exactly what we want for music.
The background PNG provides all the visual content.

The MAME theme (BakerMan, 2016) demonstrates this is the standard "video-only"
approach: Theme.xml + Info.txt, no SWF files, no Video.png required.
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

# w="1" h="1": video element is a single invisible pixel → audio plays, image hidden.
# x="512" y="384": centred on HyperSpin's 1024×768 canvas so the 1px dot appears
# at dead-centre (barely visible even if HyperSpin renders it at minimum size).
# forceaspect="none": do not scale up to preserve aspect ratio.
# All other attributes copied verbatim from the MAME reference theme (BakerMan 2016).
THEME_XML = """\
<Theme>
    <video w="1"
           h="1"
           x="512"
           y="384"
           r="0"
           rx="0"
           ry="0"
           below="false"
           overlaybelow="false"
           overlayoffsetx="0"
           overlayoffsety="0"
           forceaspect="none"
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

INFO_TXT = (
    "Cinematic Theme Created By: SpinDoctor\n"
    "Date: 2024\n"
    "Created With: SpinDoctor\n"
)

# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    for system_name in SYSTEMS:
        safe_name = system_name.replace(" ", "_")
        zip_path  = ASSETS_DIR / f"theme_{safe_name}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Theme.xml", THEME_XML)
            zf.writestr("Info.txt",  INFO_TXT)

        size = zip_path.stat().st_size
        print(f"  {zip_path.name}  ({size:,} bytes)")
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                print(f"    {info.filename:20s}  {info.file_size:>8,} bytes")
        print()


if __name__ == "__main__":
    main()
