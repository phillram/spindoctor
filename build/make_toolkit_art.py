"""Draw the wheel art for the helpers `install-tools` can add to a wheel.

Writes ``spindoctor/assets/toolkit_<key>.png`` for every helper in
``spindoctor.toolkit_helpers.HELPERS``: a transparent 400x156 PNG (a
HyperSpin wheel logo) with the name in upper-case italic Impact, pink
(#D9196B), over a soft blue (#0A6AEA) glow down and to the right.  One or two
lines, fitted to 372x132; every name gets the same letter size, the size at
which "RESET BUTTON" fills the width, unless it has to shrink to fit.

The PNGs are committed, so SpinDoctor itself needs neither Pillow nor the
font.  Re-run this after adding a helper (Pillow required):

    python build/make_toolkit_art.py                 # Impact from the Windows fonts folder
    python build/make_toolkit_art.py --font impact.ttf
    python build/make_toolkit_art.py --only restart-cabinet

Impact is a Windows font; on other systems pass ``--font`` with a bold
condensed font (the result then looks different).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "spindoctor" / "assets"

WIDTH, HEIGHT = 400, 156
BOX_W, BOX_H = 372, 132          # the text is fitted inside this
PINK = (0xD9, 0x19, 0x6B, 255)
BLUE = (0x0A, 0x6A, 0xEA)
GLOW_ALPHA = 150
GLOW_OFFSET = (7, 9)             # the glow sits down and to the right
GLOW_SCALE = 4                   # drawn at a quarter of the size, then scaled up: a cheap blur
GLOW_SPREAD = 3                  # outline around the quarter-size text (a MaxFilter size)
SLANT = 0.33                     # italic: x moves this much per unit of height
EM = 256                         # drawing size before scaling; big enough to stay sharp
LINE_GAP = 1.05                  # line spacing, in em
REFERENCE = "RESET BUTTON"       # the longest line that still gets the full letter size

#: How each helper's name breaks into lines; any other helper splits in two
#: by width.
LINES = {
    "refresh-favorites": ["REFRESH", "FAVORITES"],
    "refresh-recently-played": ["REFRESH", "RECENTLY PLAYED"],
    "refresh-most-played": ["REFRESH", "MOST PLAYED"],
    "refresh-all": ["REFRESH", "ALL"],
    "shut-down-cabinet": ["SHUT DOWN", "CABINET"],
    "restart-cabinet": ["RESTART", "CABINET"],
    "exit-to-windows": ["EXIT TO", "WINDOWS"],
    "reset-button-lights": ["RESET BUTTON", "LIGHTS"],
    "set-windows-resolution": ["SET WINDOWS", "RESOLUTION"],
}


def default_font() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts" / "impact.ttf"


def split_lines(name: str) -> "list[str]":
    """Two lines of about equal length (one for a single word)."""
    words = name.upper().split()
    if len(words) < 2:
        return words
    best = min(range(1, len(words)),
               key=lambda i: max(len(" ".join(words[:i])), len(" ".join(words[i:]))))
    return [" ".join(words[:best]), " ".join(words[best:])]


def _line_mask(line, font):
    """One line, slanted like an italic face, as an L mask of the full line height."""
    from PIL import Image, ImageDraw

    pad = EM // 2  # room for the ink outside the advance box
    height = EM + 2 * pad
    canvas = Image.new("L", (int(font.getlength(line)) + 2 * pad + int(SLANT * height), height), 0)
    ImageDraw.Draw(canvas).text((pad, pad), line, fill=255, font=font)
    # The top moves right: x_src = x_dst + SLANT * (y - bottom), as an affine map.
    return canvas.transform(canvas.size, Image.AFFINE, (1, SLANT, -SLANT * height, 0, 1, 0),
                            resample=Image.BICUBIC)


def _text_mask(lines, font):
    """The lines, each slanted and centred under the one before, trimmed to the ink."""
    from PIL import Image

    masks = [_line_mask(line, font) for line in lines]
    boxes = [m.getbbox() or (0, 0, 1, 1) for m in masks]
    ink_w = max(b[2] - b[0] for b in boxes)
    line_h = int(EM * LINE_GAP)
    canvas = Image.new("L", (ink_w + 2, masks[0].height + line_h * (len(lines) - 1)), 0)
    for i, (mask, box) in enumerate(zip(masks, boxes)):
        x = (ink_w - (box[2] - box[0])) // 2 - box[0]
        canvas.paste(mask, (x, i * line_h), mask)
    return canvas.crop(canvas.getbbox())


def render(lines, font_path: Path):
    """One wheel logo as an RGBA image."""
    from PIL import Image, ImageChops, ImageFilter, ImageFont

    font = ImageFont.truetype(str(font_path), EM)
    mask = _text_mask(lines, font)
    cap = BOX_W / _text_mask([REFERENCE], font).width
    scale = min(BOX_W / mask.width, BOX_H / mask.height, cap)
    size = (max(1, round(mask.width * scale)), max(1, round(mask.height * scale)))
    mask = mask.resize(size, Image.LANCZOS)
    x = round(WIDTH / 2 - 4 - mask.width / 2)
    y = round((HEIGHT - mask.height) / 2 - 6)

    placed = Image.new("L", (WIDTH, HEIGHT), 0)
    placed.paste(mask, (x, y))

    # Glow: the text at a quarter size, filled and outlined in translucent blue
    # (where the two overlap it's denser), then scaled back up, which blurs it.
    fill = placed.resize((WIDTH // GLOW_SCALE, HEIGHT // GLOW_SCALE), Image.BOX)
    outline = fill.filter(ImageFilter.MaxFilter(GLOW_SPREAD))

    def translucent(mask):
        return mask.point(lambda v: v * GLOW_ALPHA // 255)

    # One translucent layer over another: a + b - a*b, which is what "screen" computes.
    small = ImageChops.screen(translucent(fill), translucent(outline))
    glow = small.resize((WIDTH, HEIGHT), Image.BICUBIC)
    shifted = Image.new("L", (WIDTH, HEIGHT), 0)
    shifted.paste(glow, GLOW_OFFSET)

    out = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    out.paste(Image.new("RGBA", (WIDTH, HEIGHT), BLUE + (255,)), (0, 0), shifted)
    out.paste(Image.new("RGBA", (WIDTH, HEIGHT), PINK), (0, 0), placed)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--font", type=Path, default=None, help="TrueType font (default: Windows Impact)")
    parser.add_argument("--only", action="append", default=[], help="Draw just this helper key (repeatable)")
    parser.add_argument("--out", type=Path, default=ASSETS, help="Folder to write to (default: spindoctor/assets)")
    args = parser.parse_args(argv)
    font = args.font or default_font()
    if not font.is_file():
        parser.error(f"font not found: {font} (pass --font)")
    sys.path.insert(0, str(ROOT))
    from spindoctor.toolkit_helpers import HELPERS

    args.out.mkdir(parents=True, exist_ok=True)
    for helper in HELPERS:
        if args.only and helper.key not in args.only:
            continue
        lines = LINES.get(helper.key) or split_lines(helper.name)
        path = args.out / f"toolkit_{helper.key}.png"
        render(lines, font).save(path, optimize=True)
        print(f"{path.name}: {' / '.join(lines)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
