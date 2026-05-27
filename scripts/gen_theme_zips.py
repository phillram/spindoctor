#!/usr/bin/env python3
"""Generate HyperSpin theme zip files for synthetic wheels.

Run from the repo root:
    python3 scripts/gen_theme_zips.py

Produces spindoctor/assets/theme_{Favorites,Most_Played,Recently_Played}.zip
each containing:
  Theme.xml        — layout with a centred 16:9 <video> element
  Background.swf   — minimal blank FWS SWF (transparent, 1 frame)
  Artwork1.swf     — minimal blank FWS SWF
  Artwork4.swf     — minimal blank FWS SWF
  Video.png        — 256×144 thumbnail scaled from the bundled background PNG
  Info.txt         — authorship metadata
"""

from __future__ import annotations

import struct
import zipfile
from io import BytesIO
from pathlib import Path

ASSETS_DIR = Path(__file__).parent.parent / "spindoctor" / "assets"

SYSTEMS = [
    "Favorites",
    "Most Played",
    "Recently Played",
]

BG_ASSETS: dict[str, str] = {
    "Favorites":       "bg_Favorites.png",
    "Most Played":     "bg_Most_Played.png",
    "Recently Played": "bg_Recently_Played.png",
}

# ── SWF generation ─────────────────────────────────────────────────────────────

def _encode_swf_rect(xmax_twips: int, ymax_twips: int) -> bytes:
    """Encode an SWF RECT for a (0, 0) → (xmax, ymax) stage.

    RECT layout (SWF spec §SWF file format):
        Nbits  UB[5]        number of bits for each value
        Xmin   SB[Nbits]    = 0
        Xmax   SB[Nbits]
        Ymin   SB[Nbits]    = 0
        Ymax   SB[Nbits]
    Total bits = 5 + 4*Nbits, zero-padded to a byte boundary.
    """
    nbits = max(xmax_twips.bit_length(), ymax_twips.bit_length()) + 1  # +1 for sign bit

    # Build the bit-stream as a Python integer
    acc = nbits  # first 5 bits = Nbits
    for v in (0, xmax_twips, 0, ymax_twips):
        acc = (acc << nbits) | (v & ((1 << nbits) - 1))

    total_bits = 5 + 4 * nbits
    nbytes = (total_bits + 7) // 8
    acc <<= (nbytes * 8 - total_bits)          # zero-pad to byte boundary
    return acc.to_bytes(nbytes, "big")


def _swf_tag(tag_type: int, data: bytes = b"") -> bytes:
    """Return a SWF RECORDHEADER + payload (short form if len < 63, else long)."""
    if len(data) < 63:
        return struct.pack("<H", (tag_type << 6) | len(data)) + data
    return struct.pack("<H", (tag_type << 6) | 63) + struct.pack("<I", len(data)) + data


def make_blank_swf(w_px: int = 1024, h_px: int = 768, fps: int = 24) -> bytes:
    """Return a minimal valid uncompressed FWS SWF with one blank frame.

    Signature: FWS (uncompressed — no zlib dependency required).
    Version: 9 (Flash Player 9, well-supported by Adobe AIR).
    Tags: SetBackgroundColor(black) + ShowFrame + End.
    """
    rect = _encode_swf_rect(w_px * 20, h_px * 20)          # twips = px × 20
    frame_rate  = struct.pack("<BB", 0, fps)                 # 8.8 fixed-point LE
    frame_count = struct.pack("<H", 1)

    body = (
        rect
        + frame_rate
        + frame_count
        + _swf_tag(9, bytes([0, 0, 0]))     # SetBackgroundColor: RGB(0,0,0)
        + _swf_tag(1)                        # ShowFrame
        + _swf_tag(0)                        # End
    )
    header = b"FWS" + bytes([9]) + struct.pack("<I", 8 + len(body))
    return header + body


# ── Theme.xml ─────────────────────────────────────────────────────────────────

# 16:9 video (600×338) centred at (512, 350) on HyperSpin's 1024×768 canvas.
# Attributes mirror the Atari 8-bit reference theme; type/start/rest="none"
# keeps it static so there are no dependency on HyperSpin particle effects.
THEME_XML = """\
<Theme>
    <video w="600"
           h="338"
           x="512"
           y="350"
           r="0"
           rx="0"
           ry="0"
           below="false"
           overlaybelow="false"
           overlayoffsetx="0"
           overlayoffsety="0"
           forceaspect="both"
           time="0.3"
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
    "Particle Preset Created By: SpinDoctor\n"
    "Date: 2024\n"
    "Created With: SpinDoctor  https://github.com/your-org/spindoctor\n"
)

# ── Thumbnail (Video.png) ──────────────────────────────────────────────────────

def _make_video_png(bg_path: Path, w: int = 256, h: int = 144) -> bytes:
    """Scale the background PNG down to a 256×144 thumbnail (Video.png)."""
    from PIL import Image  # type: ignore[import]
    img = Image.open(bg_path).convert("RGB")
    img = img.resize((w, h), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    blank_swf = make_blank_swf()

    # Sanity-check the RECT encoding: first 5 bits must equal Nbits (16 for 1024×768)
    first_byte = blank_swf[8]  # RECT starts at byte 8 (after the 8-byte SWF header)
    nbits_check = first_byte >> 3  # top 5 bits of the first RECT byte
    assert nbits_check == 16, f"RECT Nbits mismatch: got {nbits_check}, expected 16"

    print(f"Blank SWF: {len(blank_swf)} bytes  header={blank_swf[:8].hex()}  RECT[0]=0x{first_byte:02X} (Nbits={nbits_check})")
    print()

    for system_name in SYSTEMS:
        safe_name = system_name.replace(" ", "_")
        zip_path  = ASSETS_DIR / f"theme_{safe_name}.zip"
        bg_path   = ASSETS_DIR / BG_ASSETS[system_name]

        video_png = _make_video_png(bg_path)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Theme.xml",     THEME_XML)
            zf.writestr("Background.swf", blank_swf)
            zf.writestr("Artwork1.swf",   blank_swf)
            zf.writestr("Artwork4.swf",   blank_swf)
            zf.writestr("Video.png",      video_png)
            zf.writestr("Info.txt",       INFO_TXT)

        size = zip_path.stat().st_size
        print(f"  {zip_path.name}  ({size:,} bytes)")
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                print(f"    {info.filename:20s}  {info.file_size:>8,} bytes")
        print()


if __name__ == "__main__":
    main()
