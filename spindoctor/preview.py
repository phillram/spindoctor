"""Wheel / theme / media preview generation.

Builds visual previews of a system's media so users can sanity-check what
their HyperSpin library looks like without opening every PNG in turn.

Two output flavours:

* **Contact sheet** — a grid of every wheel with the game name underneath.
  Comes in two formats:

    - HTML (default, no extra deps) uses a CSS grid and ``file://`` paths
      so nothing is copied.
    - PNG (Pillow required) composites each wheel onto a colored cell and
      writes a single image. Falls back to HTML mode with a warning when
      Pillow isn't installed.

* **Per-game card** — a full-page HTML mock of a HyperSpin entry: full-bleed
  background, wheel logo center-bottom, snap top-right, title image
  top-left, plus a metadata strip (display name · year · manufacturer ·
  genre) at the bottom. Theme/sound/video paths are listed when present
  but not embedded.

``render_system_overview`` orchestrates the lot — it writes an
``index.html`` contact sheet, one ``games/<name>.html`` card per game,
and (if Pillow is installed) an ``index.png``.

Pillow is an optional dependency declared in ``setup.py`` under the
``[preview]`` extra and probed at runtime via :mod:`importlib`, mirroring
the ``[archives]`` pattern used by :mod:`spindoctor.archives`.
"""
from __future__ import annotations

import html
import importlib
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import Config
from .database import GameEntry, load_database


_IMG_EXTS = (".png", ".jpg", ".jpeg")
_VIDEO_EXTS = (".mp4", ".avi", ".flv", ".mkv")
_SOUND_EXTS = (".mp3", ".wav", ".ogg")
_THEME_EXTS = (".zip", ".swf")


# ─── data shapes ──────────────────────────────────────────────────────────────


@dataclass
class PreviewItem:
    """One game's worth of media slots, resolved to actual on-disk paths.

    A ``None`` value means the slot is empty for that game.
    ``metadata`` mirrors the GameEntry fields (year, manufacturer, genre,
    rating, description) so the per-game card can render them without
    re-reading the DB.
    """
    game_name: str
    display_name: str
    wheel: Optional[Path] = None
    background: Optional[Path] = None
    snap: Optional[Path] = None
    title_img: Optional[Path] = None
    artwork: Optional[Path] = None
    theme: Optional[Path] = None
    video: Optional[Path] = None
    metadata: dict = field(default_factory=dict)

    def has_any_media(self) -> bool:
        return any(
            p is not None for p in (
                self.wheel, self.background, self.snap, self.title_img,
                self.artwork, self.theme, self.video,
            )
        )


# ─── runtime probe ────────────────────────────────────────────────────────────


def _try_import_pillow():
    """Return the imported Pillow ``Image`` module, or ``None`` if unavailable."""
    try:
        return importlib.import_module("PIL.Image")
    except ImportError:
        return None


def pillow_available() -> bool:
    """True when Pillow is importable. Used by ``spindoctor doctor``."""
    return _try_import_pillow() is not None


# ─── path resolution ──────────────────────────────────────────────────────────


def _first_existing(directory: Path, stem: str, exts: tuple[str, ...]) -> Optional[Path]:
    if not directory.exists():
        return None
    for ext in exts:
        candidate = directory / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def _resolve_theme(media_root: Path, stem: str) -> Optional[Path]:
    """Theme is either a folder Themes/<game>/ or Themes/<game>.zip|.swf."""
    folder = media_root / "Themes" / stem
    if folder.exists() and folder.is_dir():
        return folder
    return _first_existing(media_root / "Themes", stem, _THEME_EXTS)


def _resolve_paths(media_root: Path, stem: str) -> dict[str, Optional[Path]]:
    """Resolve every preview slot for one game stem under ``media_root``."""
    return {
        "wheel": _first_existing(media_root / "Images" / "Wheel", stem, _IMG_EXTS),
        "background": _first_existing(
            media_root / "Images" / "Backgrounds", stem, _IMG_EXTS,
        ),
        # Mirror audit.check_media slot conventions:
        #   Artwork1 → artwork, Artwork2 → title, Artwork3 → snap.
        "artwork": _first_existing(
            media_root / "Images" / "Artwork1", stem, _IMG_EXTS,
        ),
        "title_img": _first_existing(
            media_root / "Images" / "Artwork2", stem, _IMG_EXTS,
        ),
        "snap": _first_existing(
            media_root / "Images" / "Artwork3", stem, _IMG_EXTS,
        ),
        "video": _first_existing(media_root / "Video", stem, _VIDEO_EXTS),
        "theme": _resolve_theme(media_root, stem),
    }


def _build_item(name: str, entry: Optional[GameEntry], media_root: Path) -> PreviewItem:
    paths = _resolve_paths(media_root, name)
    display = (entry.description if entry and entry.description else name) or name
    metadata = {
        "description": entry.description if entry else "",
        "year": entry.year if entry else "",
        "manufacturer": entry.manufacturer if entry else "",
        "genre": entry.genre if entry else "",
        "rating": entry.rating if entry else "",
    }
    return PreviewItem(
        game_name=name,
        display_name=display,
        wheel=paths["wheel"],
        background=paths["background"],
        snap=paths["snap"],
        title_img=paths["title_img"],
        artwork=paths["artwork"],
        theme=paths["theme"],
        video=paths["video"],
        metadata=metadata,
    )


def collect_previews(system_name: str, config: Config) -> list[PreviewItem]:
    """Build a PreviewItem per DB game; skip games with zero media on disk."""
    media_root = config.media_dir / system_name
    db = load_database(system_name, config.databases_dir)

    items: list[PreviewItem] = []
    for name, entry in db.games().items():
        item = _build_item(name, entry, media_root)
        if not item.has_any_media():
            continue
        items.append(item)
    items.sort(key=lambda i: i.display_name.lower())
    return items


def collect_previews_including_missing(
    system_name: str, config: Config,
) -> list[PreviewItem]:
    """Like :func:`collect_previews` but keeps games with no media."""
    media_root = config.media_dir / system_name
    db = load_database(system_name, config.databases_dir)
    items = [
        _build_item(name, entry, media_root)
        for name, entry in db.games().items()
    ]
    items.sort(key=lambda i: i.display_name.lower())
    return items


# ─── HTML helpers ─────────────────────────────────────────────────────────────


def _file_url(path: Path) -> str:
    """Return ``file://`` URL for a Path; safe for local <img> / <a>."""
    return path.resolve().as_uri()


def _e(text: str) -> str:
    return html.escape(text or "", quote=True)


# Single CSS block reused by both the contact sheet and per-game cards.
# Self-contained, no external assets.
_CSS_BASE = """
* { box-sizing: border-box; }
body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #1a1a22;
    color: #e8e8ee;
}
a { color: inherit; text-decoration: none; }
"""

_CSS_CONTACT = """
.header {
    padding: 20px 24px;
    border-bottom: 1px solid #2c2c38;
    background: #14141c;
}
.header h1 { margin: 0; font-size: 20px; font-weight: 600; }
.header .meta { margin-top: 4px; font-size: 12px; color: #8a8aa0; }

.grid {
    display: grid;
    grid-template-columns: repeat(var(--cols, 6), 1fr);
    gap: 12px;
    padding: 16px;
}
.cell {
    background: #232330;
    border: 1px solid #2c2c38;
    border-radius: 6px;
    padding: 10px;
    text-align: center;
    transition: border-color 0.1s ease;
}
.cell:hover { border-color: #4a90e2; }
.cell .wheel-wrap {
    aspect-ratio: 4 / 3;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #15151c;
    border-radius: 4px;
    overflow: hidden;
    margin-bottom: 8px;
}
.cell img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
}
.cell .placeholder {
    color: #555566;
    font-size: 11px;
    letter-spacing: 0.05em;
}
.cell .name {
    font-size: 12px;
    line-height: 1.3;
    word-break: break-word;
    color: #c8c8d4;
}
.cell .slots {
    margin-top: 6px;
    font-size: 10px;
    color: #6a6a7e;
    letter-spacing: 0.04em;
}
.cell .slots .has { color: #6abf6a; }
.cell .slots .no  { color: #444454; }
"""

_CSS_CARD = """
.card {
    position: relative;
    width: 100vw;
    height: 100vh;
    overflow: hidden;
}
.card .bg {
    position: absolute; inset: 0;
    background-size: cover;
    background-position: center;
    background-color: #0a0a10;
    filter: brightness(0.6);
}
.card .layer {
    position: absolute;
    z-index: 2;
}
.card .title-img {
    top: 24px; left: 24px;
    max-width: 30%; max-height: 22%;
}
.card .snap {
    top: 24px; right: 24px;
    max-width: 32%; max-height: 28%;
    border: 2px solid rgba(255,255,255,0.15);
    border-radius: 4px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.5);
}
.card .wheel {
    left: 50%;
    bottom: 18%;
    transform: translateX(-50%);
    max-width: 40%;
    max-height: 30%;
    filter: drop-shadow(0 4px 12px rgba(0,0,0,0.6));
}
.card .layer img { display: block; max-width: 100%; max-height: 100%; }
.card .meta-strip {
    position: absolute;
    left: 0; right: 0; bottom: 0;
    padding: 12px 24px;
    background: linear-gradient(to top, rgba(0,0,0,0.85), rgba(0,0,0,0));
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    font-size: 14px;
    z-index: 3;
}
.card .meta-strip .label { color: #8a8aa0; margin-right: 4px; }
.card .meta-strip .name { font-weight: 600; }
.card .extras {
    position: absolute;
    bottom: 56px; left: 24px;
    z-index: 3;
    font-size: 11px;
    color: #aaaab8;
    background: rgba(0,0,0,0.5);
    padding: 6px 10px;
    border-radius: 4px;
    max-width: 60%;
}
.card .extras div { margin: 2px 0; word-break: break-all; }
.card .placeholder-bg {
    position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    color: #33334a; font-size: 14px;
    background:
      repeating-linear-gradient(45deg, #15151c 0 12px, #1a1a22 12px 24px);
}
.back-link {
    position: fixed;
    top: 12px; left: 12px;
    background: rgba(0,0,0,0.6);
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 12px;
    z-index: 10;
}
"""


# ─── contact sheet (HTML) ─────────────────────────────────────────────────────


def _slot_dot(present: bool, label: str) -> str:
    klass = "has" if present else "no"
    return f'<span class="{klass}" title="{_e(label)}">●</span>'


def _cell_html(item: PreviewItem, card_href: Optional[str]) -> str:
    if item.wheel is not None:
        wheel_html = f'<img src="{_e(_file_url(item.wheel))}" alt="">'
    else:
        wheel_html = '<div class="placeholder">no wheel</div>'

    slots = (
        f'{_slot_dot(item.background is not None, "background")}'
        f'{_slot_dot(item.snap is not None, "snap")}'
        f'{_slot_dot(item.title_img is not None, "title")}'
        f'{_slot_dot(item.artwork is not None, "artwork")}'
        f'{_slot_dot(item.theme is not None, "theme")}'
        f'{_slot_dot(item.video is not None, "video")}'
    )

    inner = (
        f'<div class="wheel-wrap">{wheel_html}</div>'
        f'<div class="name">{_e(item.display_name)}</div>'
        f'<div class="slots">{slots}</div>'
    )
    if card_href:
        return f'<a class="cell" href="{_e(card_href)}">{inner}</a>'
    return f'<div class="cell">{inner}</div>'


def render_contact_sheet_html(
    items: list[PreviewItem],
    output_path: Path,
    columns: int = 6,
    include_missing: bool = False,
    card_dir: Optional[Path] = None,
    title: str = "SpinDoctor preview",
) -> Path:
    """Write a self-contained contact-sheet HTML doc.

    When ``card_dir`` is given, each cell links to ``<card_dir>/<game>.html``
    (relative path resolved against ``output_path``'s parent). Otherwise the
    cells are non-clickable.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    visible = items if include_missing else [i for i in items if i.wheel is not None]

    cells: list[str] = []
    for item in visible:
        href: Optional[str] = None
        if card_dir is not None:
            rel = Path(card_dir) / f"{_safe_filename(item.game_name)}.html"
            try:
                rel = rel.resolve().relative_to(output_path.parent.resolve())
                href = rel.as_posix()
            except ValueError:
                href = rel.resolve().as_uri()
        cells.append(_cell_html(item, href))

    html_doc = (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        f'<title>{_e(title)}</title>'
        f"<style>{_CSS_BASE}{_CSS_CONTACT}</style>"
        "</head><body>"
        f'<div class="header">'
        f"<h1>{_e(title)}</h1>"
        f'<div class="meta">{len(visible)} of {len(items)} games · '
        f'{columns} columns</div>'
        f'</div>'
        f'<div class="grid" style="--cols: {int(columns)};">'
        f'{"".join(cells)}'
        f'</div>'
        "</body></html>"
    )
    output_path.write_text(html_doc, encoding="utf-8")
    return output_path


# ─── per-game card (HTML) ─────────────────────────────────────────────────────


def _bg_layer(item: PreviewItem) -> str:
    if item.background is not None:
        return (
            f'<div class="bg" '
            f'style="background-image: url(\'{_e(_file_url(item.background))}\');">'
            f'</div>'
        )
    return '<div class="placeholder-bg">no background</div>'


def _meta_strip(item: PreviewItem) -> str:
    pieces = [f'<span class="name">{_e(item.display_name)}</span>']
    for key in ("year", "manufacturer", "genre"):
        v = item.metadata.get(key) or ""
        if v:
            pieces.append(
                f'<span><span class="label">{_e(key)}:</span>{_e(v)}</span>'
            )
    return f'<div class="meta-strip">{"".join(pieces)}</div>'


def _extras_block(item: PreviewItem) -> str:
    rows: list[str] = []
    if item.theme is not None:
        rows.append(f"<div>theme: {_e(str(item.theme))}</div>")
    if item.video is not None:
        rows.append(f"<div>video: {_e(str(item.video))}</div>")
    if item.artwork is not None:
        rows.append(f"<div>artwork: {_e(str(item.artwork))}</div>")
    if not rows:
        return ""
    return f'<div class="extras">{"".join(rows)}</div>'


def render_game_card_html(
    item: PreviewItem,
    output_path: Path,
    back_href: Optional[str] = None,
) -> Path:
    """Write a single self-contained per-game card.

    ``back_href`` (if given) renders a small "← back" link in the top-left
    corner pointing to the contact sheet.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    layers = [_bg_layer(item)]
    if item.title_img is not None:
        layers.append(
            f'<div class="layer title-img">'
            f'<img src="{_e(_file_url(item.title_img))}" alt=""></div>'
        )
    if item.snap is not None:
        layers.append(
            f'<img class="layer snap" '
            f'src="{_e(_file_url(item.snap))}" alt="">'
        )
    if item.wheel is not None:
        layers.append(
            f'<img class="layer wheel" '
            f'src="{_e(_file_url(item.wheel))}" alt="">'
        )
    layers.append(_extras_block(item))
    layers.append(_meta_strip(item))

    back = (
        f'<a class="back-link" href="{_e(back_href)}">&larr; back</a>'
        if back_href else ""
    )

    html_doc = (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        f'<title>{_e(item.display_name)}</title>'
        f"<style>{_CSS_BASE}{_CSS_CARD}</style>"
        "</head><body>"
        f"{back}"
        f'<div class="card">{"".join(layers)}</div>'
        "</body></html>"
    )
    output_path.write_text(html_doc, encoding="utf-8")
    return output_path


# ─── contact sheet (PNG) ──────────────────────────────────────────────────────


def render_contact_sheet_png(
    items: list[PreviewItem],
    output_path: Path,
    columns: int = 6,
    cell_width: int = 240,
    cell_height: int = 180,
    include_missing: bool = False,
) -> Path:
    """Render a single PNG contact sheet via Pillow.

    Falls back to :func:`render_contact_sheet_html` (writing alongside the
    requested PNG path) and emits a :class:`RuntimeWarning` when Pillow is
    not installed. Returns the path that was actually written.
    """
    output_path = Path(output_path)

    pil_image = _try_import_pillow()
    if pil_image is None:
        warnings.warn(
            "Pillow not installed; falling back to HTML contact sheet. "
            "Install with: pip install -e .[preview]",
            RuntimeWarning,
            stacklevel=2,
        )
        html_target = output_path.with_suffix(".html")
        return render_contact_sheet_html(
            items, html_target,
            columns=columns,
            include_missing=include_missing,
        )

    # Lazy imports — only reached when Pillow is present.
    from PIL import Image, ImageDraw, ImageFont  # type: ignore

    visible = items if include_missing else [i for i in items if i.wheel is not None]
    if not visible:
        # Nothing to render — write a tiny placeholder so callers still get a file.
        Image.new("RGB", (cell_width, cell_height), (26, 26, 34)).save(output_path)
        return output_path

    columns = max(1, int(columns))
    rows = (len(visible) + columns - 1) // columns
    name_height = 28
    pad = 10
    panel_h = cell_height + name_height + pad * 2
    panel_w = cell_width + pad * 2
    canvas_w = panel_w * columns
    canvas_h = panel_h * rows
    canvas = Image.new("RGB", (canvas_w, canvas_h), (26, 26, 34))

    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover - extremely defensive
        font = None

    for idx, item in enumerate(visible):
        col = idx % columns
        row = idx // columns
        ox = col * panel_w
        oy = row * panel_h
        # Cell background.
        cell = Image.new("RGB", (panel_w, panel_h), (35, 35, 48))
        canvas.paste(cell, (ox, oy))

        if item.wheel is not None:
            try:
                # `with` closes the on-disk file handle as soon as we
                # have the in-memory RGBA copy. Without it, large
                # contact sheets (500+ wheels) hold every PNG file open
                # until the Python GC reaps them — exhausts file
                # descriptors on Windows and blocks `migrate` /
                # `backup` operations that try to move the same files
                # in a sibling subprocess.
                with Image.open(item.wheel) as src:
                    wheel_img = src.convert("RGBA")
                wheel_img.thumbnail((cell_width, cell_height))
                wx = ox + pad + (cell_width - wheel_img.width) // 2
                wy = oy + pad + (cell_height - wheel_img.height) // 2
                # Composite onto the canvas using the wheel's alpha.
                canvas.paste(wheel_img, (wx, wy), wheel_img)
            except (OSError, ValueError):
                pass

        draw = ImageDraw.Draw(canvas)
        label = item.display_name
        if len(label) > 32:
            label = label[:31] + "…"
        text_y = oy + pad + cell_height + 4
        text_x = ox + pad
        if font is not None:
            draw.text((text_x, text_y), label, fill=(200, 200, 212), font=font)
        else:
            draw.text((text_x, text_y), label, fill=(200, 200, 212))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return output_path


# ─── orchestration ────────────────────────────────────────────────────────────


_FILENAME_BAD = ("\\", "/", ":", "*", "?", '"', "<", ">", "|")


def _safe_filename(name: str) -> str:
    """Sanitize a game name into a filesystem-friendly stem."""
    out = name
    for ch in _FILENAME_BAD:
        out = out.replace(ch, "_")
    out = out.strip().rstrip(".")
    return out or "_"


def render_system_overview(
    system_name: str,
    items: list[PreviewItem],
    output_dir: Path,
    columns: int = 6,
    include_missing: bool = False,
    formats: tuple[str, ...] = ("html",),
) -> dict:
    """Write a full overview tree under ``output_dir``.

    Outputs:
      * ``<output_dir>/index.html`` — contact sheet linking to each card.
      * ``<output_dir>/games/<game>.html`` — one card per game.
      * ``<output_dir>/index.png`` — only when Pillow is available **and**
        ``"png"`` is in ``formats``.

    Returns ``{"index_html": Path, "cards": list[Path], "index_png": Path|None}``.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    games_dir = output_dir / "games"
    games_dir.mkdir(exist_ok=True)

    index_html = output_dir / "index.html"
    cards: list[Path] = []
    index_png: Optional[Path] = None

    for item in items:
        card_path = games_dir / f"{_safe_filename(item.game_name)}.html"
        render_game_card_html(item, card_path, back_href="../index.html")
        cards.append(card_path)

    # Always write an HTML index — it's the navigation entry point even
    # when the user only asked for PNG.
    render_contact_sheet_html(
        items, index_html,
        columns=columns,
        include_missing=include_missing,
        card_dir=games_dir,
        title=f"{system_name} preview",
    )

    if "png" in formats:
        png_target = output_dir / "index.png"
        result = render_contact_sheet_png(
            items, png_target,
            columns=columns,
            include_missing=include_missing,
        )
        # render_contact_sheet_png falls back to .html when Pillow is missing.
        if result.suffix.lower() == ".png":
            index_png = result

    return {
        "index_html": index_html,
        "cards": cards,
        "index_png": index_png,
    }
