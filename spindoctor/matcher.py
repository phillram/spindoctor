"""Interactive match-selection UI and persistent match cache for SpinDoctor."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from rich import box
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from .scraper import GameMetadata

CACHE_DIR = Path.home() / ".spindoctor" / "match_cache"
_SKIP = "__skip__"

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
        if cached_id == _SKIP:
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
                cache[rom_name] = _SKIP
                save_cache(system_name, cache)
                _console.print(f"  [dim]Skipped {rom_name}[/dim]")
                return None
            idx = max(0, min(n - 1, len(candidates) - 1))

    selected = candidates[idx]
    cache[rom_name] = str(selected.source_id)
    save_cache(system_name, cache)
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
