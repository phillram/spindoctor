"""HyperSpin frontend theme inventory.

Scans the HyperSpin install for "frontend art" — the overlay PNGs that
HyperSpin renders on top of every wheel (Special A / Special B button-
hint glyphs at the bottom of the screen, frontend overlays, etc.).

Concretely walks:

* ``<HyperSpin>/Media/Frontend/Images/`` — universal overlays.
* ``<HyperSpin>/Media/<system>/Images/Special A/`` and ``Special B/`` —
  per-system controller-hint glyphs configured in HyperHQ → Special A/B.

Returns a flat list of :class:`ThemeAsset` records (path / scope /
size / mtime / kind) so callers can render a table, filter by keyword,
or feed the list into :mod:`spindoctor.themes_apply` (a future module).

This is the **read-only** half of the theme tooling — no writes here.
``theme-apply`` (in a separate module) will consume this output and
copy replacement PNGs over the originals with a reversible manifest.

Out of scope: editing embedded glyphs inside ``.swf`` Flash theme
zips. Those need a SWF authoring tool — point users at HyperHQ + a
SWF decompiler instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .config import Config


# Canonical extensions HyperSpin uses for overlay art. Other formats
# (.bmp, .gif) work but aren't community standard — we surface them
# anyway when found, just labeled "image".
_OVERLAY_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}

# Filename keywords commonly found in controller-glyph art. Used by
# the optional --keyword filter (and the GUI's filter box) to narrow
# a multi-thousand-file scan down to "things that probably look like
# controller buttons". Lowercased; substring match.
KNOWN_GLYPH_KEYWORDS: tuple[str, ...] = (
    "xbox", "x360", "xbone", "xbox360",
    "playstation", "ps3", "ps4", "ps5", "ps2", "psx", "dualshock",
    "switch", "joycon", "joy-con",
    "arcade", "button", "stick", "joystick",
    "nintendo", "nes", "snes", "n64",
    "controller", "gamepad", "pad",
    "specialA", "special_a", "specialB", "special_b",
    "hint", "overlay",
)


@dataclass(frozen=True)
class ThemeAsset:
    """One overlay file with everything the scanner / GUI needs to render it.

    ``scope`` distinguishes universal frontend art ("Frontend") from
    per-system Special A/B overlays so the GUI can group by it. ``kind``
    is the lowercased file extension without the dot — used by the
    image-viewer fallback to decide whether to even try opening.
    """
    path: Path
    scope: str          # "Frontend" or system name
    bucket: str         # "Frontend / Images" or "Special A" / "Special B"
    kind: str           # extension sans dot ("png", "swf", …)
    size_bytes: int
    modified: datetime


def _safe_iterdir(d: Path) -> Iterable[Path]:
    """Yield direct children of *d* without raising on missing dirs.

    The scanner walks several optional locations — most cabinets won't
    have every one populated. Bubbling FileNotFoundError up to the
    caller would force them to wrap each call in a try/except, which
    is just noise.
    """
    try:
        yield from d.iterdir()
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return


def _collect_files(directory: Path, scope: str, bucket: str) -> list[ThemeAsset]:
    """Return one :class:`ThemeAsset` per overlay-extension file in *directory*.

    Recursive — many cabinets organise Special A art into per-game
    sub-folders, and we want those too. Skips dotfiles and anything
    without an :data:`_OVERLAY_EXTS` extension.
    """
    out: list[ThemeAsset] = []
    if not directory.exists():
        return out
    for path in directory.rglob("*"):
        if not path.is_file() or path.name.startswith("."):
            continue
        ext = path.suffix.lower()
        if ext not in _OVERLAY_EXTS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append(ThemeAsset(
            path=path,
            scope=scope,
            bucket=bucket,
            kind=ext.lstrip("."),
            size_bytes=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime),
        ))
    return out


def scan_frontend_art(config: Config) -> list[ThemeAsset]:
    """Collect every Frontend / Special A / Special B overlay file.

    Order: Frontend universal art first, then per-system buckets
    sorted by system name. Within a bucket, files come out in
    ``rglob`` order (the OS's directory traversal). Callers that need
    a specific sort apply it themselves — sorting is a display
    concern, not a scanner concern.
    """
    if not config.hyperspin_dir:
        return []
    media = Path(config.hyperspin_dir) / "Media"
    out: list[ThemeAsset] = []

    # Universal frontend art — covers the bottom-of-screen hint
    # graphics on the Main Menu and falls back to per-system overrides
    # when those aren't set.
    out.extend(_collect_files(
        media / "Frontend" / "Images",
        scope="Frontend", bucket="Frontend / Images",
    ))

    # Per-system Special A/B buckets. We list every system folder we
    # see under Media/, not just ones in the Main Menu — extra noise
    # is cheaper than missing a folder the user actually cares about.
    for system_dir in sorted(_safe_iterdir(media)):
        if not system_dir.is_dir() or system_dir.name == "Frontend":
            continue
        for bucket_label in ("Special A", "Special B"):
            out.extend(_collect_files(
                system_dir / "Images" / bucket_label,
                scope=system_dir.name, bucket=bucket_label,
            ))
    return out


def filter_assets(
    assets: Iterable[ThemeAsset],
    *,
    system: Optional[str] = None,
    keyword: Optional[str] = None,
) -> list[ThemeAsset]:
    """Return *assets* narrowed by an optional system + filename keyword.

    *system* matches ``ThemeAsset.scope`` exactly (case-sensitive — the
    on-disk folder names are the source of truth). *keyword* is a
    case-insensitive substring match against the filename, useful for
    "show me everything that might be Xbox glyphs" via ``"xbox"``.
    """
    out = list(assets)
    if system:
        out = [a for a in out if a.scope == system]
    if keyword:
        kw = keyword.lower()
        out = [a for a in out if kw in a.path.name.lower()]
    return out


def has_swf_themes(config: Config) -> bool:
    """Quick heuristic: are any frontend overlays embedded inside SWFs?

    Used by the CLI / GUI to surface a "your glyphs may live inside
    `default.zip` (Flash) — SpinDoctor can't edit those" warning when
    a scan returns no PNG hits. Looks at the Main Menu themes folder
    only; per-system theme zips are a different concern (per-game
    art, not frontend overlays).
    """
    if not config.hyperspin_dir:
        return False
    main_themes = (Path(config.hyperspin_dir) / "Media" / "Main Menu"
                   / "Themes")
    if not main_themes.exists():
        return False
    return any(p.suffix.lower() in {".swf", ".zip"}
               for p in _safe_iterdir(main_themes))
