"""Interactive match-selection UI and persistent match cache for SpinDoctor."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from rich import box
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from .scraper import GameMetadata, MediaCandidate

CACHE_DIR = Path.home() / ".spindoctor" / "match_cache"
MEDIA_CACHE_DIR = Path.home() / ".spindoctor" / "media_pick_cache"
SKIP_SENTINEL = "__skip__"  # stored in cache to record a deliberate skip decision

_console = Console()
_err = Console(stderr=True)


# ─── cache helpers ────────────────────────────────────────────────────────────

def _cache_path(system_name: str) -> Path:
    return CACHE_DIR / f"{system_name}.json"


def load_cache(system_name: str) -> dict[str, str]:
    p = _cache_path(system_name)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_cache(system_name: str, cache: dict[str, str]) -> None:
    p = _cache_path(system_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def clear_cache(system_name: Optional[str] = None) -> int:
    """Delete cached match decisions. Returns count of files removed."""
    removed = 0
    if system_name:
        p = _cache_path(system_name)
        if p.exists():
            p.unlink()
            removed = 1
    else:
        for p in CACHE_DIR.glob("*.json"):
            p.unlink()
            removed += 1
    return removed


def list_cache(system_name: Optional[str] = None) -> dict[str, dict[str, str]]:
    """Return {system: {rom_name: chosen_id}} for all cached decisions."""
    result: dict[str, dict[str, str]] = {}
    paths = [_cache_path(system_name)] if system_name else list(CACHE_DIR.glob("*.json"))
    for p in paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    result[p.stem] = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
    return result


# ─── selection logic ──────────────────────────────────────────────────────────

def choose_match(
    rom_name: str,
    candidates: "list[GameMetadata]",
    system_name: str,
    auto_best: bool = False,
    interactive: bool = True,
) -> "Optional[GameMetadata]":
    """Return the best/chosen GameMetadata for *rom_name*.

    Decision hierarchy:
    1. Cached choice → return that candidate (or None if previously skipped).
    2. Single candidate → return it directly.
    3. auto_best=True → return top candidate without prompting.
    4. interactive=True → show a selection table and prompt the user.
    5. Fallback → return top candidate silently.
    """
    if not candidates:
        return None

    cache = load_cache(system_name)

    if rom_name in cache:
        cached_id = cache[rom_name]
        if cached_id == SKIP_SENTINEL:
            return None
        for c in candidates:
            if str(c.source_id) == cached_id:
                return c
        # Cached ID no longer in result set — fall through to re-prompt

    if len(candidates) == 1:
        return candidates[0]

    if auto_best or not interactive:
        return candidates[0]

    return _prompt(rom_name, candidates, system_name, cache)


def _prompt(
    rom_name: str,
    candidates: "list[GameMetadata]",
    system_name: str,
    cache: dict[str, str],
) -> "Optional[GameMetadata]":
    _console.print()
    tbl = Table(
        title=f"Multiple matches for [yellow]{rom_name}[/yellow]",
        box=box.ROUNDED,
        show_lines=False,
        padding=(0, 1),
    )
    tbl.add_column("#", style="bold dim", width=3)
    tbl.add_column("Title", style="cyan", max_width=45)
    tbl.add_column("Year", width=6)
    tbl.add_column("Publisher", max_width=24)
    tbl.add_column("Conf.", width=6)
    tbl.add_column("Review link", style="dim", max_width=55)

    for i, c in enumerate(candidates, 1):
        score = getattr(c, "match_score", 0.0)
        link = getattr(c, "source_url", "")
        tbl.add_row(
            str(i),
            c.name,
            c.year or "?",
            c.manufacturer or "?",
            f"{score:.0%}" if score else "—",
            link,
        )

    _console.print(tbl)
    _console.print(
        "[dim]Number to select · [bold]0[/bold] to skip · "
        "[bold]Enter[/bold] to accept #1[/dim]"
    )

    try:
        raw = input(f"  Choice for '{rom_name}' [1]: ").strip()
    except (EOFError, KeyboardInterrupt):
        _console.print("\n[yellow]Interrupted.[/yellow]")
        return None

    if not raw:
        idx = 0
    else:
        try:
            n = int(raw)
        except ValueError:
            idx = 0
        else:
            if n == 0:
                cache[rom_name] = SKIP_SENTINEL
                save_cache(system_name, cache)
                _console.print(f"  [dim]Skipped {rom_name}[/dim]")
                return None
            idx = max(0, min(n - 1, len(candidates) - 1))

    selected = candidates[idx]
    cache[rom_name] = str(selected.source_id)
    save_cache(system_name, cache)
    return selected


# ─── media candidate picker ──────────────────────────────────────────────────

def _media_cache_path(system_name: str) -> Path:
    return MEDIA_CACHE_DIR / f"{system_name}.json"


def _load_media_cache(system_name: str) -> dict[str, str]:
    p = _media_cache_path(system_name)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_media_cache(system_name: str, cache: dict[str, str]) -> None:
    p = _media_cache_path(system_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def clear_media_cache(system_name: Optional[str] = None) -> int:
    removed = 0
    if system_name:
        p = _media_cache_path(system_name)
        if p.exists():
            p.unlink()
            removed = 1
    else:
        if MEDIA_CACHE_DIR.exists():
            for p in MEDIA_CACHE_DIR.glob("*.json"):
                p.unlink()
                removed += 1
    return removed


def pick_media(
    item_name: str,
    media_type: str,
    candidates: "list[MediaCandidate]",
    system_name: str,
    *,
    interactive: bool = True,
    previewer: Optional[Callable[["MediaCandidate", int], None]] = None,
) -> "Optional[MediaCandidate]":
    """Pick one media candidate; cache the choice keyed by item+type+url.

    ``item_name`` is the game (or system) name used as the cache key prefix.
    ``previewer`` is an optional callback invoked as ``previewer(candidate, idx)``
    when the user types ``p<N>`` to preview candidate N before picking.

    Returns the chosen MediaCandidate, or ``None`` if the user skipped.
    """
    if not candidates:
        return None

    cache_key = f"{item_name}::{media_type}"
    cache = _load_media_cache(system_name)

    if cache_key in cache:
        cached_url = cache[cache_key]
        if cached_url == SKIP_SENTINEL:
            return None
        for c in candidates:
            if c.url == cached_url:
                return c
        # Cached URL no longer in the result set — fall through to re-prompt

    if len(candidates) == 1 or not interactive:
        return candidates[0]

    return _prompt_media(item_name, media_type, candidates,
                         system_name, cache, previewer)


def _prompt_media(
    item_name: str,
    media_type: str,
    candidates: "list[MediaCandidate]",
    system_name: str,
    cache: dict[str, str],
    previewer: Optional[Callable[["MediaCandidate", int], None]],
) -> "Optional[MediaCandidate]":
    while True:
        _console.print()
        tbl = Table(
            title=f"[yellow]{item_name}[/yellow] · "
                  f"[cyan]{media_type}[/cyan] — "
                  f"{len(candidates)} candidates",
            box=box.ROUNDED, show_lines=False, padding=(0, 1),
        )
        tbl.add_column("#", style="bold dim", width=3)
        tbl.add_column("Region", width=6)
        tbl.add_column("Type", style="cyan", max_width=20)
        tbl.add_column("Format", width=8)
        tbl.add_column("Dims", width=11)
        tbl.add_column("URL", style="dim", no_wrap=False)

        for i, c in enumerate(candidates, 1):
            dims = f"{c.width}×{c.height}" if c.width and c.height else ""
            tbl.add_row(
                str(i),
                (c.region or "—").upper(),
                c.source_type or "",
                c.format or "",
                dims,
                c.url,
            )

        _console.print(tbl)
        hint = (
            "[dim]Number to select · [bold]p<N>[/bold] preview · "
            "[bold]0[/bold] skip · [bold]Enter[/bold] accept #1[/dim]"
            if previewer else
            "[dim]Number to select · [bold]0[/bold] skip · "
            "[bold]Enter[/bold] accept #1[/dim]"
        )
        _console.print(hint)

        try:
            raw = input(f"  Pick {media_type} for '{item_name}' [1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            _console.print("\n[yellow]Interrupted.[/yellow]")
            return None

        if not raw:
            idx = 0
        elif raw.lower().startswith("p") and previewer:
            try:
                n = int(raw[1:])
            except ValueError:
                _console.print("[red]Bad preview index.[/red]")
                continue
            if not 1 <= n <= len(candidates):
                _console.print("[red]Out of range.[/red]")
                continue
            previewer(candidates[n - 1], n - 1)
            continue
        else:
            try:
                n = int(raw)
            except ValueError:
                idx = 0
            else:
                if n == 0:
                    cache[f"{item_name}::{media_type}"] = SKIP_SENTINEL
                    _save_media_cache(system_name, cache)
                    _console.print(f"  [dim]Skipped {media_type} for {item_name}[/dim]")
                    return None
                idx = max(0, min(n - 1, len(candidates) - 1))

        selected = candidates[idx]
        cache[f"{item_name}::{media_type}"] = selected.url
        _save_media_cache(system_name, cache)
        return selected


def partition_by_confidence(
    candidates_map: "dict[str, list[GameMetadata]]",
    auto_threshold: float = 0.90,
) -> "tuple[dict[str, GameMetadata], dict[str, list[GameMetadata]]]":
    """Split candidates into auto-resolved and ambiguous groups.

    Returns:
        auto     — {rom_name: best_candidate} where top score >= auto_threshold
        ambiguous — {rom_name: [candidates]} where human review is preferred
    """
    auto: dict[str, "GameMetadata"] = {}
    ambiguous: dict[str, "list[GameMetadata]"] = {}
    for rom_name, cands in candidates_map.items():
        if not cands:
            continue
        top_score = getattr(cands[0], "match_score", 0.0)
        if top_score >= auto_threshold:
            auto[rom_name] = cands[0]
        else:
            ambiguous[rom_name] = cands
    return auto, ambiguous
