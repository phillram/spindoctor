"""SpinDoctor CLI — Hyperspin arcade library manager."""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Optional

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from . import __app_name__, __version__
from .audit import GameAuditEntry, SystemAuditResult, audit_system, build_stub_entry
from .config import Config, MEDIA_TYPES, get_systems, load_config, save_config
from .database import load_database

console = Console()
err_console = Console(stderr=True)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _load_cfg() -> Config:
    return load_config()


def _resolve_systems(config: Config, system: Optional[str], all_systems: bool) -> list[str]:
    if all_systems:
        systems = get_systems(config)
        if not systems:
            err_console.print("[red]No systems found. Check your roms_dir and hyperspin_dir.[/red]")
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


def _status_icon(value: bool) -> str:
    return "[green]✓[/green]" if value else "[red]✗[/red]"


# ─── root group ───────────────────────────────────────────────────────────────

@click.group()
@click.version_option(__version__, prog_name=__app_name__)
def cli():
    """SpinDoctor — Hyperspin arcade library manager.

    Audit ROMs, sync databases, and fetch metadata & media for your arcade cabinet.
    """


# ─── config ───────────────────────────────────────────────────────────────────

@cli.group("config")
def config_group():
    """Show or update SpinDoctor configuration."""


@config_group.command("show")
def config_show():
    """Display current configuration."""
    config = _load_cfg()
    table = Table(title="SpinDoctor Configuration", box=box.ROUNDED)
    table.add_column("Key", style="cyan")
    table.add_column("Value")

    sensitive = {"screenscraper_pass", "thegamesdb_key"}
    for key, val in config.to_dict().items():
        if key in ("ignore_lists",):
            continue
        display = "***" if key in sensitive and val else (str(val) or "[dim]<not set>[/dim]")
        table.add_row(key, display)

    console.print(table)


@config_group.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Set a configuration value.

    \b
    Keys:
      roms_dir            Directory containing system ROM folders
      hyperspin_dir       Root HyperSpin directory (contains Databases/ and Media/)
      emulators_dir       Directory containing emulator folders
      output_dir          Default output directory (leave blank to modify in-place)
      screenscraper_user  ScreenScraper username
      screenscraper_pass  ScreenScraper password
      thegamesdb_key      TheGamesDB API key
      default_metadata_source  screenscraper or thegamesdb
      backup_before_modify     true/false
      max_concurrent_downloads Integer
    """
    config = _load_cfg()
    if not hasattr(config, key):
        err_console.print(f"[red]Unknown config key:[/red] {key}")
        sys.exit(1)

    current = getattr(config, key)
    if isinstance(current, bool):
        setattr(config, key, value.lower() in ("1", "true", "yes"))
    elif isinstance(current, int):
        setattr(config, key, int(value))
    else:
        setattr(config, key, value)

    save_config(config)
    console.print(f"[green]✓[/green] Set [cyan]{key}[/cyan] = {value!r}")


# ─── systems ──────────────────────────────────────────────────────────────────

@cli.command("systems")
def list_systems():
    """List all detected systems."""
    config = _load_cfg()
    _check_config(config)
    systems = get_systems(config)
    if not systems:
        console.print("[yellow]No systems found.[/yellow]")
        return

    table = Table(title="Detected Systems", box=box.ROUNDED)
    table.add_column("#", style="dim")
    table.add_column("System", style="cyan")
    table.add_column("ROMs dir", style="dim")
    table.add_column("Database", style="dim")

    roms_base = Path(config.roms_dir)
    db_base = config.databases_dir

    for i, sys_name in enumerate(systems, 1):
        has_roms = (roms_base / sys_name).exists()
        has_db = any((db_base / sys_name).glob("*.xml")) if (db_base / sys_name).exists() else False
        table.add_row(
            str(i),
            sys_name,
            _status_icon(has_roms),
            _status_icon(has_db),
        )

    console.print(table)


# ─── audit ────────────────────────────────────────────────────────────────────

@cli.command("audit")
@click.option("--system", "-s", default=None, help="System name to audit.")
@click.option("--all", "all_systems", is_flag=True, help="Audit all systems.")
@click.option("--no-media", is_flag=True, help="Skip media file checks (faster).")
@click.option("--report", "-r", type=click.Path(), default=None,
              help="Write CSV report to this path.")
@click.option("--show-matched", is_flag=True, help="Also show matched games (verbose).")
def audit(system, all_systems, no_media, report, show_matched):
    """Audit ROM files against Hyperspin database entries and media.

    Reports ROMs missing from the database, database entries with no ROM,
    incomplete metadata, and missing media assets.
    """
    config = _load_cfg()
    _check_config(config)
    systems = _resolve_systems(config, system, all_systems)

    all_results: list[SystemAuditResult] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Auditing systems...", total=len(systems))
        for sys_name in systems:
            progress.update(task, description=f"Auditing [cyan]{sys_name}[/cyan]...")
            result = audit_system(sys_name, config, check_media_flag=not no_media)
            all_results.append(result)
            progress.advance(task)

    for result in all_results:
        _print_audit_result(result, show_matched)

    if report:
        _write_audit_csv(all_results, Path(report))
        console.print(f"\n[green]Report saved:[/green] {report}")


def _print_audit_result(result: SystemAuditResult, show_matched: bool) -> None:
    title = f" {result.system_name} "
    console.print(Panel(title, style="bold blue"))

    summary = Table.grid(padding=(0, 2))
    summary.add_row("[cyan]Total ROMs:[/cyan]", str(result.total_roms))
    summary.add_row("[cyan]Total DB entries:[/cyan]", str(result.total_db_entries))
    summary.add_row(
        "[green]ROMs matched in DB:[/green]",
        str(result.roms_in_db),
    )
    summary.add_row(
        "[yellow]ROMs NOT in DB:[/yellow]",
        str(result.roms_not_in_db),
    )
    summary.add_row(
        "[red]DB entries with no ROM:[/red]",
        str(result.db_entries_no_rom),
    )
    summary.add_row(
        "[magenta]Entries with incomplete metadata:[/magenta]",
        str(len(result.missing_metadata_entries)),
    )
    summary.add_row(
        "[magenta]Entries with missing media:[/magenta]",
        str(len(result.missing_media_entries)),
    )
    console.print(summary)

    if result.roms_only:
        console.print("\n[yellow bold]ROMs not in database:[/yellow bold]")
        for entry in result.roms_only[:50]:
            console.print(f"  [yellow]•[/yellow] {entry.rom_name}")
        if len(result.roms_only) > 50:
            console.print(f"  [dim]... and {len(result.roms_only) - 50} more[/dim]")

    if result.db_only:
        console.print("\n[red bold]Database entries with no ROM:[/red bold]")
        for entry in result.db_only[:50]:
            desc = entry.db_entry.description if entry.db_entry else ""
            console.print(f"  [red]•[/red] {entry.rom_name}" + (f" ({desc})" if desc else ""))
        if len(result.db_only) > 50:
            console.print(f"  [dim]... and {len(result.db_only) - 50} more[/dim]")

    if result.missing_metadata_entries:
        console.print("\n[magenta bold]Entries with incomplete metadata:[/magenta bold]")
        tbl = Table(box=box.SIMPLE)
        tbl.add_column("Game")
        tbl.add_column("Missing Fields")
        for entry in result.missing_metadata_entries[:30]:
            tbl.add_row(entry.rom_name, ", ".join(entry.missing_metadata))
        console.print(tbl)
        if len(result.missing_metadata_entries) > 30:
            console.print(f"  [dim]... and {len(result.missing_metadata_entries) - 30} more[/dim]")

    if show_matched and result.matched:
        console.print(f"\n[green]Matched games: {len(result.matched)}[/green]")


def _write_audit_csv(results: list[SystemAuditResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "system", "rom_name", "in_database", "rom_exists",
            "missing_metadata", "missing_media",
            "wheel", "background", "artwork", "video", "sound",
        ])
        for result in results:
            for entry in result.entries:
                writer.writerow([
                    result.system_name,
                    entry.rom_name,
                    entry.in_database,
                    entry.rom_exists,
                    ";".join(entry.missing_metadata),
                    ";".join(entry.media.missing()),
                    entry.media.wheel,
                    entry.media.background,
                    entry.media.artwork,
                    entry.media.video,
                    entry.media.sound,
                ])


# ─── fetch-meta ───────────────────────────────────────────────────────────────

@cli.command("fetch-meta")
@click.option("--system", "-s", default=None, help="System name.")
@click.option("--all", "all_systems", is_flag=True)
@click.option("--source", default=None, type=click.Choice(["screenscraper", "thegamesdb"]),
              help="Metadata source (default: from config).")
@click.option("--missing-only", is_flag=True, default=True,
              help="Only fetch for entries with incomplete metadata (default: on).")
@click.option("--all-games", "fetch_all", is_flag=True,
              help="Fetch metadata for all games, even complete ones.")
@click.option("--dry-run", is_flag=True, help="Show what would be updated without writing.")
@click.option("--output-dir", type=click.Path(), default=None,
              help="Write updated databases here instead of in-place.")
def fetch_meta(system, all_systems, source, missing_only, fetch_all, dry_run, output_dir):
    """Download and update game metadata in Hyperspin database XML files.

    Fetches description, year, manufacturer, genre, and rating from the
    configured metadata source and writes them into the database XML.
    """
    config = _load_cfg()
    _check_config(config)
    systems = _resolve_systems(config, system, all_systems)

    from .scraper import MetadataError, build_client

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
            targets = list(db.games().values())
        else:
            targets = list(db.iter_incomplete())

        if not targets:
            console.print("  [green]All metadata complete. Nothing to do.[/green]")
            continue

        console.print(f"  Fetching metadata for [cyan]{len(targets)}[/cyan] games...")

        updated = 0
        failed = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            task = progress.add_task("", total=len(targets))

            for game in targets:
                progress.update(task, description=f"[dim]{game.name[:40]}[/dim]")
                try:
                    meta = client.fetch(game.name, sys_name)
                    if meta:
                        if not dry_run:
                            game.description = meta.name or game.description
                            if meta.manufacturer:
                                game.manufacturer = meta.manufacturer
                            if meta.year:
                                game.year = meta.year
                            if meta.genre:
                                game.genre = meta.genre
                            if meta.rating:
                                game.rating = meta.rating
                            if not game.description:
                                game.description = game.name
                            db.update_game(game)
                        updated += 1
                    else:
                        failed += 1
                except MetadataError as e:
                    console.print(f"  [red]Error fetching {game.name}:[/red] {e}")
                    failed += 1
                progress.advance(task)

        console.print(
            f"  Updated: [green]{updated}[/green]  "
            f"Not found: [yellow]{failed}[/yellow]"
        )

        if not dry_run and updated > 0:
            if out_base:
                out_path = out_base / "Databases" / sys_name / f"{sys_name}.xml"
                saved = db.save(output_path=out_path, backup=False)
            else:
                saved = db.save(backup=config.backup_before_modify)
            console.print(f"  [green]Saved:[/green] {saved}")


# ─── fetch-media ──────────────────────────────────────────────────────────────

@cli.command("fetch-media")
@click.option("--system", "-s", default=None)
@click.option("--all", "all_systems", is_flag=True)
@click.option("--types", default=",".join(MEDIA_TYPES),
              help=f"Comma-separated media types. Options: {', '.join(MEDIA_TYPES)}")
@click.option("--source", default=None, type=click.Choice(["screenscraper", "thegamesdb"]))
@click.option("--missing-only", is_flag=True, default=True,
              help="Only download media that doesn't already exist (default: on).")
@click.option("--overwrite", is_flag=True, help="Overwrite existing media files.")
@click.option("--dry-run", is_flag=True)
@click.option("--output-dir", type=click.Path(), default=None,
              help="Save media here instead of inside hyperspin_dir.")
def fetch_media(system, all_systems, types, source, missing_only, overwrite, dry_run, output_dir):
    """Download media assets (wheel art, backgrounds, videos, sounds, etc.).

    Fetches media URLs from the metadata source then saves them into the
    correct Hyperspin Media directory structure.
    """
    config = _load_cfg()
    _check_config(config)
    systems = _resolve_systems(config, system, all_systems)

    from .audit import check_media
    from .media import MediaDownloader
    from .scraper import MetadataError, build_client

    media_types = [t.strip() for t in types.split(",") if t.strip() in MEDIA_TYPES]
    if not media_types:
        err_console.print(f"[red]No valid media types specified. Choose from: {', '.join(MEDIA_TYPES)}[/red]")
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
        games = list(db.games().values())

        if not games:
            console.print("  [yellow]No games in database.[/yellow]")
            continue

        if missing_only and not overwrite:
            games = [
                g for g in games
                if check_media(g.name, sys_name, config.media_dir).missing()
            ]

        if not games:
            console.print("  [green]All media present. Nothing to download.[/green]")
            continue

        console.print(f"  Processing [cyan]{len(games)}[/cyan] games for types: {', '.join(media_types)}")

        total_ok = total_skip = total_fail = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            task = progress.add_task("", total=len(games))

            for game in games:
                progress.update(task, description=f"[dim]{game.name[:40]}[/dim]")
                try:
                    meta = client.fetch(game.name, sys_name)
                    if meta:
                        results = downloader.download_from_metadata(
                            game.name,
                            sys_name,
                            meta,
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
                    console.print(f"  [red]Error for {game.name}:[/red] {e}")
                    total_fail += len(media_types)
                progress.advance(task)

        console.print(
            f"  Downloaded: [green]{total_ok}[/green]  "
            f"Skipped: [dim]{total_skip}[/dim]  "
            f"Failed: [red]{total_fail}[/red]"
        )


# ─── update-db ────────────────────────────────────────────────────────────────

@cli.command("update-db")
@click.option("--system", "-s", default=None)
@click.option("--all", "all_systems", is_flag=True)
@click.option("--add-missing", is_flag=True, default=True,
              help="Add ROMs that are missing from the database (default: on).")
@click.option("--remove-orphans", is_flag=True,
              help="Remove database entries that have no corresponding ROM.")
@click.option("--dry-run", is_flag=True, help="Show changes without writing.")
@click.option("--output-dir", type=click.Path(), default=None)
def update_db(system, all_systems, add_missing, remove_orphans, dry_run, output_dir):
    """Sync database XML files to match the ROM directory.

    By default, adds stub entries for ROMs not in the database.
    Use --remove-orphans to also remove database entries with no ROM file.
    """
    config = _load_cfg()
    _check_config(config)
    systems = _resolve_systems(config, system, all_systems)

    out_base = Path(output_dir) if output_dir else None
    if dry_run:
        console.print("[yellow bold][DRY RUN][/yellow bold] No files will be written.")

    for sys_name in systems:
        console.print(f"\n[blue bold]{sys_name}[/blue bold]")
        result = audit_system(sys_name, config, check_media_flag=False)
        db = load_database(sys_name, config.databases_dir)

        added = removed = 0

        if add_missing and result.roms_only:
            console.print(f"  Adding [cyan]{len(result.roms_only)}[/cyan] stub entries...")
            for entry in result.roms_only:
                stub = build_stub_entry(entry.rom_name)
                if dry_run:
                    console.print(f"  [yellow]+[/yellow] {entry.rom_name} → \"{stub.description}\"")
                else:
                    db.add_game(stub)
                added += 1

        if remove_orphans and result.db_only:
            console.print(f"  Removing [cyan]{len(result.db_only)}[/cyan] orphan entries...")
            for entry in result.db_only:
                if dry_run:
                    console.print(f"  [red]−[/red] {entry.rom_name}")
                else:
                    db.remove_game(entry.rom_name)
                removed += 1

        console.print(
            f"  Added: [green]{added}[/green]  Removed: [red]{removed}[/red]"
        )

        if not dry_run and (added or removed):
            if out_base:
                out_path = out_base / "Databases" / sys_name / f"{sys_name}.xml"
                saved = db.save(output_path=out_path, backup=False)
            else:
                saved = db.save(backup=config.backup_before_modify)
            console.print(f"  [green]Saved:[/green] {saved}")
        elif not added and not removed:
            console.print("  [green]Database already in sync.[/green]")


# ─── report ───────────────────────────────────────────────────────────────────

@cli.command("report")
@click.option("--system", "-s", default=None)
@click.option("--all", "all_systems", is_flag=True)
@click.option("--format", "fmt", default="table",
              type=click.Choice(["table", "csv", "summary"]))
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write report to file (required for CSV).")
@click.option("--no-media", is_flag=True)
def report(system, all_systems, fmt, output, no_media):
    """Generate an audit report without making any changes."""
    config = _load_cfg()
    _check_config(config)
    systems = _resolve_systems(config, system, all_systems)

    all_results = []
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
        task = prog.add_task("Scanning...", total=len(systems))
        for sys_name in systems:
            prog.update(task, description=f"Scanning [cyan]{sys_name}[/cyan]...")
            all_results.append(audit_system(sys_name, config, check_media_flag=not no_media))
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
        tbl.add_column("Matched", justify="right", style="green")
        tbl.add_column("ROM only", justify="right", style="yellow")
        tbl.add_column("DB only", justify="right", style="red")
        tbl.add_column("No meta", justify="right", style="magenta")
        tbl.add_column("No media", justify="right", style="magenta")
        for r in all_results:
            tbl.add_row(
                r.system_name,
                str(r.total_roms),
                str(r.total_db_entries),
                str(r.roms_in_db),
                str(r.roms_not_in_db),
                str(r.db_entries_no_rom),
                str(len(r.missing_metadata_entries)),
                str(len(r.missing_media_entries)),
            )
        console.print(tbl)
        if output:
            with open(output, "w", encoding="utf-8") as f:
                from rich.console import Console as RC
                file_console = RC(file=f, no_color=True)
                file_console.print(tbl)
            console.print(f"[green]Report written:[/green] {output}")
        return

    for r in all_results:
        _print_audit_result(r, show_matched=False)
