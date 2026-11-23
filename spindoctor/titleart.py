"""Draw a game's title as a HyperSpin wheel picture, and "not found" cards.

Plain drawing with Pillow and a font already on the PC: no internet, no
artwork service, no AI.  ``generate-media`` decides what to draw and where it
goes; this module only turns text into PNG bytes.
"""
from __future__ import annotations

import io
import itertools
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence

#: Letter colors from top to bottom.
STYLES = {
    "chrome": ((255, 255, 255), (170, 205, 240), (60, 110, 190)),
    "gold": ((255, 244, 170), (255, 176, 20), (214, 70, 8)),
    "white": ((255, 255, 255), (255, 255, 255), (255, 255, 255)),
    "lcd": ((226, 244, 196), (150, 196, 110), (58, 108, 72)),       # a handheld's greenish LCD
    "led": ((255, 222, 210), (255, 72, 48), (186, 8, 8)),           # red LEDs
    "vfd": ((214, 255, 250), (76, 236, 222), (0, 156, 170)),        # a vacuum fluorescent display's cyan
    "neon": ((255, 224, 255), (255, 84, 226), (164, 0, 214)),
}
#: Styles that glow in this color instead of casting a dark shadow: lit displays.
GLOWS = {
    "led": (255, 40, 20),
    "vfd": (0, 255, 226),
    "neon": (255, 0, 214),
}
DEFAULT_STYLE = "chrome"
BACKGROUNDS = ("blue", "snow")
DEFAULT_SIZE = (400, 175)       # what most HyperSpin wheel pictures are
CARD_SIZE = (640, 480)

_EDGE = (10, 10, 16, 255)
_SCALE = 3                      # drawn this many times larger, then scaled down
_LINE = 1.04                    # line height, in letter heights
_MAX_LINES = 4

_LATIN_FONTS = (
    "impact.ttf", "Impact.ttf", "ariblk.ttf", "Arial Black.ttf", "arialbd.ttf", "segoeuib.ttf",
    "verdanab.ttf", "tahomabd.ttf", "DejaVuSansCondensed-Bold.ttf", "DejaVuSans-Bold.ttf",
    "LiberationSans-Bold.ttf", "NotoSans-Bold.ttf",
)
_CARD_FONTS = ("trebucbd.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf",
               "LiberationSans-Bold.ttf")
_CJK_FONTS = ("YuGothB.ttc", "meiryob.ttc", "msgothic.ttc", "msyhbd.ttc", "msyh.ttc", "simhei.ttf",
              "malgunbd.ttf", "NotoSansCJK-Bold.ttc", "NotoSansCJK-Regular.ttc")
_HANGUL_FONTS = ("malgunbd.ttf", "malgun.ttf") + _CJK_FONTS


class TitleArtError(RuntimeError):
    """The picture can't be drawn here: no Pillow, or no usable font."""


def pillow_available() -> bool:
    try:
        import PIL.Image  # noqa: F401
        import PIL.ImageFont  # noqa: F401
    except ImportError:
        return False
    return True


def _need_pillow() -> None:
    if not pillow_available():
        raise TitleArtError("Drawing pictures needs Pillow, which this install doesn't have "
                            "(pip install \"spindoctor[preview]\"; the Windows EXEs include it).")


# ─── the words ────────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"\s*[(\[]([^)\]]*)[)\]]")
# Tags that tell two pictures apart; region, revision and dump tags don't.
_KEEP_TAG_RE = re.compile(r"^\s*((?:dis[ck]|side|tape|part|cart|cassette|volume|vol\.?|program)\s*\w+)",
                          re.I)
_ARTICLE_RE = re.compile(r"^(?P<main>.+?), (?P<article>The|An?|Les?|La|Der|Die|Das|El|Los|Las|Il)"
                         r"(?P<rest>\s+[-:].*)?$", re.I)


def display_title(description: str, name: str = "") -> str:
    """The title to draw: the database description (or *name*) without
    "(USA)"-style tags, with "Legend, The" turned round.  "(Disk 2 of 3)"
    stays as "Disk 2", so a game's disks don't all look the same."""
    text = (description or "").strip() or (name or "").strip()
    kept: list[str] = []

    def drop(match):
        keep = _KEEP_TAG_RE.match(match.group(1))
        if keep:
            kept.append(keep.group(1))
        return ""

    base = re.sub(r"\s+", " ", _TAG_RE.sub(drop, text)).strip(" -")
    if not base:
        return text
    match = _ARTICLE_RE.match(base)
    if match:
        base = f"{match['article']} {match['main']}{match['rest'] or ''}"
    return " - ".join([base] + kept)


# Tag parts that don't make two games different games: regions, languages,
# revisions, versions, dump and release marks.
_SAME_GAME_PART_RE = re.compile(
    r"^(?:usa|us|u|europe|eu|e|japan|jp|j|world|w|asia|korea|china|taiwan|brazil|australia|canada|france|"
    r"germany|spain|italy|uk|netherlands|sweden|scandinavia|en|fr|de|es|it|ja|pt|nl|sv|no|da|fi|zh|ko|"
    r"rev\.?\s*\w+|v\s?\d[\w.]*|version\s+\S+|set\s+\d+|alt\w*|beta\s*\d*|proto\w*|demo|sample|unl|"
    r"unlicensed|pirate|hack|translated\b.*|t[+-]\w+|!|a\d*|b\d*|o\d*|h\d*|p\d*|f\d*|\d{4}(?:-\d\d){0,2})$",
    re.I)


def tell_apart(descriptions: Sequence[str], title: str) -> list[str]:
    """Titles for games of one wheel that all display as *title*: each with the
    bracketed parts of its description the others don't share, like
    "Electronic Football - Conic" and "Electronic Football - Epoch", so their
    pictures differ.  Regions, revisions and dump marks don't count, so a
    game's regional copies keep one picture."""
    parts = []
    for text in descriptions:
        found = [p.strip() for tag in _TAG_RE.findall(text or "") for p in tag.split(",")]
        parts.append([p for p in found if p and not _SAME_GAME_PART_RE.match(p)])
    common = set.intersection(*(set(p.lower() for p in ps) for ps in parts)) if parts else set()
    out = []
    for ps in parts:
        extra = [p for p in ps if p.lower() not in common]
        out.append(f"{title} - {', '.join(extra)}" if extra else title)
    return out


# ─── fonts ────────────────────────────────────────────────────────────────────

def _font_dirs() -> list[Path]:
    dirs: list[Path] = []
    if sys.platform == "win32":
        dirs.append(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        dirs += [Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts"),
                 Path("/System/Library/Fonts")]
    else:
        dirs += [Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/truetype/liberation"),
                 Path("/usr/share/fonts/opentype/noto"), Path("/usr/share/fonts/truetype/noto"),
                 Path("/usr/share/fonts/TTF"), Path("/usr/share/fonts/dejavu-sans-fonts")]
    return dirs


def _first_font(names) -> Optional[Path]:
    for name in names:
        for folder in _font_dirs():
            path = folder / name
            if path.is_file():
                return path
    return None


def parse_color(text: str) -> RGB:
    """``#rrggbb``, ``rrggbb`` or ``#rgb`` as ``(r, g, b)``."""
    value = text.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    try:
        if len(value) != 6:
            raise ValueError
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except ValueError:
        raise TitleArtError(f"{text!r} isn't a color: use #rrggbb, like #33ccff.") from None


def color_text(rgb: Sequence[int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


@lru_cache(maxsize=1)
def installed_fonts() -> dict[str, Path]:
    """Every font in the PC's font folders, by the name it shows ("Bahnschrift",
    "Segoe UI Black"), sorted; a font Pillow can't read goes by its file name."""
    _need_pillow()
    from PIL import ImageFont

    found: dict[str, Path] = {}
    for folder in _font_dirs():
        try:
            files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".ttf", ".otf", ".ttc"))
        except OSError:
            continue
        for path in files:
            try:
                family, kind = ImageFont.truetype(str(path), 12).getname()
                name = family if (kind or "").lower() in ("", "regular", "normal", "roman", "book") \
                    else f"{family} {kind}"
            except (OSError, ValueError):
                name = path.stem
            found.setdefault(name or path.stem, path)
    return dict(sorted(found.items(), key=lambda kv: kv[0].casefold()))


def find_font(name: str) -> Path:
    """The font file *name* stands for: a path to a ``.ttf``/``.otf``/``.ttc``,
    or the file name of one in the PC's font folders, with or without its
    extension, in any case (``bahnschrift``, ``Impact.ttf``)."""
    path = Path(name)
    if path.is_file():
        return path
    stem = name.strip().lower()
    if pillow_available():
        for shown, file in installed_fonts().items():
            if shown.lower() == stem:
                return file
    for folder in _font_dirs():
        try:
            files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".ttf", ".otf", ".ttc"))
        except OSError:
            continue
        for p in files:
            if stem in (p.name.lower(), p.stem.lower()):
                return p
    raise TitleArtError(f"No font {name!r} here: give a font file, or the name of one in "
                        f"{', '.join(str(d) for d in _font_dirs()) or 'the font folders'}.")


def font_for(text: str, font: Optional[Path] = None, latin=_LATIN_FONTS) -> Optional[Path]:
    """A font file with the letters of *text*: *font* when given, else a bold
    one from the PC.  None means Pillow's built-in font."""
    if font:
        return Path(font)
    if any(0xAC00 <= ord(c) <= 0xD7A3 or 0x1100 <= ord(c) <= 0x11FF for c in text):
        return _first_font(_HANGUL_FONTS)
    if any(ord(c) >= 0x2E80 for c in text):
        return _first_font(_CJK_FONTS) or _first_font(latin)
    return _first_font(latin)


@lru_cache(maxsize=64)
def _load(path: Optional[Path], size: int):
    from PIL import ImageFont

    if path is not None:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError as exc:
            raise TitleArtError(f"Can't use the font {path}: {exc}") from exc
    try:
        return ImageFont.load_default(size)  # Pillow 10.1+; older ones have one tiny size only
    except TypeError as exc:
        raise TitleArtError("No usable font found. Name one with --font (a .ttf file).") from exc


# ─── layout ───────────────────────────────────────────────────────────────────

def _splits(words: list[str]):
    """Every way to put the words on up to four lines, without the dash a
    line would start or end with."""
    for n in range(1, min(_MAX_LINES, len(words)) + 1):
        for cuts in itertools.combinations(range(1, len(words)), n - 1):
            edges = (0,) + cuts + (len(words),)
            lines = [" ".join(words[a:b]) for a, b in zip(edges, edges[1:])]
            if n > 1:
                lines = [line.strip(" -") for line in lines]
            if all(lines):
                yield lines


def layout(text: str, font: Optional[Path], width: int, height: int,
           largest: float) -> tuple[list[str], int]:
    """``(lines, letter size)``: the split that allows the largest letters in
    *width* x *height*, at most *largest*.  When splits are about equal: the
    one with fewer lines, then the one with the shortest longest line."""
    words = text.split()
    if not words:
        raise TitleArtError("There's no title to draw.")
    if len(words) > 18:  # a very long title has too many splits to try them all
        step = -(-len(words) // 18)
        words = [" ".join(words[i:i + step]) for i in range(0, len(words), step)]
    ref = _load(font, 100)
    widths: dict[str, float] = {}
    best: Optional[tuple[float, list[str], float]] = None
    for lines in _splits(words):
        for line in lines:
            if line not in widths:
                widths[line] = max(1.0, ref.getlength(line))
        widest = max(widths[line] for line in lines)
        size = min(width * 100.0 / widest, height / (_LINE * len(lines)), largest)
        if best is None or size > best[0] * 1.02 or (
                size >= best[0] * 0.98 and len(lines) == len(best[1]) and widest < best[2]):
            best = (size, lines, widest)
    return best[1], max(8, int(best[0]))


def _png(img) -> bytes:
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("Software", "SpinDoctor")
    info.add_text("Comment", "Drawn by SpinDoctor generate-media")
    buf = io.BytesIO()
    img.save(buf, "PNG", pnginfo=info, optimize=True)
    return buf.getvalue()


# ─── pictures ─────────────────────────────────────────────────────────────────

RGB = tuple[int, int, int]


#: What goes round the letters, besides their dark edge.
EFFECTS = ("shadow", "glow", "flat")


def default_effect(style: str) -> str:
    """The effect *style* has of itself: lit displays glow, the rest cast a shadow."""
    return "glow" if style in GLOWS else "shadow"


def draw_title(title: str, style: str = DEFAULT_STYLE, size: tuple[int, int] = DEFAULT_SIZE,
               font: Optional[Path] = None, colors: Optional[Sequence[RGB]] = None,
               effect: str = "style", glow_color: Optional[RGB] = None) -> bytes:
    """*title* as a transparent PNG of *size*: heavy letters in *style*'s
    colors with a dark edge.  *colors* (top, middle, bottom) replace the
    style's.  *effect*: "shadow" (dark and soft), "glow" (in *glow_color*,
    else the style's glow color, else its middle color), "flat" (the edge
    only), or "style" for the style's own (:func:`default_effect`)."""
    _need_pillow()
    from PIL import Image, ImageDraw, ImageFilter

    if style not in STYLES:
        raise TitleArtError(f"Unknown style {style!r}: use {', '.join(STYLES)}.")
    palette = tuple(tuple(c) for c in colors) if colors else STYLES[style]
    if len(palette) != 3:
        raise TitleArtError("Give three colors: top, middle and bottom.")
    effect = default_effect(style) if effect == "style" else effect
    if effect not in EFFECTS:
        raise TitleArtError(f"Unknown effect {effect!r}: use {', '.join(EFFECTS)}.")
    halo = (tuple(glow_color) if glow_color else GLOWS.get(style, palette[1])) if effect == "glow" else None
    text = title.upper()
    path = font_for(text, font)
    w, h = size[0] * _SCALE, size[1] * _SCALE
    margin = max(8, size[0] // 40) * _SCALE
    if halo is not None:
        margin += round(h * 0.08)     # room for the glow, so the picture's edge doesn't cut it off
    lines, letter = layout(text, path, w - 2 * margin, h - 2 * margin, h * 0.62)
    face = _load(path, letter)
    edge = max(_SCALE, round(letter * 0.07))
    step = letter * _LINE
    top = (h - step * len(lines)) / 2 + step / 2

    fill, outline = Image.new("L", (w, h), 0), Image.new("L", (w, h), 0)
    draw_fill, draw_edge = ImageDraw.Draw(fill), ImageDraw.Draw(outline)
    colors = Image.new("RGBA", (w, h), palette[2] + (255,))
    paint = ImageDraw.Draw(colors)
    first, middle, last = palette
    for i, line in enumerate(lines):
        y = top + i * step
        draw_edge.text((w / 2, y), line, font=face, fill=255, anchor="mm",
                       stroke_width=edge, stroke_fill=255)
        draw_fill.text((w / 2, y), line, font=face, fill=255, anchor="mm")
        y0, y1 = int(y - step / 2), int(y + step / 2)
        for row in range(y0, y1 + 1):
            t = min(1.0, max(0.0, (row - y0) / max(1, y1 - y0)))
            a, b, part = (first, middle, t * 2) if t < 0.5 else (middle, last, t * 2 - 1)
            paint.line([(0, row), (w, row)],
                       fill=tuple(round(p + (q - p) * part) for p, q in zip(a, b)) + (255,))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if halo is not None:
        # A lit display: a colored halo round the letters, strongest close in.
        for radius, strength in ((0.12, 2), (0.05, 3)):
            glow_mask = outline.filter(ImageFilter.GaussianBlur(letter * radius)).point(
                lambda v, s=strength: 0 if v * s < 16 else min(255, v * s))     # no faint tail to the edge
            out.paste(tuple(halo) + (255,), (0, 0), glow_mask)
    elif effect == "shadow":
        shadow = outline.filter(ImageFilter.GaussianBlur(letter * 0.04)).point(lambda v: v * 3 // 4)
        out.paste((0, 0, 0, 255), (round(letter * 0.03), round(letter * 0.04)), shadow)
    out.paste(_EDGE, (0, 0), outline)
    out.paste(colors, (0, 0), fill)
    return _png(out.resize(size, Image.LANCZOS))


def draw_card(message: str, title: str = "", background: str = "blue",
              size: tuple[int, int] = CARD_SIZE, font: Optional[Path] = None) -> bytes:
    """A full picture saying *message* ("No video found"), with the game's
    *title* under it."""
    _need_pillow()
    from PIL import Image, ImageDraw

    w, h = size
    if background == "snow":
        img = Image.effect_noise((w // 2, h // 2), 90).point(lambda v: v * 2 // 5)
        img = img.resize((w, h), Image.NEAREST).convert("RGB")
    elif background == "blue":
        img = Image.new("RGB", size)
        paint = ImageDraw.Draw(img)
        for y in range(h):
            t = y / h
            paint.line([(0, y), (w, y)], fill=(int(16 + 10 * t), int(20 + 14 * t), int(38 + 30 * t)))
    else:
        raise TitleArtError(f"Unknown background {background!r}: use {' or '.join(BACKGROUNDS)}.")
    draw = ImageDraw.Draw(img, "RGBA")
    box_h = int(h * 0.40) if title else int(h * 0.25)
    top = (h - box_h) // 2
    draw.rectangle([int(w * 0.06), top, int(w * 0.94), top + box_h],
                   fill=(0, 0, 0, 165), outline=(255, 255, 255, 60))
    text = message.upper()
    path = font_for(text, font)
    lines, letter = layout(text, path, int(w * 0.80), int(h * 0.15), h * 0.12)
    face = _load(path, letter)
    y = top + box_h * (0.30 if title else 0.50) - letter * _LINE * (len(lines) - 1) / 2
    for i, line in enumerate(lines):
        draw.text((w / 2, y + i * letter * _LINE), line, font=face, fill=(255, 255, 255), anchor="mm")
    if title:
        path = font_for(title, None, _CARD_FONTS)
        lines, letter = layout(title, path, int(w * 0.80), int(h * 0.16), h * 0.065)
        face = _load(path, letter)
        step = letter * 1.2
        y = top + box_h * 0.70 - step * (len(lines) - 1) / 2
        for i, line in enumerate(lines):
            draw.text((w / 2, y + i * step), line, font=face, fill=(255, 205, 90), anchor="mm")
    return _png(img)
