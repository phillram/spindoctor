"""SpinDoctor CLI — Hyperspin arcade library manager."""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from . import __app_name__, __version__
from .audit import GameAuditEntry, SystemAuditResult, audit_system, build_stub_entry
from .config import (
    Config, MEDIA_TYPES, get_systems, load_config, save_config,
)
from .database import load_database

console = Console()
err_console = Console(stderr=True)


# ─── shared helpers ───────────────────────────────────────────────────────────

def _cfg() -> Config:
    return load_config()


def _resolve_systems(config: Config, system: Optional[str], all_systems: bool) -> list[str]:
    if all_systems:
        systems = get_systems(config)
        if not systems:
            err_console.print("[red]No systems found. Check roms_dir and hyperspin_dir.[/red]")
            sys.exit(1)
        return systems
    if system:
        return [system]
    err_console.print("[red]Specify --system NAME or --all.[/red]")
    sys.exit(1)


def _check_config(config: Config) -> None:
    ok, errors = config.is_valid()
    if not ok:
        for e in errors:
            err_console.print(f"[red]Config error:[/red] {e}")
        err_console.print("Run [cyan]spindoctor config set[/cyan] to configure paths.")
        sys.exit(1)


def _status(value: bool) -> str:
    return "[green]✓[/green]" if value else "[red]✗[/red]"


def _auto_export_audit(config: Config, systems: list[str]) -> None:
    """If auto_audit_export_dir is configured, write an audit CSV there."""
    if not config.auto_audit_export_dir:
        return
    export_dir = Path(config.auto_audit_export_dir)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = export_dir / f"audit_{stamp}.csv"
    results = [audit_system(s, config, check_media_flag=True) for s in systems]
    _write_audit_csv(results, report_path)
    console.print(f"\n[dim]Auto-audit export:[/dim] {report_path}")


# ─── root command ─────────────────────────────────────────────────────────────

@click.group()
@click.version_option(__version__, prog_name=__app_name__)
def cli():
    """SpinDoctor — Hyperspin arcade library manager.

    Audit ROMs, sync databases, fetch metadata & media, and generate
    RocketLauncher / RocketUI config files for your arcade cabinet.
    """


# ─── config ───────────────────────────────────────────────────────────────────

@cli.group("config")
def config_group():
    """Show or update SpinDoctor configuration."""


@config_group.command("show")
def config_show():
    """Display current configuration."""
    config = _cfg()
    tbl = Table(title="SpinDoctor Configuration", box=box.ROUNDED)
    tbl.add_column("Key", style="cyan")
    tbl.add_column("Value")

    sensitive = {"screenscraper_pass", "thegamesdb_key"}
    for key, val in config.to_dict().items():
        if key == "ignore_lists":
            n = sum(len(v) for v in val.values())
            tbl.add_row(key, f"[dim]{n} entries across {len(val)} system(s)[/dim]")
            continue
        display = "***" if key in sensitive and val else (str(val) or "[dim]<not set>[/dim]")
        tbl.add_row(key, display)
    console.print(tbl)


@config_group.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Set a configuration value.

    \b
    Keys:
      roms_dir                  Directory containing one sub-folder per system
      hyperspin_dir             Root HyperSpin folder (has Databases/ and Media/)
      emulators_dir             Emulator root directory
      rocketlauncher_dir        RocketLauncher root directory
      output_dir                Default output directory (blank = write in-place)
      auto_audit_export_dir     Auto-export audit CSV here after write operations
      screenscraper_user        ScreenScraper username
      screenscraper_pass        ScreenScraper password
      thegamesdb_key            TheGamesDB API key
      default_metadata_source   screenscraper | thegamesdb
      backup_before_modify      true | false
      match_threshold           0.0–1.0 fuzzy match confidence (default 0.80)
      interactive_matching      true | false
      max_concurrent_downloads  Integer
      strip_variant_tags_in_display_name
                                true | false (default false; when true,
                                strips '(Japan)' / '(Rev A)' tags from
                                stub display names)
    """
    config = _cfg()
    if not hasattr(config, key) or key in ("ignore_lists", "databases_dir", "media_dir"):
        err_console.print(f"[red]Unknown config key:[/red] {key}")
        sys.exit(1)
    current = getattr(config, key)
    if isinstance(current, bool):
        setattr(config, key, value.lower() in ("1", "true", "yes"))
    elif isinstance(current, int):
        setattr(config, key, int(value))
    elif isinstance(current, float):
        setattr(config, key, float(value))
    else:
        setattr(config, key, value)
    save_config(config)
    console.print(f"[green]✓[/green] Set [cyan]{key}[/cyan] = {value!r}")


# ─── systems ──────────────────────────────────────────────────────────────────

@cli.command("systems")
def list_systems():
    """List all detected systems."""
    config = _cfg()
    _check_config(config)
    systems = get_systems(config)
    if not systems:
        console.print("[yellow]No systems found.[/yellow]")
        return
    tbl = Table(title="Detected Systems", box=box.ROUNDED)
    tbl.add_column("#", style="dim")
    tbl.add_column("System", style="cyan")
    tbl.add_column("ROMs", justify="center")
    tbl.add_column("Database", justify="center")
    tbl.add_column("Ignored", justify="right", style="dim")
    for i, sys_name in enumerate(systems, 1):
        has_roms = (Path(config.roms_dir) / sys_name).exists()
        db_dir = config.databases_dir / sys_name
        has_db = bool(list(db_dir.glob("*.xml"))) if db_dir.exists() else False
        ignored = len(config.ignore_lists.get(sys_name, []))
        tbl.add_row(str(i), sys_name, _status(has_roms), _status(has_db),
                    str(ignored) if ignored else "—")
    console.print(tbl)


# ─── audit ────────────────────────────────────────────────────────────────────

@cli.command("audit")
@click.option("--system", "-s", default=None)
@click.option("--all", "all_systems", is_flag=True)
@click.option("--no-media", is_flag=True, help="Skip media checks (faster).")
@click.option("--no-fuzzy", is_flag=True, help="Skip fuzzy ROM/DB matching.")
@click.option("--detailed", is_flag=True,
              help="Show per-file details (size, dimensions, video length) "
                   "for every game that needs attention.")
@click.option("--report", "-r", type=click.Path(), default=None,
              help="Write CSV report to this path.")
@click.option("--show-matched", is_flag=True)
def audit(system, all_systems, no_media, no_fuzzy, detailed, report, show_matched):
    """Audit ROM files against the Hyperspin database and media assets.

    Reports ROMs missing from the database, orphan DB entries, incomplete
    metadata, missing media, fuzzy-matched variants, and ignored games.

    Add --detailed to append a per-file breakdown (path, size, dimensions,
    video length) for every game that needs attention.
    """
    config = _cfg()
    _check_config(config)
    systems = _resolve_systems(config, system, all_systems)

    all_results: list[SystemAuditResult] = []
    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  BarColumn(), TimeElapsedColumn(), console=console) as prog:
        task = prog.add_task("Auditing...", total=len(systems))
        for sys_name in systems:
            prog.update(task, description=f"Auditing [cyan]{sys_name}[/cyan]...")
            all_results.append(
                audit_system(sys_name, config,
                             check_media_flag=not no_media,
                             fuzzy=not no_fuzzy)
            )
            prog.advance(task)

    for result in all_results:
        _print_audit_result(result, show_matched)

    if detailed:
        _print_detailed_section(all_results, config)

    if report:
        _write_audit_csv(all_results, Path(report))
        console.print(f"\n[green]Report saved:[/green] {report}")
    else:
        _auto_export_audit(config, systems)


def _print_audit_result(result: SystemAuditResult, show_matched: bool) -> None:
    console.print(Panel(f" {result.system_name} ", style="bold blue"))

    grid = Table.grid(padding=(0, 2))
    grid.add_row("[cyan]Total ROMs:[/cyan]", str(result.total_roms))
    grid.add_row("[cyan]Total DB entries:[/cyan]", str(result.total_db_entries))
    grid.add_row("[green]Exact matches:[/green]", str(result.roms_in_db))
    grid.add_row("[yellow]ROMs not in DB:[/yellow]", str(result.roms_not_in_db))
    grid.add_row("[blue]Fuzzy matches (ROM↔DB variants):[/blue]", str(len(result.fuzzy_matches)))
    grid.add_row("[red]DB entries with no ROM:[/red]", str(result.db_entries_no_rom))
    grid.add_row("[magenta]Incomplete metadata:[/magenta]", str(len(result.missing_metadata_entries)))
    grid.add_row("[magenta]Missing media:[/magenta]", str(len(result.missing_media_entries)))
    grid.add_row("[dim]Ignored:[/dim]", str(result.ignored_count))
    console.print(grid)

    if result.fuzzy_matches:
        console.print("\n[blue bold]Fuzzy-matched ROM variants:[/blue bold]")
        tbl = Table(box=box.SIMPLE, show_header=True)
        tbl.add_column("ROM file", style="yellow")
        tbl.add_column("DB entry", style="cyan")
        tbl.add_column("Conf.", width=6)
        tbl.add_column("DB description", style="dim")
        for f in result.fuzzy_matches[:30]:
            desc = f.db_entry.description if f.db_entry else ""
            tbl.add_row(f.rom_name, f.db_name, f"{f.score:.0%}", desc)
        if len(result.fuzzy_matches) > 30:
            console.print(f"  [dim]... and {len(result.fuzzy_matches) - 30} more[/dim]")
        console.print(tbl)

    if result.roms_only:
        console.print("\n[yellow bold]ROMs not in database:[/yellow bold]")
        for e in result.roms_only[:50]:
            console.print(f"  [yellow]•[/yellow] {e.rom_name}")
        if len(result.roms_only) > 50:
            console.print(f"  [dim]... and {len(result.roms_only) - 50} more[/dim]")

    if result.db_only:
        console.print("\n[red bold]DB entries with no ROM:[/red bold]")
        for e in result.db_only[:50]:
            desc = e.db_entry.description if e.db_entry else ""
            label = f" ({desc})" if desc and desc != e.rom_name else ""
            console.print(f"  [red]•[/red] {e.rom_name}{label}")
        if len(result.db_only) > 50:
            console.print(f"  [dim]... and {len(result.db_only) - 50} more[/dim]")

    if result.missing_metadata_entries:
        console.print("\n[magenta bold]Incomplete metadata:[/magenta bold]")
        tbl = Table(box=box.SIMPLE)
        tbl.add_column("Game")
        tbl.add_column("Missing")
        for e in result.missing_metadata_entries[:30]:
            tbl.add_row(e.rom_name, ", ".join(e.missing_metadata))
        console.print(tbl)
        if len(result.missing_metadata_entries) > 30:
            console.print(f"  [dim]... and {len(result.missing_metadata_entries) - 30} more[/dim]")

    if show_matched and result.matched:
        console.print(f"\n[green]Matched games:[/green] {len(result.matched)}")


def _write_audit_csv(results: list[SystemAuditResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "system", "rom_name", "in_database", "rom_exists", "ignored",
            "fuzzy_match_to", "fuzzy_score",
            "missing_metadata", "missing_media",
        ] + MEDIA_TYPES)
        fuzzy_by_rom: dict[tuple, tuple] = {}
        for result in results:
            for fm in result.fuzzy_matches:
                fuzzy_by_rom[(result.system_name, fm.rom_name)] = (fm.db_name, f"{fm.score:.2f}")
        for result in results:
            for entry in result.entries:
                fm_info = fuzzy_by_rom.get((result.system_name, entry.rom_name), ("", ""))
                writer.writerow([
                    result.system_name,
                    entry.rom_name,
                    entry.in_database,
                    entry.rom_exists,
                    entry.ignored,
                    fm_info[0],
                    fm_info[1],
                    ";".join(entry.missing_metadata),
                    ";".join(entry.media.missing()),
                ] + [str(getattr(entry.media, t, False)) for t in MEDIA_TYPES])


# ─── detailed file display helpers ───────────────────────────────────────────

def _print_game_detail(report, *, verbose_path: bool = True) -> None:
    """Print a rich per-game file-detail panel to the console."""
    from .fileinfo import GameFileReport

    # ── DB info header ────────────────────────────────────────────────────────
    db_lines: list[str] = []
    if report.db_description:
        db_lines.append(f"[bold]{report.db_description}[/bold]")
    meta_parts = []
    if report.db_year:
        meta_parts.append(f"Year [cyan]{report.db_year}[/cyan]")
    if report.db_manufacturer:
        meta_parts.append(f"Publisher [cyan]{report.db_manufacturer}[/cyan]")
    if report.db_genre:
        meta_parts.append(f"Genre [cyan]{report.db_genre}[/cyan]")
    if report.db_rating:
        meta_parts.append(f"Rating [cyan]{report.db_rating}[/cyan]")
    if meta_parts:
        db_lines.append("  ·  ".join(meta_parts))
    db_lines.append(
        f"Total on-disk: [green]{report.total_size_human}[/green]  ·  "
        f"Media present: [green]{len(report.present_media())}[/green]/"
        f"{len(report.media)}  ·  "
        f"Missing: [red]{len(report.missing_media())}[/red]"
    )

    header = "\n".join(db_lines) if db_lines else "(no DB entry)"
    console.print(Panel(header, title=f"[bold cyan]{report.game_name}[/bold cyan]  "
                                      f"[dim]{report.system_name}[/dim]",
                        border_style="blue", padding=(0, 1)))

    # ── ROM file ──────────────────────────────────────────────────────────────
    rom = report.rom
    rom_tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    rom_tbl.add_column("", width=3)
    rom_tbl.add_column("File", style="cyan")
    rom_tbl.add_column("Size", justify="right")
    rom_tbl.add_column("Ext", style="dim")
    rom_tbl.add_column("Modified", style="dim")
    rom_tbl.add_column("Path", style="dim", no_wrap=False)

    if rom and rom.exists:
        path_str = str(rom.path) if verbose_path else rom.path.name
        rom_tbl.add_row("[green]✓[/green]", rom.path.name, rom.size_human,
                        rom.extension, rom.modified_str, path_str)
    else:
        expected = str(rom.path) if rom else "—"
        rom_tbl.add_row("[red]✗[/red]", "[dim]not found[/dim]", "—", "—", "—",
                        f"[dim]{expected}[/dim]")

    console.print("[bold]ROM[/bold]")
    console.print(rom_tbl)

    # ── media files ───────────────────────────────────────────────────────────
    media_tbl = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    media_tbl.add_column("Type", style="cyan", width=12)
    media_tbl.add_column("", width=3)
    media_tbl.add_column("Size", justify="right", width=10)
    media_tbl.add_column("Dim / Length", width=16)
    media_tbl.add_column("Ext", style="dim", width=6)
    media_tbl.add_column("Modified", style="dim", width=17)
    media_tbl.add_column("Path", style="dim", no_wrap=False)

    for mt in MEDIA_TYPES:
        detail = report.media.get(mt)
        if detail and detail.exists:
            path_str = str(detail.path) if verbose_path else detail.path.name
            media_tbl.add_row(
                mt,
                "[green]✓[/green]",
                detail.size_human,
                detail.detail_str,
                detail.extension,
                detail.modified_str,
                path_str,
            )
        else:
            expected = str(detail.path) if detail else "—"
            media_tbl.add_row(
                mt,
                "[red]✗[/red]",
                "—", "—", "—", "—",
                f"[dim]{expected}[/dim]",
            )

    console.print("[bold]MEDIA[/bold]")
    console.print(media_tbl)


def _print_detailed_section(
    all_results: "list[SystemAuditResult]",
    config: Config,
) -> None:
    """Print per-file detail for all games that need attention."""
    from .fileinfo import scan_game

    needs_attention = [
        (result.system_name, entry)
        for result in all_results
        for entry in result.entries
        if entry.needs_attention
    ]

    if not needs_attention:
        console.print("\n[green]No games need attention.[/green]")
        return

    console.print(
        f"\n[bold]Detailed file report[/bold] — "
        f"[cyan]{len(needs_attention)}[/cyan] game(s) needing attention\n"
    )

    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  BarColumn(), console=console) as prog:
        task = prog.add_task("Scanning files...", total=len(needs_attention))
        reports = []
        for sys_name, entry in needs_attention:
            prog.update(task, description=f"[dim]{entry.rom_name[:40]}[/dim]")
            report = scan_game(
                entry.rom_name,
                sys_name,
                Path(config.roms_dir),
                config.media_dir,
                db_entry=entry.db_entry,
            )
            reports.append(report)
            prog.advance(task)

    for report in reports:
        _print_game_detail(report)
        console.print()


# ─── inspect ──────────────────────────────────────────────────────────────────

@cli.command("inspect")
@click.option("--system", "-s", required=True, help="System to inspect.")
@click.option("--game", "-g", default=None,
              help="Single game (ROM stem) to inspect.")
@click.option("--all", "all_games", is_flag=True,
              help="Inspect every game in the system.")
@click.option("--format", "fmt", default="table",
              type=click.Choice(["table", "csv"]),
              help="Output format.")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write CSV output to this file.")
@click.option("--no-path", is_flag=True,
              help="Show only filenames rather than full paths (less wide).")
def inspect(system, game, all_games, fmt, output, no_path):
    """Show detailed per-file information for one game or a whole system.

    \b
    For every game, shows:
      ROM    — path, file size, extension, last modified
      MEDIA  — per type: exists, size, image dimensions, video length,
               extension, last modified, full path

    \b
    Examples:
      # Single game deep-dive
      spindoctor inspect --system MAME --game 1942

      # All games missing something in SNES
      spindoctor inspect --system SNES --needs-attention

      # Export full file manifest to CSV
      spindoctor inspect --system MAME --all --format csv --output D:\\mame_files.csv
    """
    config = _cfg()
    _check_config(config)

    from .fileinfo import scan_game, scan_system

    db = load_database(system, config.databases_dir)
    db_games = db.games()

    # Determine which games to inspect
    if game:
        game_names = [game]
    elif all_games:
        game_names = sorted(db_games.keys())
    else:
        # needs-attention: run a quick audit, pick games with issues
        result = audit_system(system, config, check_media_flag=True)
        game_names = [e.rom_name for e in result.entries if e.needs_attention]
        if not game_names:
            console.print("[green]No games need attention in this system.[/green]")
            return

    if not game_names:
        console.print("[yellow]No games to inspect.[/yellow]")
        return

    console.print(
        f"Scanning [cyan]{len(game_names)}[/cyan] game(s) in "
        f"[bold]{system}[/bold]…"
    )

    reports = []
    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  BarColumn(), TextColumn("{task.completed}/{task.total}"),
                  console=console) as prog:
        task = prog.add_task("Reading files...", total=len(game_names))
        for name in game_names:
            prog.update(task, description=f"[dim]{name[:45]}[/dim]")
            reports.append(
                scan_game(
                    name, system,
                    Path(config.roms_dir),
                    config.media_dir,
                    db_entry=db_games.get(name),
                )
            )
            prog.advance(task)

    if fmt == "csv":
        path = Path(output) if output else None
        _write_inspect_csv(reports, path)
        if path:
            console.print(f"[green]Saved:[/green] {path}")
        return

    # Table output
    for report in reports:
        _print_game_detail(report, verbose_path=not no_path)
        console.print()

    # Footer summary
    total_rom = sum(1 for r in reports if r.rom and r.rom.exists)
    total_size = sum(r.total_size_bytes for r in reports)
    from .fileinfo import human_size
    size_str = human_size(total_size)
    missing_counts: dict[str, int] = {mt: 0 for mt in MEDIA_TYPES}
    for r in reports:
        for mt in r.missing_media():
            missing_counts[mt] += 1

    summary_tbl = Table(title="Inspect Summary", box=box.ROUNDED)
    summary_tbl.add_column("Stat", style="cyan")
    summary_tbl.add_column("Value", justify="right")
    summary_tbl.add_row("Games inspected", str(len(reports)))
    summary_tbl.add_row("ROMs on disk", str(total_rom))
    summary_tbl.add_row("Total on-disk size", size_str)
    for mt, n in missing_counts.items():
        if n:
            summary_tbl.add_row(f"Missing {mt}", f"[red]{n}[/red]")
    console.print(summary_tbl)


def _write_inspect_csv(reports, path) -> None:
    """Write a detailed per-file CSV from a list of GameFileReport objects."""
    rows = []
    for r in reports:
        base = {
            "system": r.system_name,
            "game": r.game_name,
            "db_name": r.db_name,
            "db_description": r.db_description,
            "db_year": r.db_year,
            "db_manufacturer": r.db_manufacturer,
            "db_genre": r.db_genre,
            "db_rating": r.db_rating,
        }
        # ROM row
        rom = r.rom
        rows.append({
            **base,
            "file_category": "rom",
            "media_type": "rom",
            "exists": rom.exists if rom else False,
            "path": str(rom.path) if rom else "",
            "filename": rom.path.name if rom else "",
            "extension": rom.extension if rom else "",
            "size_bytes": rom.size_bytes if rom and rom.exists else "",
            "size_human": rom.size_human if rom and rom.exists else "",
            "width": "",
            "height": "",
            "dimensions": "",
            "duration_seconds": "",
            "duration_human": "",
            "modified": rom.modified_str if rom else "",
        })
        # Media rows
        for mt in MEDIA_TYPES:
            d = r.media.get(mt)
            rows.append({
                **base,
                "file_category": "media",
                "media_type": mt,
                "exists": d.exists if d else False,
                "path": str(d.path) if d else "",
                "filename": d.path.name if d else "",
                "extension": d.extension if d else "",
                "size_bytes": d.size_bytes if d and d.exists else "",
                "size_human": d.size_human if d and d.exists else "",
                "width": d.width if d and d.width else "",
                "height": d.height if d and d.height else "",
                "dimensions": d.dimensions if d and d.exists else "",
                "duration_seconds": (
                    f"{d.duration_seconds:.2f}"
                    if d and d.duration_seconds is not None else ""
                ),
                "duration_human": d.duration_human if d and d.exists else "",
                "modified": d.modified_str if d and d.exists else "",
            })

    columns = [
        "system", "game", "db_name", "db_year", "db_manufacturer",
        "db_genre", "db_rating", "file_category", "media_type", "exists",
        "filename", "extension", "size_bytes", "size_human",
        "width", "height", "dimensions",
        "duration_seconds", "duration_human",
        "modified", "path",
    ]

    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    else:
        # Print CSV to stdout
        import io
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        console.print(buf.getvalue())


# ─── ignore ───────────────────────────────────────────────────────────────────

@cli.group("ignore")
def ignore_group():
    """Manage per-system and global ignore lists.

    Ignored games are skipped by audit, fetch-meta, fetch-media, and update-db.
    """


@ignore_group.command("add")
@click.argument("game_name")
@click.option("--system", "-s", default="_global",
              help="System name, or _global for all systems (default: _global).")
def ignore_add(game_name: str, system: str):
    """Add a game to the ignore list."""
    config = _cfg()
    config.add_ignore(game_name, system)
    save_config(config)
    label = "globally" if system == "_global" else f"for [cyan]{system}[/cyan]"
    console.print(f"[green]✓[/green] Ignoring [yellow]{game_name}[/yellow] {label}.")


@ignore_group.command("remove")
@click.argument("game_name")
@click.option("--system", "-s", default="_global")
def ignore_remove(game_name: str, system: str):
    """Remove a game from the ignore list."""
    config = _cfg()
    if config.remove_ignore(game_name, system):
        save_config(config)
        console.print(f"[green]✓[/green] Removed [yellow]{game_name}[/yellow] from ignore list.")
    else:
        console.print(f"[yellow]{game_name}[/yellow] not found in ignore list for {system}.")


@ignore_group.command("list")
@click.option("--system", "-s", default=None, help="Filter by system.")
def ignore_list(system: Optional[str]):
    """List all ignored games."""
    config = _cfg()
    lists = config.ignore_lists

    if not lists:
        console.print("[dim]No games are currently ignored.[/dim]")
        return

    tbl = Table(title="Ignored Games", box=box.ROUNDED)
    tbl.add_column("System")
    tbl.add_column("Game name", style="yellow")

    for sys_name, games in sorted(lists.items()):
        if system and sys_name != system:
            continue
        for g in sorted(games):
            label = "[dim]global[/dim]" if sys_name == "_global" else sys_name
            tbl.add_row(label, g)

    console.print(tbl)


@ignore_group.command("clear")
@click.option("--system", "-s", default=None, help="Clear only this system's list.")
@click.confirmation_option(prompt="Clear all ignore entries?")
def ignore_clear(system: Optional[str]):
    """Clear ignore list entries."""
    config = _cfg()
    if system:
        config.ignore_lists.pop(system, None)
        console.print(f"[green]✓[/green] Cleared ignore list for {system}.")
    else:
        config.ignore_lists.clear()
        console.print("[green]✓[/green] All ignore lists cleared.")
    save_config(config)


# ─── match ────────────────────────────────────────────────────────────────────

@cli.group("match")
def match_group():
    """Manage cached metadata match decisions."""


@match_group.command("list")
@click.option("--system", "-s", default=None)
def match_list(system: Optional[str]):
    """Show cached match selections."""
    from .matcher import list_cache, SKIP_SENTINEL
    cached = list_cache(system)
    if not cached:
        console.print("[dim]No cached match decisions.[/dim]")
        return
    tbl = Table(title="Cached Match Decisions", box=box.ROUNDED)
    tbl.add_column("System")
    tbl.add_column("ROM name", style="yellow")
    tbl.add_column("Chosen ID / Action", style="cyan")
    for sys_name, entries in sorted(cached.items()):
        for rom_name, chosen in sorted(entries.items()):
            action = "[dim]skip[/dim]" if chosen == SKIP_SENTINEL else chosen
            tbl.add_row(sys_name, rom_name, action)
    console.print(tbl)


@match_group.command("clear")
@click.option("--system", "-s", default=None, help="Clear only this system.")
@click.confirmation_option(prompt="Clear cached match decisions?")
def match_clear(system: Optional[str]):
    """Delete cached match selections so games are re-evaluated."""
    from .matcher import clear_cache
    n = clear_cache(system)
    console.print(f"[green]✓[/green] Cleared {n} cache file(s).")


# ─── fetch-meta ───────────────────────────────────────────────────────────────

@cli.command("fetch-meta")
@click.option("--system", "-s", default=None)
@click.option("--all", "all_systems", is_flag=True)
@click.option("--source", default=None, type=click.Choice(["screenscraper", "thegamesdb"]))
@click.option("--all-games", "fetch_all", is_flag=True,
              help="Refresh metadata for every game, even complete ones.")
@click.option("--interactive/--auto-best", "interactive", default=None,
              help="Prompt when multiple matches exist (default: from config).")
@click.option("--threshold", default=None, type=float,
              help="Fuzzy confidence required for auto-accept (default: from config).")
@click.option("--dry-run", is_flag=True)
@click.option("--output-dir", type=click.Path(), default=None)
def fetch_meta(system, all_systems, source, fetch_all,
               interactive, threshold, dry_run, output_dir):
    """Fetch and update game metadata in the Hyperspin XML databases.

    For each game with missing fields, SpinDoctor queries the metadata source.
    When a ROM name contains variant tags (region, version, revision) those are
    normalised before searching so each ROM variant is looked up individually.
    If multiple candidates are found you can select the correct one interactively;
    your choice is saved to ~/.spindoctor/match_cache/ and reused on future runs.
    """
    config = _cfg()
    _check_config(config)
    systems = _resolve_systems(config, system, all_systems)

    from .matcher import choose_match, partition_by_confidence
    from .scraper import MetadataError, build_client

    do_interactive = config.interactive_matching if interactive is None else interactive
    match_thresh = threshold if threshold is not None else config.match_threshold

    try:
        client = build_client(config, source)
    except MetadataError as e:
        err_console.print(f"[red]{e}[/red]")
        sys.exit(1)

    out_base = Path(output_dir) if output_dir else None
    if dry_run:
        console.print("[yellow bold][DRY RUN][/yellow bold] No files will be written.")

    for sys_name in systems:
        console.print(f"\n[blue bold]{sys_name}[/blue bold]")
        db = load_database(sys_name, config.databases_dir)

        if fetch_all:
            targets = [g for g in db.games().values()
                       if not config.is_ignored(g.name, sys_name)]
        else:
            targets = [g for g in db.iter_incomplete()
                       if not config.is_ignored(g.name, sys_name)]

        if not targets:
            console.print("  [green]All metadata complete (or all ignored).[/green]")
            continue

        console.print(f"  Looking up metadata for [cyan]{len(targets)}[/cyan] games…")

        # ── Phase 1: collect all candidates ──────────────────────────────────
        candidates_map: dict[str, list] = {}
        fetch_errors: list[str] = []

        with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                      BarColumn(), TextColumn("{task.completed}/{task.total}"),
                      console=console) as prog:
            task = prog.add_task("Searching…", total=len(targets))
            for game in targets:
                prog.update(task, description=f"[dim]{game.name[:40]}[/dim]")
                try:
                    cands = client.fetch_with_search(game.name, sys_name,
                                                     threshold=match_thresh)
                    if cands:
                        candidates_map[game.name] = cands
                    else:
                        fetch_errors.append(game.name)
                except MetadataError as e:
                    fetch_errors.append(game.name)
                    console.print(f"  [red]Error [{game.name}]:[/red] {e}")
                prog.advance(task)

        # ── Phase 2: resolve ambiguous matches ────────────────────────────────
        auto_resolved, ambiguous = partition_by_confidence(
            candidates_map, auto_threshold=match_thresh
        )

        if ambiguous and do_interactive:
            console.print(
                f"\n[yellow]{len(ambiguous)}[/yellow] game(s) need manual selection "
                f"(confidence < {match_thresh:.0%}):"
            )
            for rom_name, cands in ambiguous.items():
                chosen = choose_match(rom_name, cands, sys_name,
                                      auto_best=False, interactive=True)
                if chosen:
                    auto_resolved[rom_name] = chosen
        elif ambiguous:
            # Non-interactive: auto-pick best candidate
            for rom_name, cands in ambiguous.items():
                if cands:
                    auto_resolved[rom_name] = cands[0]

        # ── Phase 3: apply updates ────────────────────────────────────────────
        updated = 0
        for game in targets:
            meta = auto_resolved.get(game.name)
            if not meta:
                continue
            if dry_run:
                console.print(
                    f"  [dim]+[/dim] {game.name} → {meta.name!r} "
                    f"({meta.year}, {meta.manufacturer})"
                )
            else:
                if not game.description:
                    game.description = meta.name or game.name
                if meta.manufacturer:
                    game.manufacturer = meta.manufacturer
                if meta.year:
                    game.year = meta.year
                if meta.genre:
                    game.genre = meta.genre
                if meta.rating:
                    game.rating = meta.rating
                db.update_game(game)
            updated += 1

        console.print(
            f"  Updated: [green]{updated}[/green]  "
            f"Ambiguous: [yellow]{len(ambiguous)}[/yellow]  "
            f"Not found: [red]{len(fetch_errors)}[/red]"
        )

        if not dry_run and updated > 0:
            if out_base:
                saved = db.save(
                    output_path=out_base / "Databases" / sys_name / f"{sys_name}.xml",
                    backup=False,
                )
            else:
                saved = db.save(backup=config.backup_before_modify)
            console.print(f"  [green]Saved:[/green] {saved}")

    _auto_export_audit(config, systems)


# ─── fetch-media ──────────────────────────────────────────────────────────────

@cli.command("fetch-media")
@click.option("--system", "-s", default=None)
@click.option("--all", "all_systems", is_flag=True)
@click.option("--types", default=",".join(MEDIA_TYPES),
              help=f"Comma-separated types. Options: {', '.join(MEDIA_TYPES)}")
@click.option("--source", default=None, type=click.Choice(["screenscraper", "thegamesdb"]))
@click.option("--overwrite", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("--output-dir", type=click.Path(), default=None)
def fetch_media(system, all_systems, types, source, overwrite, dry_run, output_dir):
    """Download media assets for games in the database.

    Only downloads media that is missing unless --overwrite is passed.
    Media types: wheel, background, artwork, title, snap, video, trailer, sound, theme.
    """
    config = _cfg()
    _check_config(config)
    systems = _resolve_systems(config, system, all_systems)

    from .audit import check_media
    from .media import MediaDownloader
    from .scraper import MetadataError, build_client

    media_types = [t.strip() for t in types.split(",") if t.strip() in MEDIA_TYPES]
    if not media_types:
        err_console.print(
            f"[red]No valid types. Choose from:[/red] {', '.join(MEDIA_TYPES)}"
        )
        sys.exit(1)

    try:
        client = build_client(config, source)
    except MetadataError as e:
        err_console.print(f"[red]{e}[/red]")
        sys.exit(1)

    out_path = Path(output_dir) if output_dir else None
    downloader = MediaDownloader(config, output_dir_override=out_path)

    if dry_run:
        console.print("[yellow bold][DRY RUN][/yellow bold] No files will be written.")

    for sys_name in systems:
        console.print(f"\n[blue bold]{sys_name}[/blue bold]")
        db = load_database(sys_name, config.databases_dir)
        games = [
            g for g in db.games().values()
            if not config.is_ignored(g.name, sys_name)
        ]
        if not games:
            console.print("  [yellow]No games in database (or all ignored).[/yellow]")
            continue

        if not overwrite:
            media_base = downloader._media_base()
            games = [
                g for g in games
                if check_media(g.name, sys_name, media_base).missing()
            ]
        if not games:
            console.print("  [green]All media present.[/green]")
            continue

        console.print(
            f"  Processing [cyan]{len(games)}[/cyan] games · "
            f"types: {', '.join(media_types)}"
        )

        total_ok = total_skip = total_fail = 0
        with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                      BarColumn(), TextColumn("{task.completed}/{task.total}"),
                      console=console) as prog:
            task = prog.add_task("", total=len(games))
            for game in games:
                prog.update(task, description=f"[dim]{game.name[:40]}[/dim]")
                try:
                    meta = client.fetch_with_search(game.name, sys_name)
                    chosen = meta[0] if meta else None
                    if chosen:
                        results = downloader.download_from_metadata(
                            game.name, sys_name, chosen,
                            media_types=media_types,
                            overwrite=overwrite,
                            dry_run=dry_run,
                        )
                        for r in results:
                            if r.skipped:
                                total_skip += 1
                            elif r.success:
                                total_ok += 1
                            else:
                                total_fail += 1
                    else:
                        total_fail += len(media_types)
                except MetadataError as e:
                    console.print(f"  [red]Error [{game.name}]:[/red] {e}")
                    total_fail += len(media_types)
                prog.advance(task)

        console.print(
            f"  Downloaded: [green]{total_ok}[/green]  "
            f"Skipped: [dim]{total_skip}[/dim]  "
            f"Failed: [red]{total_fail}[/red]"
        )

    _auto_export_audit(config, systems)


# ─── media add ────────────────────────────────────────────────────────────────

@cli.command("media-add")
@click.option("--system", "-s", required=True, help="System name.")
@click.option("--game", "-g", required=True, help="ROM/game name (no extension).")
@click.option("--type", "media_type", required=True,
              type=click.Choice(MEDIA_TYPES), help="Media type.")
@click.option("--file", "source_file", required=True, type=click.Path(exists=True),
              help="Local file to add.")
@click.option("--move", is_flag=True, help="Move instead of copy.")
@click.option("--overwrite", is_flag=True)
@click.option("--output-dir", type=click.Path(), default=None)
def media_add(system, game, media_type, source_file, move, overwrite, output_dir):
    """Manually add a local media file for a specific game.

    Copies (or moves) the file into the correct HyperSpin Media directory.

    \b
    Example:
      spindoctor media-add --system MAME --game 1942 --type trailer \\
          --file C:\\Downloads\\1942_trailer.mp4
    """
    config = _cfg()
    _check_config(config)

    from .media import MediaDownloader
    out_path = Path(output_dir) if output_dir else None
    downloader = MediaDownloader(config, output_dir_override=out_path)
    result = downloader.add_local_file(
        source_path=Path(source_file),
        game_name=game,
        system_name=system,
        media_type=media_type,
        move=move,
        overwrite=overwrite,
    )

    action = "Moved" if move else "Copied"
    if result.success and not result.skipped:
        console.print(f"[green]✓[/green] {action} → {result.path}")
    elif result.skipped:
        console.print(f"[yellow]Skipped:[/yellow] {result.error}")
    else:
        err_console.print(f"[red]Failed:[/red] {result.error}")
        sys.exit(1)


# ─── update-db ────────────────────────────────────────────────────────────────

@cli.command("update-db")
@click.option("--system", "-s", default=None)
@click.option("--all", "all_systems", is_flag=True)
@click.option("--add-missing", "add_missing", is_flag=True, default=True)
@click.option("--remove-orphans", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("--output-dir", type=click.Path(), default=None)
@click.option(
    "--strip-variant-tags/--keep-variant-tags",
    "strip_variants_cli",
    default=None,
    help="Strip region/revision tags from stub display names "
         "(default: keep, e.g. '1942 (Japan)').",
)
def update_db(system, all_systems, add_missing, remove_orphans, dry_run,
              output_dir, strip_variants_cli):
    """Sync Hyperspin XML databases to match ROM directories.

    Adds stub entries for ROMs not in the database; optionally removes entries
    with no matching ROM.  Variant ROM names (region, version, revision) are
    each written as their own individual database entry.
    """
    config = _cfg()
    _check_config(config)
    systems = _resolve_systems(config, system, all_systems)
    out_base = Path(output_dir) if output_dir else None

    strip_variants = (
        strip_variants_cli
        if strip_variants_cli is not None
        else config.strip_variant_tags_in_display_name
    )

    if dry_run:
        console.print("[yellow bold][DRY RUN][/yellow bold] No files will be written.")

    for sys_name in systems:
        console.print(f"\n[blue bold]{sys_name}[/blue bold]")
        result = audit_system(sys_name, config, check_media_flag=False)
        db = load_database(sys_name, config.databases_dir)

        added = removed = 0

        if add_missing:
            roms_to_add = [
                e for e in result.roms_only
                if not config.is_ignored(e.rom_name, sys_name)
            ]
            if roms_to_add:
                console.print(f"  Adding [cyan]{len(roms_to_add)}[/cyan] stub entries…")
                for entry in roms_to_add:
                    stub = build_stub_entry(entry.rom_name, strip_variants=strip_variants)
                    if dry_run:
                        console.print(
                            f"  [yellow]+[/yellow] {escape(entry.rom_name)} "
                            f"→ \"{escape(stub.description)}\""
                        )
                    else:
                        db.add_game(stub)
                    added += 1

        if remove_orphans:
            orphans = [
                e for e in result.db_only
                if not config.is_ignored(e.rom_name, sys_name)
            ]
            if orphans:
                console.print(f"  Removing [cyan]{len(orphans)}[/cyan] orphan entries…")
                for entry in orphans:
                    if dry_run:
                        console.print(f"  [red]−[/red] {escape(entry.rom_name)}")
                    else:
                        db.remove_game(entry.rom_name)
                    removed += 1

        console.print(f"  Added: [green]{added}[/green]  Removed: [red]{removed}[/red]")

        if not dry_run and (added or removed):
            if out_base:
                saved = db.save(
                    output_path=out_base / "Databases" / sys_name / f"{sys_name}.xml",
                    backup=False,
                )
            else:
                saved = db.save(backup=config.backup_before_modify)
            console.print(f"  [green]Saved:[/green] {saved}")
        elif not added and not removed:
            console.print("  [green]Database already in sync.[/green]")

    _auto_export_audit(config, systems)


# ─── generate-config ──────────────────────────────────────────────────────────

@cli.command("generate-config")
@click.option("--all", "all_systems", is_flag=True, default=False,
              help="Generate config for all detected systems.")
@click.option("--system", "-s", default=None, help="Target a single system.")
@click.option("--rl/--no-rl", "gen_rl", default=True,
              help="Generate RocketLauncher system INI files (default: on).")
@click.option("--main-menu/--no-main-menu", "gen_menu", default=True,
              help="Generate HyperSpin Main Menu.xml (default: on).")
@click.option("--db-stubs/--no-db-stubs", "gen_stubs", default=False,
              help="Create empty database XMLs for systems without one.")
@click.option("--dry-run", is_flag=True)
@click.option("--output-dir", type=click.Path(), default=None,
              help="Write all output here instead of in-place.")
def generate_config(all_systems, system, gen_rl, gen_menu, gen_stubs, dry_run, output_dir):
    """Generate RocketLauncher INI files and the HyperSpin Main Menu database.

    \b
    What gets generated:
      - RocketLauncher Settings/<SystemName>.ini  (one per system)
      - Databases/Main Menu/Main Menu.xml         (lists all systems)
      - Databases/<SystemName>/<SystemName>.xml   (stubs, with --db-stubs)

    \b
    Examples:
      # Dry run — see what would be created
      spindoctor generate-config --dry-run

      # Write into a staging folder, review, then copy
      spindoctor generate-config --output-dir D:\\Output

      # Write in-place (requires rocketlauncher_dir to be configured)
      spindoctor generate-config
    """
    config = _cfg()
    _check_config(config)

    from .rocketlauncher import (
        generate_hs_main_menu,
        generate_rl_system_ini,
        generate_system_db_stubs,
        guess_emulator,
    )

    # Default to all systems when neither --system nor --all is given
    if not system and not all_systems:
        all_systems = True
    systems = _resolve_systems(config, system, all_systems)
    out_base = Path(output_dir) if output_dir else None

    if dry_run:
        console.print("[yellow bold][DRY RUN][/yellow bold] No files will be written.")

    if gen_rl:
        console.print(f"\n[blue bold]RocketLauncher system INIs[/blue bold] ({len(systems)} systems)")
        tbl = Table(box=box.SIMPLE, show_header=True)
        tbl.add_column("System", style="cyan")
        tbl.add_column("Emulator")
        tbl.add_column("Path" if not dry_run else "Would write")

        for sys_name in systems:
            emulator = guess_emulator(sys_name)
            if dry_run:
                rl_base = out_base or (Path(config.rocketlauncher_dir) if config.rocketlauncher_dir else None)
                path_str = (
                    str(rl_base / "Settings" / f"{sys_name}.ini")
                    if rl_base else "[dim]rocketlauncher_dir not configured[/dim]"
                )
                tbl.add_row(sys_name, emulator, path_str)
            else:
                try:
                    p = generate_rl_system_ini(sys_name, config, out_base)
                    tbl.add_row(sys_name, emulator, str(p))
                except ValueError as e:
                    tbl.add_row(sys_name, emulator, f"[red]{e}[/red]")
        console.print(tbl)

    if gen_menu:
        console.print(f"\n[blue bold]HyperSpin Main Menu[/blue bold]")
        if dry_run:
            db_base = out_base / "Databases" if out_base else config.databases_dir
            console.print(f"  [dim]Would write:[/dim] {db_base / 'Main Menu' / 'Main Menu.xml'}")
            console.print(f"  Listing {len(systems)} systems: {', '.join(systems[:8])}"
                          + (f" …+{len(systems)-8}" if len(systems) > 8 else ""))
        else:
            p = generate_hs_main_menu(systems, config, out_base)
            console.print(f"  [green]✓[/green] {p}")

    if gen_stubs:
        console.print(f"\n[blue bold]Database stubs[/blue bold]")
        if dry_run:
            console.print(f"  [dim]Would create stubs for:[/dim] {', '.join(systems)}")
        else:
            created = generate_system_db_stubs(systems, config, out_base)
            if created:
                for p in created:
                    console.print(f"  [green]+[/green] {p}")
            else:
                console.print("  [dim]All system databases already exist.[/dim]")


# ─── report ───────────────────────────────────────────────────────────────────

@cli.command("report")
@click.option("--system", "-s", default=None)
@click.option("--all", "all_systems", is_flag=True)
@click.option("--format", "fmt", default="summary",
              type=click.Choice(["table", "csv", "summary"]))
@click.option("--output", "-o", type=click.Path(), default=None)
@click.option("--no-media", is_flag=True)
@click.option("--no-fuzzy", is_flag=True)
def report(system, all_systems, fmt, output, no_media, no_fuzzy):
    """Generate a read-only audit report without making any changes."""
    config = _cfg()
    _check_config(config)
    systems = _resolve_systems(config, system, all_systems)

    all_results: list[SystemAuditResult] = []
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
        task = prog.add_task("Scanning…", total=len(systems))
        for sys_name in systems:
            prog.update(task, description=f"Scanning [cyan]{sys_name}[/cyan]…")
            all_results.append(
                audit_system(sys_name, config,
                             check_media_flag=not no_media,
                             fuzzy=not no_fuzzy)
            )
            prog.advance(task)

    if fmt == "csv":
        if not output:
            err_console.print("[red]--output is required for CSV format.[/red]")
            sys.exit(1)
        _write_audit_csv(all_results, Path(output))
        console.print(f"[green]Report written:[/green] {output}")
        return

    if fmt == "summary":
        tbl = Table(title="Audit Summary", box=box.ROUNDED)
        tbl.add_column("System", style="cyan")
        tbl.add_column("ROMs", justify="right")
        tbl.add_column("DB", justify="right")
        tbl.add_column("Match", justify="right", style="green")
        tbl.add_column("Fuzzy", justify="right", style="blue")
        tbl.add_column("ROM only", justify="right", style="yellow")
        tbl.add_column("DB only", justify="right", style="red")
        tbl.add_column("No meta", justify="right", style="magenta")
        tbl.add_column("No media", justify="right", style="magenta")
        tbl.add_column("Ignored", justify="right", style="dim")
        for r in all_results:
            tbl.add_row(
                r.system_name,
                str(r.total_roms), str(r.total_db_entries),
                str(r.roms_in_db), str(len(r.fuzzy_matches)),
                str(r.roms_not_in_db), str(r.db_entries_no_rom),
                str(len(r.missing_metadata_entries)),
                str(len(r.missing_media_entries)),
                str(r.ignored_count),
            )
        console.print(tbl)
        if output:
            with open(output, "w", encoding="utf-8") as f:
                from rich.console import Console as RC
                RC(file=f, no_color=True).print(tbl)
            console.print(f"[green]Report written:[/green] {output}")
        return

    for r in all_results:
        _print_audit_result(r, show_matched=False)
    if output:
        _write_audit_csv(all_results, Path(output))
        console.print(f"[green]Report written:[/green] {output}")
