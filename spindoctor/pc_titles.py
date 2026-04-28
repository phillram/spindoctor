"""Interactive title-confirmation for PC/Windows/Steam game files.

Recursive scans of a games folder produce a *proposed* title per file
(see ``romutils.derive_pc_title``).  Those proposals come from filename
heuristics, so installs with awkward layouts — e.g. a launcher.exe inside
``Bin/Win64/`` — can land on the wrong title.  This module lets the user
review and edit each proposal once, then caches the decision so re-runs
are silent.

Cache file:
    ~/.spindoctor/pc_titles_cache/<system_name>.json

Schema:
    {"<absolute file path>": "<final title>"}     # accepted/edited
    {"<absolute file path>": "__skip__"}          # excluded from the DB
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from rich import box
from rich.console import Console
from rich.table import Table

from .matcher import SKIP_SENTINEL


CACHE_DIR = Path.home() / ".spindoctor" / "pc_titles_cache"

_console = Console()


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
    removed = 0
    if system_name:
        p = _cache_path(system_name)
        if p.exists():
            p.unlink()
            removed = 1
    elif CACHE_DIR.exists():
        for p in CACHE_DIR.glob("*.json"):
            p.unlink()
            removed += 1
    return removed


def _key(path: Path) -> str:
    """Stable cache key for a file path — absolute, OS-style separator."""
    return str(path.resolve())


def review_titles(
    system_name: str,
    proposals: list[tuple[Path, str]],
    *,
    interactive: bool = True,
) -> dict[Path, str]:
    """Confirm/edit the proposed title for each file.

    *proposals* is a list of ``(file_path, proposed_title)`` pairs.

    Returns ``{file_path: final_title}``.  Files the user skips are
    excluded from the result dict (and recorded as a skip in the cache so
    they stay skipped on re-run).
    """
    cache = load_cache(system_name)
    result: dict[Path, str] = {}

    if not proposals:
        return result

    if not interactive:
        # Non-interactive mode just honours any prior cache decisions and
        # accepts the proposal otherwise — no prompts.
        for path, proposed in proposals:
            cached = cache.get(_key(path))
            if cached == SKIP_SENTINEL:
                continue
            result[path] = cached or proposed
        return result

    _print_header(system_name, len(proposals))

    for idx, (path, proposed) in enumerate(proposals, 1):
        key = _key(path)
        cached = cache.get(key)
        if cached == SKIP_SENTINEL:
            _console.print(f"  [dim]· skipped (cached): {path}[/dim]")
            continue
        if cached:
            result[path] = cached
            _console.print(f"  [dim]· {cached} (cached)[/dim]")
            continue

        final = _prompt_one(idx, len(proposals), path, proposed)
        if final is None:
            cache[key] = SKIP_SENTINEL
            save_cache(system_name, cache)
            continue
        cache[key] = final
        save_cache(system_name, cache)
        result[path] = final

    return result


def _print_header(system_name: str, n: int) -> None:
    _console.print()
    _console.print(
        f"[bold]Reviewing {n} title(s) for[/bold] [cyan]{system_name}[/cyan]"
    )
    _console.print(
        "[dim]Enter to accept · type a new title to edit · "
        "[bold]s[/bold] to skip · [bold]Ctrl-C[/bold] to abort[/dim]"
    )


def _prompt_one(
    idx: int,
    total: int,
    path: Path,
    proposed: str,
) -> Optional[str]:
    tbl = Table(box=box.MINIMAL, show_header=False, padding=(0, 1))
    tbl.add_column("k", style="dim")
    tbl.add_column("v")
    tbl.add_row(f"[{idx}/{total}]", str(path))
    tbl.add_row("title", f"[cyan]{proposed}[/cyan]")
    _console.print(tbl)

    try:
        raw = input("  accept [enter] / new title / s skip: ")
    except (EOFError, KeyboardInterrupt):
        _console.print("\n[yellow]Interrupted.[/yellow]")
        raise

    raw = raw.strip()
    if raw == "":
        return proposed
    if raw.lower() == "s":
        _console.print(f"  [dim]Skipped {path.name}[/dim]")
        return None
    return raw
