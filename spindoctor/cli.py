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
from .audit import SystemAuditResult, audit_system, build_stub_entry
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
    """Show or update SpinDoctor configuration.

    Run `spindoctor config init` for a first-run wizard that walks through
    every path-based setting in one go.
    """


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
      ledblinky_dir             LEDBlinky install directory (contains LEDBlinky.exe and LEDBlinkyControls.xml)
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
      mame_executable           Path to MAME binary (used for -listxml)
      metadata_cache_ttl_days   Days to keep cached API responses (default 30)
      metadata_cache_enabled    true | false (default true)
    """
    config = _cfg()
    if not hasattr(config, key) or key in (
        "ignore_lists", "databases_dir", "media_dir", "ledblinky_default_colors",
    ):
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


# Wizard fields: (key, prompt label, hardcoded Windows default, allow_blank).
# allow_blank=True keys accept "-" as a sentinel to clear the value.
_INIT_FIELDS: tuple[tuple[str, str, str, bool], ...] = (
    ("roms_dir",              "ROMs directory (one sub-folder per system)",        r"D:\ROMs",                       False),
    ("hyperspin_dir",         "HyperSpin directory (has Databases/ and Media/)",   r"D:\HyperSpin",                  False),
    ("emulators_dir",         "Emulators directory",                               r"D:\Emulators",                  False),
    ("rocketlauncher_dir",    "RocketLauncher directory",                          r"D:\RocketLauncher",             False),
    ("ledblinky_dir",         "LEDBlinky install directory ('-' to skip)",         r"C:\LEDBlinky",                  True),
    ("mame_executable",       "MAME executable ('-' to skip)",                     r"D:\Emulators\MAME\mame.exe",    True),
    ("output_dir",            "Default output directory ('-' for in-place writes)", r"D:\SpinDoctorOutput",          True),
    ("auto_audit_export_dir", "Auto-audit export directory ('-' to skip)",         r"D:\SpinDoctorAudits",           True),
)


@config_group.command("init")
def config_init():
    """First-run setup wizard — prompt for every path-based config key in order.

    Press Enter to accept the shown default. For optional keys, type '-' to
    leave the value blank. Existing values (from a previous run) are used as
    the defaults so re-running the wizard refines rather than overwrites.
    """
    config = _cfg()
    console.print(Panel.fit(
        "[bold]SpinDoctor first-run setup[/bold]\n"
        "Press [cyan]Enter[/cyan] to accept each default. "
        "Type [cyan]-[/cyan] to clear an optional path.",
        box=box.ROUNDED,
    ))

    pending: dict[str, str] = {}
    for key, label, win_default, allow_blank in _INIT_FIELDS:
        existing = getattr(config, key, "") or ""
        default = existing if existing else win_default
        answer = click.prompt(label, default=default, show_default=True).strip()
        pending[key] = "" if (allow_blank and answer == "-") else answer

    tbl = Table(title="Review", box=box.ROUNDED)
    tbl.add_column("Key", style="cyan")
    tbl.add_column("Value")
    for key, val in pending.items():
        tbl.add_row(key, val or "[dim]<not set>[/dim]")
    console.print(tbl)

    if not click.confirm("Save this configuration?", default=True):
        console.print("[yellow]Cancelled — no changes written.[/yellow]")
        return

    for key, val in pending.items():
        setattr(config, key, val)
    save_config(config)

    ok, errors = config.is_valid()
    if ok:
        console.print("[green]✓ Setup complete.[/green] Run [cyan]spindoctor doctor[/cyan] for a full health check.")
    else:
        console.print("[green]✓ Saved.[/green] [yellow]But some required paths still need attention:[/yellow]")
        for e in errors:
            err_console.print(f"  [yellow]•[/yellow] {e}")
        console.print("Run [cyan]spindoctor doctor[/cyan] once paths are reachable.")


# ─── config system overrides ──────────────────────────────────────────────────

# Layout values supported by spindoctor/organize.py.  "flat" disables the
# default folder restructuring rule for a system.
_LAYOUT_CHOICES = ("per-game-folder", "multi-disc-m3u", "flat")


@config_group.group("system")
def config_system_group():
    """Per-system overrides for ROM extensions, scraper IDs, layout, emulator.

    Lets you add support for consoles SpinDoctor doesn't yet know about
    without editing source code.
    """


@config_system_group.command("set")
@click.argument("system_name")
@click.option("--screenscraper-id", type=int, default=None,
              help="ScreenScraper platform ID (integer).")
@click.option("--thegamesdb-id", type=int, default=None,
              help="TheGamesDB platform ID (integer).")
@click.option("--rom-extensions", default=None,
              help="Comma-separated ROM extensions (with or without leading dot).")
@click.option("--layout", default=None, type=click.Choice(_LAYOUT_CHOICES),
              help="ROM folder layout. 'flat' disables a built-in rule.")
@click.option("--emulator", default=None,
              help="RocketLauncher emulator name (e.g. RetroArch, MAME, RPCS3).")
def config_system_set(system_name, screenscraper_id, thegamesdb_id,
                      rom_extensions, layout, emulator):
    """Add or update overrides for SYSTEM_NAME.

    \b
    Example — make SpinDoctor aware of a hypothetical PS7 install:
      spindoctor config system set "Sony Playstation 7" \\
          --screenscraper-id 999 \\
          --rom-extensions ps7,iso \\
          --layout per-game-folder \\
          --emulator RPCS7
    """
    config = _cfg()
    overrides = dict(config.system_overrides)
    entry = dict(overrides.get(system_name, {}))

    if screenscraper_id is not None:
        entry["screenscraper_id"] = screenscraper_id
    if thegamesdb_id is not None:
        entry["thegamesdb_id"] = thegamesdb_id
    if rom_extensions is not None:
        exts = [
            e.strip() if e.strip().startswith(".") else f".{e.strip()}"
            for e in rom_extensions.split(",")
            if e.strip()
        ]
        entry["rom_extensions"] = exts
    if layout is not None:
        entry["layout"] = layout
    if emulator is not None:
        entry["emulator"] = emulator

    if not entry:
        err_console.print(
            "[red]Nothing to set.[/red] Pass at least one of "
            "--screenscraper-id / --thegamesdb-id / --rom-extensions / --layout / --emulator."
        )
        sys.exit(1)

    overrides[system_name] = entry
    config.system_overrides = overrides
    save_config(config)
    console.print(f"[green]✓[/green] Override saved for [cyan]{system_name}[/cyan]:")
    for k, v in entry.items():
        console.print(f"    [dim]{k}:[/dim] {v}")


@config_system_group.command("clear")
@click.argument("system_name")
def config_system_clear(system_name):
    """Remove all overrides for SYSTEM_NAME (falls back to built-in defaults)."""
    config = _cfg()
    if system_name not in config.system_overrides:
        console.print(f"[yellow]No overrides set for {system_name}.[/yellow]")
        return
    config.system_overrides = {
        k: v for k, v in config.system_overrides.items() if k != system_name
    }
    save_config(config)
    console.print(f"[green]✓[/green] Cleared overrides for [cyan]{system_name}[/cyan].")


@config_system_group.command("list")
def config_system_list():
    """Show all per-system overrides."""
    config = _cfg()
    if not config.system_overrides:
        console.print("[dim]No system overrides configured.[/dim]")
        return
    tbl = Table(title="System Overrides", box=box.ROUNDED)
    tbl.add_column("System", style="cyan")
    tbl.add_column("Override")
    tbl.add_column("Value")
    for sys_name in sorted(config.system_overrides):
        entry = config.system_overrides[sys_name]
        for k, v in entry.items():
            tbl.add_row(sys_name, k, str(v))
    console.print(tbl)


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

    # MAME -listxml enrichment, if available
    listxml_checked = [e for e in result.entries if e.has_mame_input is not None]
    if listxml_checked:
        with_input = sum(1 for e in listxml_checked if e.has_mame_input)
        no_input = sum(1 for e in listxml_checked if e.has_mame_input is False)
        not_listed = len(result.entries) - len(listxml_checked)
        grid.add_row(
            "[cyan]MAME controls (-listxml):[/cyan]",
            f"[green]{with_input}[/green] with input · "
            f"[yellow]{no_input}[/yellow] no-input · "
            f"[red]{not_listed}[/red] not listed",
        )
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

    from .fileinfo import scan_game

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


# ─── find-dupes / find-misplaced / lint ──────────────────────────────────────

@cli.command("find-dupes")
@click.option("--system", "-s", default=None)
@click.option("--all", "all_systems", is_flag=True)
@click.option("--cross-systems", is_flag=True,
              help="Also report titles that appear under more than one system.")
@click.option("--by-content", is_flag=True,
              help="Hash file bytes (slow) to catch identical files renamed differently.")
def find_dupes(system, all_systems, cross_systems, by_content):
    """Scan for duplicated games within a system (and optionally across systems).

    \b
    Two ROMs are considered duplicates by default when their stems
    collapse to the same normalised title (region/version/disc tags
    stripped). Use --by-content to additionally pair files that share
    bytes; --cross-systems to find a title filed under multiple systems.
    """
    from .dupes import find_cross_system_duplicates, find_duplicates_in_system

    config = _cfg()
    _check_config(config)
    systems = _resolve_systems(config, system, all_systems)

    total = 0
    for sys_name in systems:
        groups = find_duplicates_in_system(sys_name, config, by_content=by_content)
        if not groups:
            console.print(f"[green]✓[/green] {sys_name}: no duplicates")
            continue
        console.print(Panel(f" {sys_name} — {len(groups)} duplicate group(s) ",
                            style="bold yellow"))
        for g in groups:
            label = "title" if g.reason == "title" else f"sha1:{g.key}"
            console.print(f"  [cyan]{label}[/cyan] [dim]({g.count} files)[/dim]")
            for p in g.files:
                console.print(f"    [yellow]·[/yellow] {p}")
        total += len(groups)

    if cross_systems and len(systems) > 1:
        matches = find_cross_system_duplicates(systems, config)
        if matches:
            console.print(Panel(
                f" cross-system — {len(matches)} title(s) in multiple folders ",
                style="bold magenta"))
            for m in matches:
                console.print(f"  [cyan]{m.key}[/cyan] [dim]→ {', '.join(m.systems)}[/dim]")
                for sys_name, p in m.occurrences:
                    console.print(f"    [yellow]·[/yellow] [dim]{sys_name}:[/dim] {p}")
            total += len(matches)
        else:
            console.print("[green]✓[/green] no cross-system overlap")

    if total == 0:
        console.print("\n[green]Clean — no duplicates detected.[/green]")
    else:
        console.print(f"\n[yellow]{total}[/yellow] duplicate group(s) total.")


@cli.command("find-misplaced")
@click.option("--system", "-s", default=None)
@click.option("--all", "all_systems", is_flag=True)
@click.option("--apply", "apply_moves_flag", is_flag=True,
              help="Move each misplaced ROM into its first suggested system "
                   "folder. Writes a manifest so the change can be undone.")
@click.option("--undo", is_flag=True,
              help="Reverse the most recent --apply manifest.")
def find_misplaced(system, all_systems, apply_moves_flag, undo):
    """Scan for ROMs whose extension doesn't match the folder's system.

    \b
    Surfaces files that probably belong to a different platform — e.g. a
    .nes inside the snes folder. Generic containers (.zip, .iso, .bin)
    are skipped because they're ambiguous on inspection alone. Each
    finding lists candidate systems that *do* claim the extension.

    \b
    Examples:
      spindoctor find-misplaced --all
      spindoctor find-misplaced --system snes --apply
      spindoctor find-misplaced --undo
    """
    from .misplaced import (
        apply_moves, find_latest_misplaced_manifest,
        find_misplaced_in_system, undo_moves,
    )

    config = _cfg()
    _check_config(config)

    if undo:
        manifest = find_latest_misplaced_manifest(Path(config.roms_dir))
        if not manifest:
            console.print("[yellow]No misplaced-move manifest to undo.[/yellow]")
            return
        console.print(f"Reverting {manifest.name}")
        summary = undo_moves(manifest)
        console.print(
            f"[green]+[/green] reverted {summary['reverted']} move(s)"
        )
        for err in summary["errors"]:
            err_console.print(f"  [red]✗[/red] {err}")
        return

    systems = _resolve_systems(config, system, all_systems)
    known = get_systems(config)

    total = 0
    all_items = []
    for sys_name in systems:
        items = find_misplaced_in_system(sys_name, config, known_systems=known)
        if not items:
            console.print(f"[green]✓[/green] {sys_name}: nothing misplaced")
            continue
        console.print(Panel(
            f" {sys_name} — {len(items)} misplaced ROM(s) ", style="bold yellow"))
        tbl = Table(box=box.SIMPLE)
        tbl.add_column("File", style="yellow")
        tbl.add_column("Ext")
        tbl.add_column("Likely belongs to", style="cyan")
        for m in items:
            try:
                rel = m.path.relative_to(Path(config.roms_dir) / sys_name)
            except ValueError:
                rel = m.path
            tbl.add_row(str(rel), m.extension,
                        ", ".join(m.suggested_systems[:4]) or "—")
        console.print(tbl)
        total += len(items)
        all_items.extend(items)

    if total == 0:
        console.print("\n[green]Clean — every ROM lives in a matching folder.[/green]")
        return

    console.print(f"\n[yellow]{total}[/yellow] misplaced ROM(s) total.")

    if not apply_moves_flag:
        console.print(
            "[dim]Re-run with[/dim] [cyan]--apply[/cyan] [dim]to move them "
            "into their suggested folders.[/dim]"
        )
        return

    result, manifest = apply_moves(all_items, config)
    console.print(f"\n[green]✓[/green] moved {len(result.moved)} file(s)")
    for src, dest in result.moved:
        console.print(f"  [dim]·[/dim] {src.name} → {dest.parent.name}/")
    if result.skipped:
        console.print(f"[yellow]⚠[/yellow] skipped {len(result.skipped)}:")
        for path, reason in result.skipped:
            console.print(f"  [dim]·[/dim] {path.name} — {reason}")
    if manifest:
        console.print(
            f"\nManifest: {manifest.name}\n"
            f"Run [cyan]spindoctor find-misplaced --undo[/cyan] to revert."
        )


@cli.command("lint")
@click.option("--source", default=None,
              help="Source root to scan (default: spindoctor package directory).")
@click.option("--category", "-c", multiple=True,
              help="Limit output to one or more categories: unused-import, "
                   "dead-code, bare-except, todo, duplicate-body.")
def lint_cmd(source, category):
    """Static-analysis pass over the SpinDoctor codebase itself.

    Reports unused imports, bare except clauses, TODO/FIXME markers, and
    near-duplicate function bodies. Useful as a pre-commit sanity check.
    """
    from . import __file__ as pkg_init
    from .lint import lint_tree

    root = Path(source).resolve() if source else Path(pkg_init).resolve().parent
    report = lint_tree(root)

    wanted = set(category) if category else None
    grouped = report.by_category()
    shown = 0
    for cat in sorted(grouped):
        if wanted and cat not in wanted:
            continue
        items = grouped[cat]
        console.print(Panel(f" {cat} — {len(items)} ", style="bold blue"))
        tbl = Table(box=box.SIMPLE)
        tbl.add_column("File", style="cyan")
        tbl.add_column("Line", justify="right")
        tbl.add_column("Detail")
        for f in items:
            try:
                rel = f.path.relative_to(root)
            except ValueError:
                rel = f.path
            tbl.add_row(str(rel), str(f.line), escape(f.detail))
        console.print(tbl)
        shown += len(items)

    console.print(
        f"\n[dim]scanned {report.files_scanned} file(s); "
        f"{shown} finding(s) shown of {len(report.findings)} total.[/dim]"
    )


# ─── find-orphan-media / check-discs / verify / stats ────────────────────────

@cli.command("find-orphan-media")
@click.option("--system", "-s", default=None)
@click.option("--all", "all_systems", is_flag=True)
@click.option("--delete", is_flag=True,
              help="Delete the reported orphans (irreversible). Default is dry-run.")
def find_orphan_media(system, all_systems, delete):
    """Find media files whose game no longer exists in DB or ROMs.

    \b
    Walks Media/<system>/{Wheel,Backgrounds,Artwork1..3,Video,Sound,Themes}
    and reports each file whose stem isn't a known game. With --delete,
    removes the orphan files (this is destructive; no undo).
    """
    from .orphan_media import delete_orphans, find_orphan_media as _find

    config = _cfg()
    _check_config(config)
    systems = _resolve_systems(config, system, all_systems)

    grand_total = 0
    pending_delete: list = []
    for sys_name in systems:
        report = _find(sys_name, config)
        if not report.orphans:
            console.print(f"[green]✓[/green] {sys_name}: no orphan media")
            continue
        console.print(Panel(
            f" {sys_name} — {len(report.orphans)} orphan(s) ", style="bold yellow"))
        tbl = Table(box=box.SIMPLE)
        tbl.add_column("Type", style="cyan")
        tbl.add_column("File", style="yellow")
        for o in report.orphans:
            try:
                rel = o.path.relative_to(config.media_dir / sys_name)
            except ValueError:
                rel = o.path
            tbl.add_row(o.media_type, str(rel))
        console.print(tbl)
        breakdown = ", ".join(f"{k}: {v}" for k, v in report.by_type.items())
        console.print(f"  [dim]{breakdown}[/dim]")
        grand_total += len(report.orphans)
        pending_delete.extend(report.orphans)

    if grand_total == 0:
        console.print("\n[green]Clean — no orphan media.[/green]")
        return

    console.print(f"\n[yellow]{grand_total}[/yellow] orphan(s) total.")
    if not delete:
        console.print(
            "[dim]Re-run with[/dim] [cyan]--delete[/cyan] [dim]to remove "
            "them (irreversible).[/dim]"
        )
        return

    if not click.confirm(f"Permanently delete {grand_total} file(s)/folder(s)?",
                         default=False):
        console.print("[yellow]Cancelled.[/yellow]")
        return
    deleted, errors = delete_orphans(pending_delete)
    console.print(f"[green]✓[/green] deleted {deleted}")
    for e in errors:
        err_console.print(f"  [red]✗[/red] {e}")


@cli.command("check-discs")
@click.option("--system", "-s", default=None)
@click.option("--all", "all_systems", is_flag=True)
def check_discs_cmd(system, all_systems):
    """Validate multi-disc games and .m3u playlists.

    \b
    Two checks per system:
      • every (Disc N) file has a matching (Disc 1..N-1) sibling
      • every .m3u line resolves to a file that exists on disk
    """
    from .discs import check_discs

    config = _cfg()
    _check_config(config)
    systems = _resolve_systems(config, system, all_systems)

    total_issues = 0
    for sys_name in systems:
        report = check_discs(sys_name, config)
        if not report.issues:
            console.print(
                f"[green]✓[/green] {sys_name}: "
                f"{report.games_checked} game(s), "
                f"{report.playlists_checked} playlist(s) — all good"
            )
            continue
        console.print(Panel(
            f" {sys_name} — {len(report.issues)} disc issue(s) ",
            style="bold yellow"))
        for issue in report.issues:
            console.print(
                f"  [yellow]·[/yellow] [cyan]{issue.kind}[/cyan] "
                f"[dim]{issue.location}[/dim]"
            )
            console.print(f"      {issue.detail}")
        total_issues += len(report.issues)

    if total_issues == 0:
        console.print("\n[green]Clean — all multi-disc layouts are intact.[/green]")
    else:
        console.print(f"\n[yellow]{total_issues}[/yellow] disc issue(s) total.")


@cli.command("verify")
@click.option("--system", "-s", required=True, help="System to verify.")
@click.option("--dat", "dat_path", type=click.Path(exists=True), required=True,
              help="No-Intro / Redump / TOSEC DAT XML file.")
@click.option("--show-good", is_flag=True,
              help="Also list verified-good ROMs (default: only problems).")
def verify_cmd(system, dat_path, show_good):
    """Verify ROM file integrity against a No-Intro / Redump DAT.

    \b
    Each ROM is matched by SHA1, then CRC32, then size+name. Statuses:
      good     — exact match
      renamed  — hash matches but the filename differs from the DAT
      bad      — size matches a known entry but hashes don't
      unknown  — DAT doesn't list anything of this size

    Hashing is lazy: a file whose size is absent from the DAT skips
    hashing entirely so unknown homebrew won't slow the scan down.
    """
    from .verify import verify_system

    config = _cfg()
    _check_config(config)

    report = verify_system(system, Path(dat_path), Path(config.roms_dir))

    console.print(Panel(f" verify: {system} ", style="bold blue"))
    if not report.entries:
        console.print(f"[yellow]No files to verify under {Path(config.roms_dir) / system}[/yellow]")
        return

    style = {
        "good": "green",
        "renamed": "yellow",
        "bad": "red",
        "unknown": "dim",
    }
    tbl = Table(box=box.SIMPLE)
    tbl.add_column("Status", style="cyan", width=8)
    tbl.add_column("File", style="yellow")
    tbl.add_column("Detail")
    for e in report.entries:
        if e.status == "good" and not show_good:
            continue
        try:
            rel = e.path.relative_to(Path(config.roms_dir) / system)
        except ValueError:
            rel = e.path
        tbl.add_row(
            f"[{style.get(e.status, 'white')}]{e.status}[/{style.get(e.status, 'white')}]",
            str(rel),
            e.detail or (e.expected_name or ""),
        )
    console.print(tbl)
    summary = ", ".join(
        f"{k}: {v}" for k, v in sorted(report.summary.items())
    )
    console.print(f"\n[bold]Summary:[/bold] {summary}")


@cli.command("stats")
@click.option("--system", "-s", default=None)
@click.option("--all", "all_systems", is_flag=True, default=True,
              help="Aggregate across all systems (default).")
def stats_cmd(system, all_systems):
    """Coverage dashboard: % of games with metadata + media per system.

    \b
    Reuses the audit pipeline so figures match what `spindoctor audit`
    reports. Useful for spotting which systems still need attention.
    """
    from .stats import collect_stats, top_missing_media

    config = _cfg()
    _check_config(config)
    if system:
        systems = [system]
    else:
        systems = _resolve_systems(config, None, True)

    report = collect_stats(systems, config)
    if not report.per_system:
        console.print("[yellow]No systems found.[/yellow]")
        return

    tbl = Table(title="Coverage by system", box=box.ROUNDED)
    tbl.add_column("System", style="cyan")
    tbl.add_column("ROMs", justify="right")
    tbl.add_column("DB", justify="right")
    tbl.add_column("Matched", justify="right")
    tbl.add_column("Metadata", justify="right")
    tbl.add_column("Media", justify="right")
    for s in report.per_system:
        tbl.add_row(
            s.system,
            str(s.total_roms),
            str(s.total_db_entries),
            f"{s.rom_coverage:.0%}",
            f"{s.metadata_coverage:.0%}",
            f"{s.media_coverage:.0%}",
        )
    console.print(tbl)

    grand = (
        f"\n[bold]Totals:[/bold] {report.total_roms} ROMs · "
        f"{report.total_db_entries} DB entries across "
        f"{len(report.per_system)} system(s)"
    )
    console.print(grand)

    missing = top_missing_media(report)
    if missing:
        console.print("\n[bold]Top missing media types[/bold]")
        for media_type, count in missing:
            console.print(f"  · [cyan]{media_type}[/cyan] — {count} game(s)")


# ─── fav / recent / tools ─────────────────────────────────────────────────────

@cli.group("fav")
def fav_group():
    """Manage the cross-system Favorites wheel.

    \b
    The Favorites system is a synthetic HyperSpin system whose database
    is regenerated from ~/.spindoctor/favorites.json. Each entry there is
    a (source_system, rom_name) pair. After 'fav rebuild' you'll see one
    unified wheel inside HyperSpin containing favorites picked from any
    number of source systems.
    """


@fav_group.command("add")
@click.argument("system_name")
@click.argument("rom_name")
@click.option("--display-name", default=None,
              help="Override the wheel display name (default: ROM name).")
def fav_add(system_name, rom_name, display_name):
    """Add a favorite. Run [cyan]fav rebuild[/cyan] afterwards to update HyperSpin."""
    from .favorites import add, load_store, save_store
    store = load_store()
    if add(store, system_name, rom_name, display_name):
        save_store(store)
        console.print(f"[green]+[/green] {system_name} :: {rom_name}")
    else:
        console.print(f"[yellow]already a favorite:[/yellow] {system_name} :: {rom_name}")


@fav_group.command("remove")
@click.argument("system_name")
@click.argument("rom_name")
def fav_remove(system_name, rom_name):
    """Remove a favorite from the cross-system wheel."""
    from .favorites import load_store, remove, save_store
    store = load_store()
    if remove(store, system_name, rom_name):
        save_store(store)
        console.print(f"[green]-[/green] {system_name} :: {rom_name}")
    else:
        console.print(f"[yellow]not a favorite:[/yellow] {system_name} :: {rom_name}")


@fav_group.command("list")
def fav_list():
    """List every entry in the favorites store."""
    from .favorites import load_store
    store = load_store()
    if not store.entries:
        console.print("[dim]No favorites set.[/dim]")
        return
    tbl = Table(title=f"Favorites → '{store.target_system}'", box=box.ROUNDED)
    tbl.add_column("System", style="cyan")
    tbl.add_column("ROM", style="yellow")
    tbl.add_column("Display name")
    tbl.add_column("Added", style="dim")
    for e in store.entries:
        tbl.add_row(e.system, e.rom_name, e.display_name, e.added)
    console.print(tbl)


@fav_group.command("sync")
def fav_sync():
    """Pull HyperSpin's per-system favorites into the cross-system store.

    HyperSpin's built-in F-key writes per-system Favorites lists. This
    command merges them into your cross-system favorites so you can use
    either workflow.
    """
    from .favorites import load_store, save_store, sync_native
    config = _cfg()
    _check_config(config)
    store = load_store()
    n = sync_native(store, config)
    save_store(store)
    console.print(f"[green]+[/green] synced {n} new favorite(s)")


@fav_group.command("rebuild")
@click.option("--media-mode",
              type=click.Choice(["link", "symlink", "copy", "auto", "none"]),
              default="auto",
              help="How to mirror media into the Favorites system.")
def fav_rebuild(media_mode):
    """Regenerate the Favorites HyperSpin system + media + launchers.

    \b
    Idempotent — safe to run on every boot. Steps:
      1. Write Databases/<Favorites>/<Favorites>.xml from favorites.json
      2. Mirror media (hardlinks by default; falls back to copy)
      3. Write per-game PCLauncher INIs that route via RocketLauncher
    """
    from .favorites import load_store, rebuild
    from .medialink import LinkMode
    config = _cfg()
    _check_config(config)
    store = load_store()
    skip_media = media_mode == "none"
    mode = LinkMode.AUTO if skip_media else LinkMode(media_mode)
    summary = rebuild(store, config, media_mode=mode, skip_media=skip_media)
    _print_synth_summary("Favorites", summary)


@cli.group("recent")
def recent_group():
    """Manage the Recently Played wheel (auto-derived from RocketLauncher stats)."""


@recent_group.command("rebuild")
@click.option("--limit", type=int, default=20,
              help="Number of recent games to keep (default 20).")
@click.option("--target-system", default="Recently Played",
              help="Synthetic system name (default 'Recently Played').")
@click.option("--media-mode",
              type=click.Choice(["link", "symlink", "copy", "auto", "none"]),
              default="auto")
def recent_rebuild(limit, target_system, media_mode):
    """Rebuild the Recently Played system from RocketLauncher Statistics.ini files.

    \b
    Reads RocketLauncher's launch stats (no extra hooks required), keeps
    the most-recent N games across every system, and regenerates the
    HyperSpin system + media mirrors + per-game launchers.
    """
    from .medialink import LinkMode
    from .recent import rebuild
    config = _cfg()
    _check_config(config)
    skip_media = media_mode == "none"
    mode = LinkMode.AUTO if skip_media else LinkMode(media_mode)
    summary = rebuild(
        config,
        target_system=target_system,
        limit=limit,
        media_mode=mode,
        skip_media=skip_media,
    )
    _print_synth_summary("Recently Played", summary)


@recent_group.command("list")
@click.option("--limit", type=int, default=20)
def recent_list(limit):
    """Print the top-N games by last-played timestamp."""
    from .recent import collect_play_records, top_recent
    config = _cfg()
    records = top_recent(collect_play_records(config), limit=limit)
    if not records:
        console.print("[dim]No play records found.[/dim]")
        return
    tbl = Table(title=f"Top {len(records)} recently played", box=box.ROUNDED)
    tbl.add_column("Last played", style="cyan")
    tbl.add_column("System")
    tbl.add_column("ROM", style="yellow")
    tbl.add_column("×", justify="right")
    for r in records:
        tbl.add_row(
            r.last_played.strftime("%Y-%m-%d %H:%M"),
            r.system, r.rom_name, str(r.play_count),
        )
    console.print(tbl)


def _print_synth_summary(label: str, summary) -> None:
    grid = Table.grid(padding=(0, 2))
    grid.add_row(f"[bold]{label} system:[/bold]", str(summary.target_system))
    grid.add_row("[cyan]Entries:[/cyan]", str(summary.entries))
    grid.add_row("[cyan]Pruned:[/cyan]", str(summary.pruned))
    grid.add_row("[cyan]Database:[/cyan]", str(summary.db_path or "[dim]<not written>[/dim]"))
    grid.add_row(
        "[cyan]Media:[/cyan]",
        f"linked={summary.media_linked} "
        f"copied={summary.media_copied} "
        f"skipped={summary.media_skipped}",
    )
    grid.add_row("[cyan]Launchers:[/cyan]", str(summary.inis_written))
    console.print(grid)
    if summary.media_errors:
        console.print(f"[red]{len(summary.media_errors)} media error(s):[/red]")
        for e in summary.media_errors[:5]:
            console.print(f"  [red]·[/red] {e}")


@cli.command("install-tools")
@click.option("--output-dir", type=click.Path(), default=None,
              help="Directory to write .bat helpers. Defaults to "
                   "<rocketlauncher_dir>/Modules/HyperLaunch/Tools/spindoctor.")
def install_tools(output_dir):
    """Install HyperSpin Tools menu wrappers for fav/recent rebuilds.

    \b
    Writes two .bat files that HyperSpin's Tools menu can call directly:

      \b
      • Refresh Favorites.bat       → spindoctor-fav rebuild
      • Refresh Recently Played.bat → spindoctor-recent rebuild

    Drop them into HyperSpin's Tools folder (or point HyperSpin at the
    output directory) so users can refresh the wheels from the cabinet
    without dropping to a console.
    """
    config = _cfg()
    if output_dir:
        out = Path(output_dir)
    elif config.rocketlauncher_dir:
        out = Path(config.rocketlauncher_dir) / "Modules" / "HyperLaunch" / "Tools" / "spindoctor"
    else:
        err_console.print("[red]No --output-dir and rocketlauncher_dir is unset.[/red]")
        sys.exit(1)
    out.mkdir(parents=True, exist_ok=True)

    bats = {
        "Refresh Favorites.bat":
            "@echo off\r\n"
            "REM Regenerates the cross-system HyperSpin Favorites wheel.\r\n"
            "spindoctor-fav rebuild\r\n"
            "if errorlevel 1 pause\r\n",
        "Refresh Recently Played.bat":
            "@echo off\r\n"
            "REM Regenerates the Recently Played wheel from RocketLauncher stats.\r\n"
            "spindoctor-recent rebuild\r\n"
            "if errorlevel 1 pause\r\n",
        "Refresh Both.bat":
            "@echo off\r\n"
            "spindoctor-fav rebuild\r\n"
            "spindoctor-recent rebuild\r\n"
            "if errorlevel 1 pause\r\n",
    }
    for name, body in bats.items():
        (out / name).write_text(body, encoding="utf-8")
    console.print(f"[green]+[/green] wrote {len(bats)} helper(s) to [cyan]{out}[/cyan]")
    console.print(
        "[dim]Add[/dim] [cyan]" + str(out) + "[/cyan] [dim]to HyperSpin's "
        "Tools folder, or register the .bat files in HyperHQ → Tools.[/dim]"
    )
    console.print(
        "[dim]Run on boot:[/dim] schedule [cyan]spindoctor-fav rebuild[/cyan] and "
        "[cyan]spindoctor-recent rebuild[/cyan] via Windows Task Scheduler "
        "(trigger: 'At log on')."
    )


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


# ─── cleanup ──────────────────────────────────────────────────────────────────

@cli.group("cleanup")
def cleanup_group():
    """Audit and remove SpinDoctor caches, manifests, and temp files.

    \b
    Subcommands:
      audit        Show how much disk each cache/manifest category uses.
      run          Remove files from selected categories (dry-run by default).
      categories   List every cleanup category and what it covers.

    Caches (match, media, metadata, listxml, preview) rebuild themselves on
    next use. Manifests and `.bak` backups are flagged unsafe — deleting
    them removes recovery and undo options. Use --include-unsafe or pick
    the category explicitly to remove those.
    """


def _cleanup_format_mtime(ts: Optional[float]) -> str:
    if ts is None:
        return "[dim]—[/dim]"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _cleanup_resolve_keys(
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    include_unsafe: bool,
) -> list[str]:
    """Expand --include / --exclude flag values into concrete category keys.

    Special tokens: ``all`` (every category), ``safe`` (safe-by-default
    categories only). ``unsafe`` is rejected — pick the unsafe category by
    name so users opt-in deliberately.
    """
    from .cleanup import CATEGORY_KEYS, scan
    from .config import Config as _Cfg

    safe_keys = [r.key for r in scan(_Cfg()).values() if r.safe]

    chosen: list[str] = []
    for token in include:
        for raw in token.split(","):
            t = raw.strip().lower()
            if not t:
                continue
            if t == "all":
                chosen.extend(CATEGORY_KEYS)
            elif t == "safe":
                chosen.extend(safe_keys)
            elif t in CATEGORY_KEYS:
                chosen.append(t)
            else:
                err_console.print(f"[red]Unknown category:[/red] {t}")
                sys.exit(2)

    excluded: set[str] = set()
    for token in exclude:
        for raw in token.split(","):
            t = raw.strip().lower()
            if t and t in CATEGORY_KEYS:
                excluded.add(t)

    seen: set[str] = set()
    resolved: list[str] = []
    for k in chosen:
        if k in excluded or k in seen:
            continue
        seen.add(k)
        resolved.append(k)

    if not include_unsafe:
        from .cleanup import scan as _scan
        unsafe = {r.key for r in _scan(_Cfg()).values() if not r.safe}
        # Drop unsafe keys only if they came in via 'all' / 'safe'.
        # Direct opt-in (named in --include) keeps them.
        explicit = set()
        for token in include:
            for raw in token.split(","):
                t = raw.strip().lower()
                if t in CATEGORY_KEYS:
                    explicit.add(t)
        resolved = [k for k in resolved if k not in unsafe or k in explicit]

    return resolved


@cleanup_group.command("categories")
def cleanup_categories():
    """List every cleanup category and its purpose."""
    from .cleanup import scan
    config = _cfg()
    reports = scan(config)
    tbl = Table(title="Cleanup categories", box=box.ROUNDED)
    tbl.add_column("Key", style="cyan")
    tbl.add_column("Label")
    tbl.add_column("Safe", justify="center")
    tbl.add_column("Description")
    for r in reports.values():
        tbl.add_row(
            r.key,
            r.label,
            "[green]yes[/green]" if r.safe else "[yellow]no[/yellow]",
            r.description,
        )
    console.print(tbl)
    console.print(
        "\n[dim]Use [cyan]spindoctor cleanup audit[/cyan] to see how much disk each one uses, "
        "or [cyan]spindoctor cleanup run --include <key>[/cyan] to remove.[/dim]"
    )


@cleanup_group.command("audit")
@click.option("--detail", is_flag=True, help="List every individual file under each category.")
@click.option("--category", "-c", "categories", multiple=True,
              help="Limit audit to one or more category keys (repeatable, comma-separated).")
def cleanup_audit(detail: bool, categories: tuple[str, ...]):
    """Show disk usage for each SpinDoctor cache and manifest category.

    \b
    Examples:
      spindoctor cleanup audit
      spindoctor cleanup audit --detail
      spindoctor cleanup audit -c metadata-cache -c db-backups
    """
    from .cleanup import CATEGORY_KEYS, format_size, scan

    keys: Optional[list[str]] = None
    if categories:
        keys = []
        for token in categories:
            for raw in token.split(","):
                t = raw.strip().lower()
                if not t:
                    continue
                if t not in CATEGORY_KEYS:
                    err_console.print(f"[red]Unknown category:[/red] {t}")
                    sys.exit(2)
                keys.append(t)

    config = _cfg()
    reports = scan(config, keys=keys)

    summary = Table(title="SpinDoctor cleanup audit", box=box.ROUNDED)
    summary.add_column("Category", style="cyan")
    summary.add_column("Safe", justify="center")
    summary.add_column("Files", justify="right")
    summary.add_column("Size", justify="right")
    summary.add_column("Oldest")
    summary.add_column("Newest")
    summary.add_column("Location", style="dim")

    grand_bytes = 0
    grand_files = 0
    for r in reports.values():
        grand_bytes += r.total_bytes
        grand_files += r.count
        summary.add_row(
            r.key,
            "[green]✓[/green]" if r.safe else "[yellow]![/yellow]",
            str(r.count) if r.count else "[dim]0[/dim]",
            format_size(r.total_bytes) if r.count else "[dim]—[/dim]",
            _cleanup_format_mtime(r.oldest_mtime),
            _cleanup_format_mtime(r.newest_mtime),
            r.location,
        )

    console.print(summary)
    console.print(
        f"\n[bold]Total:[/bold] {grand_files} file(s), "
        f"[bold]{format_size(grand_bytes)}[/bold] across {len(reports)} categor"
        f"{'y' if len(reports) == 1 else 'ies'}."
    )

    notes = [(r.label, r.note) for r in reports.values() if r.note and r.count]
    if notes:
        console.print("\n[dim]Notes:[/dim]")
        for label, note in notes:
            console.print(f"  [yellow]•[/yellow] [bold]{escape(label)}[/bold]: {note}")

    if detail:
        for r in reports.values():
            if not r.count:
                continue
            console.print(f"\n[bold]{escape(r.label)}[/bold]  [dim]({r.key})[/dim]")
            tbl = Table(box=box.SIMPLE)
            tbl.add_column("Modified", style="dim")
            tbl.add_column("Size", justify="right")
            tbl.add_column("Path")
            for f in sorted(r.files, key=lambda x: x.mtime, reverse=True):
                tbl.add_row(
                    _cleanup_format_mtime(f.mtime),
                    format_size(f.size),
                    str(f.path),
                )
            console.print(tbl)


@cleanup_group.command("run")
@click.option("--include", "-i", multiple=True,
              help="Categories to clean. Use 'all', 'safe', or a key (repeatable, comma-separated).")
@click.option("--exclude", "-x", multiple=True,
              help="Categories to skip (repeatable, comma-separated).")
@click.option("--include-unsafe", is_flag=True,
              help="With --include all/safe, also include unsafe categories (db-backups, manifests).")
@click.option("--older-than", type=int, default=None, metavar="DAYS",
              help="Only remove files older than DAYS (by mtime).")
@click.option("--keep-recent", type=int, default=None, metavar="N",
              help="Keep the N newest files in each category, remove the rest.")
@click.option("--apply", "apply_changes", is_flag=True,
              help="Actually delete. Without this flag the command runs as a dry-run.")
@click.option("--prune-empty-dirs", is_flag=True,
              help="After deleting files, remove now-empty cache directories.")
@click.option("--yes", "-y", "skip_confirm", is_flag=True,
              help="Skip the interactive confirmation prompt.")
def cleanup_run(
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    include_unsafe: bool,
    older_than: Optional[int],
    keep_recent: Optional[int],
    apply_changes: bool,
    prune_empty_dirs: bool,
    skip_confirm: bool,
):
    """Remove cached files. Defaults to dry-run; pass --apply to actually delete.

    \b
    Examples:
      # Preview what 'all safe caches' would remove
      spindoctor cleanup run --include safe
      \b
      # Actually clear API + match caches
      spindoctor cleanup run --include metadata-cache,match-cache --apply
      \b
      # Trim DB backups to the 5 most recent per location
      spindoctor cleanup run --include db-backups --keep-recent 5 --apply
      \b
      # Drop scraper cache files older than 90 days
      spindoctor cleanup run --include metadata-cache --older-than 90 --apply
      \b
      # Wipe everything (caution: includes backups and undo manifests)
      spindoctor cleanup run --include all --include-unsafe --apply

    Categories: see [cyan]spindoctor cleanup categories[/cyan].
    """
    from .cleanup import filter_files, format_size, prune_empty_dirs as _prune
    from .cleanup import remove as _remove
    from .cleanup import scan

    if not include:
        err_console.print(
            "[red]No --include specified.[/red] "
            "Try [cyan]--include safe[/cyan] for caches, or "
            "[cyan]spindoctor cleanup categories[/cyan] for the full list."
        )
        sys.exit(2)

    keys = _cleanup_resolve_keys(include, exclude, include_unsafe)
    if not keys:
        err_console.print("[yellow]No categories selected after applying filters.[/yellow]")
        sys.exit(2)

    config = _cfg()
    reports = scan(config, keys=keys)

    pending: list[tuple[str, list]] = []
    total_files = 0
    total_bytes = 0
    for key in keys:
        report = reports[key]
        targets = filter_files(
            report.files,
            older_than_days=older_than,
            keep_recent=keep_recent,
        )
        if targets:
            pending.append((key, targets))
            total_files += len(targets)
            total_bytes += sum(f.size for f in targets)

    mode = "[bold red]APPLY[/bold red]" if apply_changes else "[bold yellow]DRY-RUN[/bold yellow]"
    console.print(f"\n{mode} — {total_files} file(s), {format_size(total_bytes)} selected.\n")

    if not pending:
        console.print("[dim]Nothing to remove.[/dim]")
        return

    plan_tbl = Table(box=box.ROUNDED)
    plan_tbl.add_column("Category", style="cyan")
    plan_tbl.add_column("Files", justify="right")
    plan_tbl.add_column("Size", justify="right")
    plan_tbl.add_column("Notes", style="dim")
    for key, targets in pending:
        report = reports[key]
        notes = []
        if not report.safe:
            notes.append("[yellow]unsafe[/yellow]")
        if report.note:
            notes.append(report.note)
        plan_tbl.add_row(
            key,
            str(len(targets)),
            format_size(sum(f.size for f in targets)),
            " · ".join(notes) if notes else "",
        )
    console.print(plan_tbl)

    if not apply_changes:
        console.print(
            "\n[dim]Dry-run only. Re-run with [cyan]--apply[/cyan] to delete.[/dim]"
        )
        if total_files:
            console.print(
                "[dim]Tip: add [cyan]--include[/cyan] '<category>' or [cyan]"
                "--keep-recent N[/cyan] to narrow the selection.[/dim]"
            )
        return

    if not skip_confirm:
        unsafe_in_plan = [k for k, _ in pending if not reports[k].safe]
        prompt = f"Permanently delete {total_files} file(s) ({format_size(total_bytes)})?"
        if unsafe_in_plan:
            prompt = (
                f"[!] Plan includes unsafe categories: {', '.join(unsafe_in_plan)}.\n"
                + prompt
            )
        if not click.confirm(prompt, default=False):
            console.print("[yellow]Cancelled — nothing was deleted.[/yellow]")
            return

    grand_removed = 0
    grand_bytes = 0
    grand_failed: list[tuple] = []
    pruned_roots: list[Path] = []
    for key, targets in pending:
        result = _remove(targets, dry_run=False)
        grand_removed += result.count_removed
        grand_bytes += result.bytes_freed
        grand_failed.extend(result.failed)
        location = reports[key].location
        if Path(location).exists():
            pruned_roots.append(Path(location))
        console.print(
            f"  [green]✓[/green] {key}: removed {result.count_removed} "
            f"({format_size(result.bytes_freed)})"
            + (f" — [red]{len(result.failed)} failed[/red]" if result.failed else "")
        )

    if prune_empty_dirs:
        n = _prune(pruned_roots)
        if n:
            console.print(f"  [green]✓[/green] Pruned {n} empty director{'y' if n == 1 else 'ies'}.")

    console.print(
        f"\n[green]✓ Cleanup complete.[/green] Removed {grand_removed} file(s), "
        f"freed [bold]{format_size(grand_bytes)}[/bold]."
    )
    if grand_failed:
        console.print(f"[red]{len(grand_failed)} file(s) could not be removed:[/red]")
        for path, err in grand_failed[:10]:
            console.print(f"  [red]·[/red] {path}: {err}")


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
@click.option("--no-cache", is_flag=True,
              help="Force-refresh: ignore the disk-cached API responses.")
@click.option("--clear-cache", is_flag=True,
              help="Delete cached API responses (for the targeted system or all) and exit.")
@click.option("--dry-run", is_flag=True)
@click.option("--output-dir", type=click.Path(), default=None)
def fetch_meta(system, all_systems, source, fetch_all,
               interactive, threshold, no_cache, clear_cache,
               dry_run, output_dir):
    """Fetch and update game metadata in the Hyperspin XML databases.

    For each game with missing fields, SpinDoctor queries the metadata source.
    When a ROM name contains variant tags (region, version, revision) those are
    normalised before searching so each ROM variant is looked up individually.
    If multiple candidates are found you can select the correct one interactively;
    your choice is saved to ~/.spindoctor/match_cache/ and reused on future runs.
    """
    config = _cfg()
    _check_config(config)

    from .matcher import choose_match, partition_by_confidence
    from .scraper import MetadataError, build_client, build_metadata_cache

    if clear_cache:
        cache = build_metadata_cache(config)
        src = source or None
        sys_name = system if system else None
        n = cache.clear(source=src, system=sys_name)
        scope = (
            f"all systems for {src}" if src and not sys_name else
            f"{sys_name} ({src or 'all sources'})" if sys_name else
            "all sources"
        )
        console.print(f"[green]✓[/green] Cleared {n} cache file(s) for {scope}.")
        return

    systems = _resolve_systems(config, system, all_systems)

    do_interactive = config.interactive_matching if interactive is None else interactive
    match_thresh = threshold if threshold is not None else config.match_threshold

    try:
        client = build_client(config, source, use_cache=not no_cache)
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
@click.option("--pick-media", "pick_media", is_flag=True,
              help="Interactively preview & pick when a media slot has multiple "
                   "candidates (different regions / artwork variants).")
@click.option("--dry-run", is_flag=True)
@click.option("--output-dir", type=click.Path(), default=None)
def fetch_media(system, all_systems, types, source, overwrite, pick_media, dry_run, output_dir):
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
    workers = max(1, config.max_concurrent_downloads)

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
            f"types: {', '.join(media_types)} · "
            f"[dim]workers={workers}[/dim]"
        )

        # ── Phase 1: gather metadata + flatten download jobs ────────────────
        all_jobs: list[tuple[str, str, str]] = []
        # When --pick-media is set we keep the candidate list and run
        # downloads sequentially so the picker can prompt interactively.
        pick_jobs: list[tuple[str, str, list]] = []
        total_fail = 0
        with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                      BarColumn(), TextColumn("{task.completed}/{task.total}"),
                      console=console) as prog:
            task = prog.add_task("Resolving metadata…", total=len(games))
            for game in games:
                prog.update(task, description=f"[dim]meta · {game.name[:35]}[/dim]")
                try:
                    meta = client.fetch_with_search(game.name, sys_name)
                    chosen = meta[0] if meta else None
                    if not chosen:
                        total_fail += len(media_types)
                        prog.advance(task)
                        continue
                    if pick_media:
                        for mt in media_types:
                            cands = chosen.media_candidates.get(mt, [])
                            if cands:
                                pick_jobs.append((game.name, mt, cands))
                            else:
                                # Fall back to the legacy single URL if any
                                url = downloader.jobs_for_metadata(
                                    game.name, chosen, media_types=[mt],
                                )[0][2]
                                all_jobs.append((game.name, mt, url))
                    else:
                        all_jobs.extend(
                            downloader.jobs_for_metadata(
                                game.name, chosen, media_types=media_types,
                            )
                        )
                except MetadataError as e:
                    console.print(f"  [red]Error [{game.name}]:[/red] {e}")
                    total_fail += len(media_types)
                prog.advance(task)

        # ── Phase 2: parallel downloads (auto path) + sequential picker ─────
        total_ok = total_skip = 0
        if dry_run:
            for game_name, mt, url in all_jobs:
                dest = downloader.media_path(sys_name, game_name, mt)
                note = "[dry-run]" if url else "[no URL available]"
                console.print(f"  [dim]+[/dim] {game_name} · {mt}  {note}  → {dest}")
                if url:
                    total_ok += 1
                else:
                    total_skip += 1
            for game_name, mt, cands in pick_jobs:
                dest = downloader.media_path(sys_name, game_name, mt)
                console.print(
                    f"  [dim]+[/dim] {game_name} · {mt}  [dry-run · {len(cands)} candidates]  → {dest}"
                )
                total_ok += 1
        else:
            if all_jobs:
                with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                              BarColumn(), TextColumn("{task.completed}/{task.total}"),
                              console=console) as prog:
                    task = prog.add_task("Downloading…", total=len(all_jobs))

                    def _on_done(r):
                        nonlocal total_ok, total_skip, total_fail
                        if r.skipped:
                            total_skip += 1
                        elif r.success:
                            total_ok += 1
                        else:
                            total_fail += 1
                        prog.advance(task)

                    downloader.download_many(
                        all_jobs, sys_name,
                        overwrite=overwrite,
                        max_workers=workers,
                        on_complete=_on_done,
                    )

            for game_name, mt, cands in pick_jobs:
                dest = downloader.media_path(sys_name, game_name, mt)
                r = downloader.download_with_picker(
                    game_name, sys_name, mt, cands, dest,
                    interactive=True, overwrite=overwrite,
                )
                if r.skipped:
                    total_skip += 1
                elif r.success:
                    total_ok += 1
                else:
                    total_fail += 1

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
@click.option("--global-emulators/--no-global-emulators", "gen_global", default=True,
              help="Write Settings/Global Emulators.ini if missing (default: on).")
@click.option("--overwrite-global", is_flag=True,
              help="Overwrite an existing Global Emulators.ini "
                   "(default: leave user customisations alone).")
@click.option("--dry-run", is_flag=True)
@click.option("--output-dir", type=click.Path(), default=None,
              help="Write all output here instead of in-place.")
def generate_config(all_systems, system, gen_rl, gen_menu, gen_stubs,
                    gen_global, overwrite_global, dry_run, output_dir):
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
        generate_global_emulators_ini,
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

    if gen_global:
        console.print(f"\n[blue bold]Global Emulators.ini[/blue bold]")
        if dry_run:
            rl_base = out_base or (Path(config.rocketlauncher_dir) if config.rocketlauncher_dir else None)
            if rl_base:
                target = rl_base / "Settings" / "Global Emulators.ini"
                action = "would overwrite" if (target.exists() and overwrite_global) else (
                    "exists — would skip" if target.exists() else "would create"
                )
                console.print(f"  [dim]{action}:[/dim] {target}")
            else:
                console.print("  [dim]rocketlauncher_dir not configured — skipping.[/dim]")
        else:
            try:
                p, status = generate_global_emulators_ini(
                    config, out_base, overwrite=overwrite_global
                )
                if status == "skipped-exists":
                    console.print(
                        f"  [dim]Skipped (exists):[/dim] {p}  "
                        f"[dim](use --overwrite-global to replace)[/dim]"
                    )
                else:
                    console.print(f"  [green]✓[/green] {status}: {p}")
            except ValueError as e:
                console.print(f"  [red]{e}[/red]")

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


# ─── doctor ───────────────────────────────────────────────────────────────────

@cli.command("doctor")
@click.option("--fix", is_flag=True,
              help="Apply safe fixes: prune stale match cache, create missing "
                   "media folders, regen Global Emulators.ini if missing.")
def doctor(fix):
    """Self-diagnose: paths, binaries, DB integrity, cache hygiene, integrations.

    Pass --fix to apply safe, idempotent repairs (never deletes ROMs/DBs/media).
    """
    from rich.tree import Tree
    from .health import Status, run_health_checks

    config = _cfg()
    report = run_health_checks(config, fix=fix)

    icon_for = {
        Status.OK: "[green]✓[/green]",
        Status.WARN: "[yellow]⚠[/yellow]",
        Status.FAIL: "[red]✗[/red]",
        Status.INFO: "[dim]i[/dim]",
    }

    tree = Tree("[bold]SpinDoctor health[/bold]")

    def render(check, parent):
        label = f"{icon_for[check.status]} [bold]{check.name}[/bold]"
        if check.detail:
            label += f"  [dim]·[/dim] {check.detail}"
        node = parent.add(label)
        if check.fix and not fix:
            node.add(f"[dim]fix:[/dim] {check.fix}")
        for ch in check.children:
            render(ch, node)

    for c in report.checks:
        render(c, tree)

    console.print(tree)

    if report.fixes_applied:
        console.print("\n[green bold]Fixes applied:[/green bold]")
        for f in report.fixes_applied:
            console.print(f"  [green]+[/green] {f}")

    overall = report.overall()
    console.print(
        f"\nOverall: {icon_for[overall]} "
        f"[bold]{overall.value.upper()}[/bold]"
    )
    if overall == Status.FAIL:
        sys.exit(2)


# ─── ledblinky ────────────────────────────────────────────────────────────────

@cli.group("ledblinky")
def ledblinky_group():
    """Generate and audit LEDBlinky controls.ini / colors.ini."""


@ledblinky_group.command("generate")
@click.option("--system", "-s", default="MAME",
              help="System to generate for (default: MAME).")
@click.option("--overwrite", is_flag=True,
              help="Overwrite existing entries (default: keep community-maintained ones).")
@click.option("--dry-run", is_flag=True)
@click.option("--output-dir", type=click.Path(), default=None,
              help="Write to this directory instead of <ledblinky_dir>.")
def ledblinky_generate(system, overwrite, dry_run, output_dir):
    """Generate / merge LEDBlinky controls.ini and colors.ini.

    Strategy: existing entries from <ledblinky_dir> are preserved verbatim;
    ROMs not yet covered get synthesized entries derived from
    `mame -listxml`.
    """
    config = _cfg()
    _check_config(config)

    if not config.mame_executable:
        err_console.print(
            "[red]mame_executable is not configured.[/red]  "
            "Run: spindoctor config set mame_executable /path/to/mame"
        )
        sys.exit(1)

    from .audit import scan_roms
    from .ledblinky import generate_for_roms

    roms = scan_roms(system, Path(config.roms_dir))
    if not roms:
        console.print(f"[yellow]No ROMs found for system {system}.[/yellow]")
        return

    out_path = Path(output_dir) if output_dir else None
    try:
        result = generate_for_roms(
            config,
            rom_names=sorted(roms.keys()),
            output_dir=out_path,
            overwrite_existing=overwrite,
            dry_run=dry_run,
        )
    except ValueError as e:
        err_console.print(f"[red]{e}[/red]")
        sys.exit(1)

    label = "[yellow]would write[/yellow]" if dry_run else "[green]wrote[/green]"
    console.print(f"\n{label} controls.ini → {result.controls_path}")
    console.print(f"{label} colors.ini   → {result.colors_path}")
    console.print(
        f"  Synthesised: [cyan]{result.controls_synthesised}[/cyan] controls, "
        f"[cyan]{result.colors_synthesised}[/cyan] colors"
    )
    console.print(
        f"  Kept existing: [dim]{result.controls_existing_kept}[/dim] controls, "
        f"[dim]{result.colors_existing_kept}[/dim] colors"
    )
    if result.skipped_no_input:
        console.print(
            f"  Skipped (no -listxml input data): [yellow]{result.skipped_no_input}[/yellow]"
        )


@ledblinky_group.command("audit")
@click.option("--system", "-s", default="MAME")
def ledblinky_audit(system):
    """Show LEDBlinky coverage per ROM (covered / would-synth / no-input / missing)."""
    config = _cfg()
    _check_config(config)

    from .audit import scan_roms
    from .ledblinky import audit_coverage

    roms = scan_roms(system, Path(config.roms_dir))
    if not roms:
        console.print(f"[yellow]No ROMs found for system {system}.[/yellow]")
        return

    rows = audit_coverage(config, sorted(roms.keys()))

    counts = {"covered": 0, "would-synth": 0, "no-input": 0, "missing": 0}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1

    summary = Table(title=f"LEDBlinky coverage — {system}", box=box.ROUNDED)
    summary.add_column("Status", style="cyan")
    summary.add_column("Count", justify="right")
    summary.add_row("[green]Covered (controls.ini + colors.ini)[/green]", str(counts["covered"]))
    summary.add_row("[yellow]Would synthesise from -listxml[/yellow]", str(counts["would-synth"]))
    summary.add_row("[dim]Game has no input[/dim]", str(counts["no-input"]))
    summary.add_row("[red]Not in -listxml[/red]", str(counts["missing"]))
    console.print(summary)

    missing_or_synth = [r for r in rows if r.status in ("would-synth", "missing")]
    if missing_or_synth:
        tbl = Table(box=box.SIMPLE, show_header=True)
        tbl.add_column("ROM", style="cyan")
        tbl.add_column("In -listxml", justify="center")
        tbl.add_column("controls.ini", justify="center")
        tbl.add_column("colors.ini", justify="center")
        tbl.add_column("Status")
        for r in missing_or_synth[:60]:
            tbl.add_row(
                r.rom_name,
                _status(r.in_listxml),
                _status(r.in_controls_ini),
                _status(r.in_colors_ini),
                r.status,
            )
        console.print(tbl)
        if len(missing_or_synth) > 60:
            console.print(f"  [dim]... and {len(missing_or_synth) - 60} more[/dim]")


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


# ─── ledblinky: HyperSpin Search compatibility (check / fix) ──────────────────

@ledblinky_group.command("check")
@click.option("--menus", default="Search",
              help="Comma-separated special menus to check. Default: Search.")
def ledblinky_check(menus):
    """Scan HyperSpin + LedBlinky configs for known Search-menu conflicts."""
    from . import ledblinky as lb

    config = _cfg()
    menu_list = [m.strip() for m in menus.split(",") if m.strip()]
    result = lb.scan(config, menus=menu_list)

    tbl = Table(title="LedBlinky compatibility scan", box=box.ROUNDED)
    tbl.add_column("Check", style="cyan")
    tbl.add_column("Result")

    tbl.add_row(
        "ledblinky_dir",
        f"{_status(result['ledblinky_dir_exists'])} "
        f"{config.ledblinky_dir or '[dim]<not set>[/dim]'}",
    )
    tbl.add_row(
        "LEDBlinkyControls.xml",
        f"{_status(result['controls_xml_exists'])} "
        f"{result['controls_xml_path'] or '[dim]—[/dim]'}",
    )

    for info in result["menu_inis"]:
        hooks = info["has_hooks"]
        in_xml = info["has_controls_entry"]
        tbl.add_row(
            f"{info['menu']} menu INI",
            f"exists={_status(info['exists'])}  "
            f"hooks={'[red]yes[/red]' if hooks else '[green]no[/green]'}  "
            f"in controls.xml={_status(in_xml)}",
        )

    if result["global_settings_ini"]:
        tbl.add_row(
            "HyperSpin Settings.ini hooks",
            "[dim]present (expected — left untouched)[/dim]"
            if result["global_settings_has_hooks"]
            else "[dim]absent[/dim]",
        )

    console.print(tbl)

    if result["ok"]:
        console.print("[green]✓ No issues detected.[/green]")
        return

    console.print("\n[yellow bold]Issues:[/yellow bold]")
    for issue in result["issues"]:
        console.print(f"  • {issue}")
    console.print(
        "\nRun [cyan]spindoctor ledblinky fix --dry-run[/cyan] to preview the patch."
    )


@ledblinky_group.command("fix")
@click.option("--dry-run", is_flag=True,
              help="Show what would change without writing anything.")
@click.option("--output-dir", type=click.Path(), default=None,
              help="Write patched files here instead of in-place.")
@click.option("--no-backup", is_flag=True,
              help="Skip .bak backups when writing in-place.")
@click.option("--menus", default="Search",
              help="Comma-separated special menus to patch. Default: Search. "
                   "Other options: Genre, Favorites.")
def ledblinky_fix(dry_run, output_dir, no_backup, menus):
    """Patch LEDBlinkyControls.xml + HyperSpin Search Settings.ini for compatibility.

    \b
    Two patches are applied:
      1. Add a stub entry to LEDBlinkyControls.xml for each requested menu
         so LedBlinky's lookup succeeds when the special menu activates.
      2. Comment out the Start_Hyperspin_Process / Exit_Hyperspin_Process
         lines in the per-menu Settings.ini that point at LEDBlinky.exe.

    \b
    Examples:
      spindoctor ledblinky fix --dry-run
      spindoctor ledblinky fix
      spindoctor ledblinky fix --menus Search,Genre,Favorites
      spindoctor ledblinky fix --output-dir D:\\Output
    """
    from . import ledblinky as lb

    config = _cfg()
    _check_config(config)
    out_base = config.effective_output_dir(output_dir)
    menu_list = [m.strip() for m in menus.split(",") if m.strip()]

    if dry_run:
        console.print("[yellow bold][DRY RUN][/yellow bold] No files will be written.")

    result = lb.apply_fix(
        config,
        output_base=out_base,
        dry_run=dry_run,
        backup=not no_backup,
        menus=menu_list,
    )

    cx = result["controls_xml"]
    console.print("\n[blue bold]LEDBlinkyControls.xml[/blue bold]")
    if cx is None:
        console.print("  [dim]skipped (ledblinky_dir not set)[/dim]")
    elif cx["added"]:
        verb = "Would add" if dry_run or not cx["wrote"] else "Added"
        console.print(f"  [green]{verb}[/green] entries: {', '.join(cx['added'])}")
        console.print(f"  Path: {cx['path']}")
    else:
        console.print("  [green]✓ Already contains all requested menu entries.[/green]")

    console.print("\n[blue bold]HyperSpin per-menu INIs[/blue bold]")
    tbl = Table(box=box.SIMPLE, show_header=True)
    tbl.add_column("Menu", style="cyan")
    tbl.add_column("Path")
    tbl.add_column("Hook lines", justify="right")
    tbl.add_column("Status")
    for info in result["menu_inis"]:
        if info.get("error"):
            tbl.add_row(info["menu"], str(info["src"]), "—", f"[dim]{info['error']}[/dim]")
            continue
        if info["lines_changed"] == 0:
            status = "[green]nothing to do[/green]"
        elif dry_run or not info["wrote"]:
            status = "[yellow]would patch[/yellow]"
        else:
            status = "[green]patched[/green]"
        tbl.add_row(
            info["menu"],
            str(info["path"]),
            str(info["lines_changed"]),
            status,
        )
    console.print(tbl)

    if result["errors"]:
        console.print("\n[red]Errors:[/red]")
        for e in result["errors"]:
            console.print(f"  • {e}")

    if not dry_run and result["backup"]:
        console.print(
            "\n[dim]Backups saved as <file>.YYYYMMDD_HHMMSS.bak next to each modified file.[/dim]"
        )


# ─── add-system ───────────────────────────────────────────────────────────────

# HyperSpin Main Menu media slots that we know how to fetch from ScreenScraper.
SYSTEM_MEDIA_SLOTS = ("wheel", "background", "video")


@cli.command("add-system")
@click.argument("system_name")
@click.option("--no-menu", is_flag=True, help="Skip the Main Menu upsert step.")
@click.option("--no-system-media", is_flag=True,
              help="Skip downloading wheel/background/video for the new system.")
@click.option("--no-db", is_flag=True,
              help="Skip building the per-system database from ROMs.")
@click.option("--no-game-media", is_flag=True,
              help="Skip per-game media fetch for the new system.")
@click.option("--pick-media", "pick_media", is_flag=True,
              help="Interactively preview & pick when a slot has multiple candidates.")
@click.option("--source", default=None, type=click.Choice(["screenscraper", "thegamesdb"]))
@click.option("--dry-run", is_flag=True)
@click.option("--output-dir", type=click.Path(), default=None)
def add_system(system_name, no_menu, no_system_media, no_db, no_game_media,
               pick_media, source, dry_run, output_dir):
    """Bootstrap a top-level console end-to-end (e.g. PS3, Dreamcast).

    Scaffolds the ROM/database folders, adds the Main Menu entry, downloads
    wheel/background/video for the system tile, builds the games database
    from the ROMs you've already placed in <roms_dir>/<SYSTEM>/, and runs
    per-game media fetch for the new system.

    \b
    Examples:
      spindoctor add-system "Sony Playstation 3"
      spindoctor add-system Dreamcast --pick-media
      spindoctor add-system PS3 --no-game-media --dry-run
    """
    from .audit import build_stub_entry, scan_roms
    from .media import MediaDownloader
    from .rocketlauncher import upsert_main_menu_system
    from .scraper import MetadataError, build_client

    config = _cfg()
    _check_config(config)

    out_base = Path(output_dir) if output_dir else None

    if dry_run:
        console.print("[yellow bold][DRY RUN][/yellow bold] No files will be written.")

    console.print(Panel(f" add-system: {system_name} ", style="bold blue"))

    # 1. Scaffold folders ──────────────────────────────────────────────────────
    rom_dir = Path(config.roms_dir) / system_name
    db_dir = config.databases_dir / system_name

    console.print("[blue bold]1. Scaffold folders[/blue bold]")
    for d in (rom_dir, db_dir):
        if d.exists():
            console.print(f"  [dim]exists:[/dim] {d}")
        elif dry_run:
            console.print(f"  [yellow]would create:[/yellow] {d}")
        else:
            d.mkdir(parents=True, exist_ok=True)
            console.print(f"  [green]+[/green] {d}")

    # 2. Main Menu upsert ──────────────────────────────────────────────────────
    if no_menu:
        console.print("[dim]2. Main Menu upsert — skipped.[/dim]")
    else:
        console.print("\n[blue bold]2. Main Menu upsert[/blue bold]")
        if dry_run:
            console.print(f"  [yellow]would add[/yellow] '{system_name}' to "
                          f"{config.databases_dir / 'Main Menu' / 'Main Menu.xml'}")
        else:
            path, added = upsert_main_menu_system(system_name, config, out_base)
            if added:
                console.print(f"  [green]+[/green] added to {path}")
            else:
                console.print(f"  [dim]already present in {path}[/dim]")

    # 3. System-level media ────────────────────────────────────────────────────
    if no_system_media:
        console.print("[dim]3. System-level media — skipped.[/dim]")
    else:
        console.print("\n[blue bold]3. System-level media[/blue bold]")
        try:
            client = build_client(config, source)
        except MetadataError as e:
            err_console.print(f"  [red]{e}[/red]")
            client = None

        if client is None or not hasattr(client, "fetch_system_media"):
            console.print(
                "  [yellow]System media fetch requires ScreenScraper.[/yellow]"
            )
        else:
            try:
                slots = client.fetch_system_media(system_name)
            except MetadataError as e:
                err_console.print(f"  [red]{e}[/red]")
                slots = {}

            if not slots:
                console.print(f"  [yellow]No system media available for {system_name}.[/yellow]")
            else:
                downloader = MediaDownloader(config, output_dir_override=out_base)
                for slot in SYSTEM_MEDIA_SLOTS:
                    cands = slots.get(slot, [])
                    if not cands:
                        console.print(f"  [dim]{slot}:[/dim] none")
                        continue
                    dest = downloader.system_media_path(system_name, slot)
                    if dry_run:
                        console.print(
                            f"  [yellow]would fetch[/yellow] {slot}  "
                            f"({len(cands)} candidate(s)) → {dest}"
                        )
                        continue
                    if pick_media and len(cands) > 1:
                        r = downloader.download_with_picker(
                            system_name, system_name, slot, cands, dest,
                            interactive=True,
                        )
                    else:
                        r = downloader.download_to_path(
                            dest, cands[0].url,
                            label=system_name, media_type=slot,
                        )
                    _print_dl_result(slot, r)

    # 4. Build the games database ──────────────────────────────────────────────
    if no_db:
        console.print("[dim]4. Games database — skipped.[/dim]")
    else:
        console.print("\n[blue bold]4. Games database[/blue bold]")
        roms = scan_roms(system_name, Path(config.roms_dir))
        if not roms:
            console.print(f"  [yellow]No ROMs found in {rom_dir} — drop ROMs in and re-run.[/yellow]")
        else:
            db = load_database(system_name, config.databases_dir)
            existing = set(db.games().keys())
            new_count = 0
            for rom_name in sorted(roms):
                if rom_name in existing:
                    continue
                stub = build_stub_entry(
                    rom_name,
                    strip_variants=config.strip_variant_tags_in_display_name,
                )
                if dry_run:
                    console.print(f"  [yellow]+[/yellow] would add stub: {rom_name}")
                else:
                    db.add_game(stub)
                new_count += 1
            if not dry_run and new_count:
                if out_base:
                    saved = db.save(
                        output_path=out_base / "Databases" / system_name / f"{system_name}.xml",
                        backup=False,
                    )
                else:
                    saved = db.save(backup=config.backup_before_modify)
                console.print(f"  [green]+[/green] {new_count} stub(s) → {saved}")
            elif new_count:
                console.print(f"  [yellow]would add {new_count} stub(s)[/yellow]")
            else:
                console.print("  [green]Database already in sync with ROMs.[/green]")

    # 5. Per-game media fetch ──────────────────────────────────────────────────
    if no_game_media:
        console.print("[dim]5. Per-game media — skipped.[/dim]")
        return
    console.print("\n[blue bold]5. Per-game media[/blue bold]")
    extra = ["--system", system_name]
    if pick_media:
        extra.append("--pick-media")
    if dry_run:
        extra.append("--dry-run")
    if output_dir:
        extra.extend(["--output-dir", str(output_dir)])
    if source:
        extra.extend(["--source", source])
    console.print(f"  [dim]running:[/dim] spindoctor fetch-media {' '.join(extra)}")
    try:
        cli.main(args=["fetch-media", *extra], standalone_mode=False, prog_name="spindoctor")
    except SystemExit:
        pass


def _print_dl_result(slot: str, r) -> None:
    if r.skipped and r.success:
        console.print(f"  [dim]·[/dim] {slot}: already present at {r.path}")
    elif r.skipped:
        console.print(f"  [yellow]·[/yellow] {slot}: skipped ({r.error})")
    elif r.success:
        console.print(f"  [green]+[/green] {slot}: {r.path}")
    else:
        console.print(f"  [red]✗[/red] {slot}: {r.error}")


# ─── add-pc-system / pc-rename ────────────────────────────────────────────────

# Default overrides for a brand-new PC/Windows/Steam library.  Writes
# settings.json so every other code path (audit, scraper, organize,
# rocketlauncher) immediately treats the system like a PC library.
PC_DEFAULT_OVERRIDES: dict = {
    "rom_extensions": [".exe", ".lnk", ".url", ".bat"],
    "layout": "flat",
    "emulator": "PCLauncher",
    "recursive_scan": True,
    "title_strategy": "smart",
}


def _ensure_pc_overrides(config: Config, system_name: str) -> dict:
    """Merge PC defaults into ``system_overrides[system_name]`` (preserves
    existing user-set keys) and persist.  Returns the merged entry."""
    overrides = dict(config.system_overrides)
    entry = dict(overrides.get(system_name, {}))
    for k, v in PC_DEFAULT_OVERRIDES.items():
        entry.setdefault(k, v)
    overrides[system_name] = entry
    config.system_overrides = overrides
    save_config(config)
    return entry


def _propose_pc_titles(
    system_name: str,
    config: Config,
) -> list[tuple[Path, str]]:
    """Walk the system's ROM dir and return ``(path, proposed_title)`` pairs.

    Honours the override's title_strategy.  Same files that ``scan_roms``
    would pick up — kept separate so the picker can show the file path
    behind each proposed title.
    """
    from .config import get_rom_extensions, get_system_overrides
    from .romutils import derive_pc_title

    rom_dir = Path(config.roms_dir) / system_name
    if not rom_dir.exists():
        return []
    extensions = {e.lower() for e in get_rom_extensions(system_name)}
    strategy = (
        get_system_overrides().get(system_name, {}).get("title_strategy", "smart")
    )
    proposals: list[tuple[Path, str]] = []
    for path in sorted(rom_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        proposals.append((path, derive_pc_title(path, rom_dir, strategy)))
    return proposals


@cli.command("add-pc-system")
@click.argument("system_name", required=False, default="PC Games")
@click.option("--rename/--no-rename", "rename", default=True,
              help="Interactively confirm/edit derived titles before writing the DB.")
@click.option("--no-menu", is_flag=True, help="Skip the Main Menu upsert step.")
@click.option("--no-system-media", is_flag=True,
              help="Skip downloading wheel/background/video for the new system.")
@click.option("--no-db", is_flag=True, help="Skip building the per-system database.")
@click.option("--no-game-media", is_flag=True, help="Skip per-game media fetch.")
@click.option("--no-pclauncher", is_flag=True,
              help="Skip generating per-game PCLauncher INIs.")
@click.option("--overwrite-pclauncher", is_flag=True,
              help="Overwrite existing PCLauncher INIs (default: keep user edits).")
@click.option("--pick-media", "pick_media", is_flag=True,
              help="Interactively preview & pick when a media slot has multiple candidates.")
@click.option("--source", default=None, type=click.Choice(["screenscraper", "thegamesdb"]))
@click.option("--dry-run", is_flag=True)
@click.option("--output-dir", type=click.Path(), default=None)
def add_pc_system(system_name, rename, no_menu, no_system_media, no_db,
                  no_game_media, no_pclauncher, overwrite_pclauncher,
                  pick_media, source, dry_run, output_dir):
    """Bootstrap a PC/Windows/Steam games system end-to-end.

    \b
    Equivalent to ``add-system`` with PC-friendly defaults baked in:
      • recursive directory scan (your install layout is preserved)
      • smart title extraction (parent folder for nested .exe; stem for .lnk/.url)
      • PCLauncher emulator wired through RocketLauncher
      • per-game PCLauncher INIs generated mapping each title → executable

    \b
    Examples:
      spindoctor add-pc-system
      spindoctor add-pc-system "Windows Games" --pick-media
      spindoctor add-pc-system "Steam Games" --no-rename --no-pclauncher
    """
    from .config import reset_override_cache

    config = _cfg()
    _check_config(config)

    out_base = Path(output_dir) if output_dir else None

    # 1. Stamp PC overrides ───────────────────────────────────────────────────
    if dry_run:
        console.print(
            "[yellow bold][DRY RUN][/yellow bold] No files will be written, "
            "and overrides will not be persisted."
        )
    console.print(Panel(f" add-pc-system: {system_name} ", style="bold magenta"))
    console.print("[blue bold]0. PC system overrides[/blue bold]")
    if dry_run:
        merged = {**PC_DEFAULT_OVERRIDES, **config.system_overrides.get(system_name, {})}
        console.print(f"  [yellow]would write[/yellow] system_overrides[{system_name!r}]:")
        for k, v in merged.items():
            console.print(f"    [dim]{k}:[/dim] {v}")
    else:
        entry = _ensure_pc_overrides(config, system_name)
        reset_override_cache()
        console.print(f"  [green]+[/green] saved override for [cyan]{system_name}[/cyan]")
        for k, v in entry.items():
            console.print(f"    [dim]{k}:[/dim] {v}")

    # 2. Run the standard add-system flow.  We always pass --no-db and
    #    --no-game-media because PC systems need the title-review step to
    #    happen between scan and DB write, and per-game media fetch must
    #    follow the DB build (otherwise there are no game names to scrape).
    inner = ["add-system", system_name, "--no-db", "--no-game-media"]
    if no_menu:
        inner.append("--no-menu")
    if no_system_media:
        inner.append("--no-system-media")
    if pick_media:
        inner.append("--pick-media")
    if dry_run:
        inner.append("--dry-run")
    if output_dir:
        inner.extend(["--output-dir", str(output_dir)])
    if source:
        inner.extend(["--source", source])

    console.print(f"\n[dim]running:[/dim] spindoctor {' '.join(inner)}")
    try:
        cli.main(args=inner, standalone_mode=False, prog_name="spindoctor")
    except SystemExit:
        pass

    if no_db:
        console.print("[dim]4. Games database — skipped.[/dim]")
        if not no_pclauncher:
            console.print(
                "[yellow]Skipping PCLauncher INI generation because --no-db was passed.[/yellow]"
            )
        return

    # 3. Title review + DB build ─────────────────────────────────────────────
    console.print("\n[blue bold]4. Title review + games database[/blue bold]")
    proposals = _propose_pc_titles(system_name, config)
    if not proposals:
        rom_dir = Path(config.roms_dir) / system_name
        console.print(
            f"  [yellow]No game files found under {rom_dir} — drop installs/shortcuts in and re-run.[/yellow]"
        )
        return

    if rename and not dry_run:
        from .pc_titles import review_titles
        title_to_path = review_titles(system_name, proposals, interactive=True)
    elif rename and dry_run:
        console.print(
            f"  [yellow]would review {len(proposals)} title(s) interactively[/yellow]"
        )
        title_to_path = {p: t for p, t in proposals}
    else:
        # No interactive review — accept proposed titles, drop duplicates.
        title_to_path = {}
        for path, proposed in proposals:
            if proposed in title_to_path.values():
                continue
            title_to_path[path] = proposed

    # Invert {path: title} → {title: path} for DB + INI writes.
    by_title: dict[str, Path] = {}
    for path, title in title_to_path.items():
        by_title.setdefault(title, path)

    if not by_title:
        console.print("  [yellow]No titles accepted — nothing to write.[/yellow]")
        return

    console.print(f"  [green]+[/green] {len(by_title)} title(s) accepted")
    if dry_run:
        for t in sorted(by_title):
            console.print(f"  [yellow]would add stub:[/yellow] {t}")
    else:
        db = load_database(system_name, config.databases_dir)
        existing = set(db.games().keys())
        new_count = 0
        for title in sorted(by_title):
            if title in existing:
                continue
            stub = build_stub_entry(
                title,
                strip_variants=config.strip_variant_tags_in_display_name,
            )
            db.add_game(stub)
            new_count += 1
        if new_count:
            if out_base:
                saved = db.save(
                    output_path=out_base / "Databases" / system_name / f"{system_name}.xml",
                    backup=False,
                )
            else:
                saved = db.save(backup=config.backup_before_modify)
            console.print(f"  [green]+[/green] {new_count} stub(s) → {saved}")
        else:
            console.print("  [green]Database already in sync with titles.[/green]")

    # 4. PCLauncher per-game INIs ─────────────────────────────────────────────
    if no_pclauncher:
        console.print("[dim]6. PCLauncher INIs — skipped.[/dim]")
    else:
        console.print("\n[blue bold]6. PCLauncher per-game INIs[/blue bold]")
        if dry_run:
            console.print(
                f"  [yellow]would write {len(by_title)} INI(s) under "
                f"{Path(config.rocketlauncher_dir) / 'Modules' / 'PCLauncher' / system_name}[/yellow]"
            )
        else:
            from .rocketlauncher import generate_pclauncher_inis
            try:
                module_dir, written, skipped = generate_pclauncher_inis(
                    system_name, by_title, config, out_base,
                    overwrite=overwrite_pclauncher,
                )
            except ValueError as e:
                err_console.print(f"  [red]{e}[/red]")
            else:
                console.print(f"  [green]+[/green] wrote {len(written)} INI(s) → {module_dir}")
                if skipped:
                    console.print(
                        f"  [dim]· kept {len(skipped)} existing INI(s) "
                        f"(pass --overwrite-pclauncher to replace)[/dim]"
                    )

    # 5. Per-game media ──────────────────────────────────────────────────────
    if no_game_media:
        return
    console.print("\n[blue bold]7. Per-game media[/blue bold]")
    extra = ["--system", system_name]
    if pick_media:
        extra.append("--pick-media")
    if dry_run:
        extra.append("--dry-run")
    if output_dir:
        extra.extend(["--output-dir", str(output_dir)])
    if source:
        extra.extend(["--source", source])
    console.print(f"  [dim]running:[/dim] spindoctor fetch-media {' '.join(extra)}")
    try:
        cli.main(args=["fetch-media", *extra], standalone_mode=False, prog_name="spindoctor")
    except SystemExit:
        pass


@cli.command("pc-rename")
@click.argument("system_name")
@click.option("--no-pclauncher", is_flag=True,
              help="Skip regenerating PCLauncher INIs after rename.")
@click.option("--overwrite-pclauncher", is_flag=True,
              help="Overwrite existing PCLauncher INIs.")
def pc_rename(system_name, no_pclauncher, overwrite_pclauncher):
    """Re-run the title picker for an existing PC system.

    \b
    Use this after dropping new games into <roms_dir>/<SYSTEM>/ or to
    revise a previously-cached title.  Updates ~/.spindoctor/pc_titles_cache/
    and (optionally) regenerates the per-game PCLauncher INIs.
    """
    config = _cfg()
    _check_config(config)
    proposals = _propose_pc_titles(system_name, config)
    if not proposals:
        rom_dir = Path(config.roms_dir) / system_name
        console.print(f"[yellow]No game files found under {rom_dir}.[/yellow]")
        return

    from .pc_titles import review_titles
    title_to_path = review_titles(system_name, proposals, interactive=True)

    by_title: dict[str, Path] = {}
    for path, title in title_to_path.items():
        by_title.setdefault(title, path)

    console.print(f"\n[green]+[/green] {len(by_title)} title(s) confirmed.")

    if not no_pclauncher and by_title:
        from .rocketlauncher import generate_pclauncher_inis
        try:
            module_dir, written, skipped = generate_pclauncher_inis(
                system_name, by_title, config,
                overwrite=overwrite_pclauncher,
            )
        except ValueError as e:
            err_console.print(f"[red]{e}[/red]")
        else:
            console.print(f"[green]+[/green] wrote {len(written)} INI(s) → {module_dir}")
            if skipped:
                console.print(
                    f"[dim]· kept {len(skipped)} existing INI(s) "
                    f"(pass --overwrite-pclauncher to replace)[/dim]"
                )


# ─── organize ─────────────────────────────────────────────────────────────────

@cli.command("organize")
@click.argument("system_name")
@click.option("--no-sort", is_flag=True,
              help="Skip generating per-axis sort databases (genre/year/...).")
@click.option("--axes", default=",".join(("genre", "manufacturer", "year", "letter")),
              help="Comma-separated sort axes to generate. Default: all four.")
@click.option("--overwrite-sort", is_flag=True,
              help="Replace existing sort-database files (default: skip them).")
@click.option("--restructure", is_flag=True,
              help="Plan ROM folder restructuring for systems that need it "
                   "(PS3, multi-disc PS2/Saturn/Dreamcast). Dry-run by default.")
@click.option("--apply", "apply_changes", is_flag=True,
              help="Required to actually move files when --restructure is set.")
@click.option("--undo", is_flag=True,
              help="Reverse the latest restructure manifest for this system.")
def organize(system_name, no_sort, axes, overwrite_sort, restructure,
             apply_changes, undo):
    """Populate sort wheels and (optionally) restructure ROMs into folders.

    \b
    What this does:
      • Sort wheels — writes per-axis sub-databases under
        Databases/<SYSTEM>/{Genre,Manufacturer,Year,Letter}/<bucket>.xml
        so HyperSpin can render "Sort by genre / year / letter / manufacturer".
        Touches only XML; never moves ROM files.
      • --restructure (opt-in) — for systems that need per-game folders
        (PS3, multi-disc PS2/Saturn/Dreamcast) plans the moves and writes a
        manifest you can undo. Dry-run unless --apply is set.

    \b
    Examples:
      spindoctor organize "Sony Playstation"
      spindoctor organize "Sony Playstation 3" --restructure
      spindoctor organize "Sony Playstation 3" --restructure --apply
      spindoctor organize "Sony Playstation 3" --undo
    """
    from .database import write_sort_databases
    from .organize import (
        apply_restructure, find_latest_manifest, plan_restructure, undo_restructure,
    )

    config = _cfg()
    _check_config(config)

    console.print(Panel(f" organize: {system_name} ", style="bold blue"))

    # 1. Sort databases ────────────────────────────────────────────────────────
    if not no_sort:
        console.print("[blue bold]Sort databases[/blue bold]")
        db = load_database(system_name, config.databases_dir)
        games = list(db.games().values())
        if not games:
            console.print(f"  [yellow]No games in database for {system_name}.[/yellow]")
        else:
            axis_list = tuple(a.strip().lower() for a in axes.split(",") if a.strip())
            written = write_sort_databases(
                system_name, games, config.databases_dir,
                axes=axis_list, overwrite=overwrite_sort,
            )
            for axis, paths in written.items():
                if paths:
                    console.print(
                        f"  [green]+[/green] {axis}: {len(paths)} file(s) "
                        f"under {config.databases_dir / system_name / axis.capitalize()}"
                    )
                else:
                    console.print(f"  [dim]·[/dim] {axis}: no buckets / nothing to write")
    else:
        console.print("[dim]Sort databases — skipped.[/dim]")

    # 2. Undo restructure ──────────────────────────────────────────────────────
    if undo:
        console.print("\n[blue bold]Undo restructure[/blue bold]")
        manifest = find_latest_manifest(system_name, Path(config.roms_dir))
        if not manifest:
            console.print(f"  [yellow]No restructure manifest found for {system_name}.[/yellow]")
            return
        console.print(f"  Reverting from {manifest.name}")
        summary = undo_restructure(manifest)
        console.print(
            f"  [green]+[/green] reverted {summary['moves_reverted']} moves, "
            f"removed {summary['creates_removed']} generated file(s)"
        )
        for err in summary["errors"]:
            console.print(f"  [red]✗[/red] {err}")
        return

    # 3. Restructure ROM layout ────────────────────────────────────────────────
    if not restructure:
        return

    console.print("\n[blue bold]ROM restructure[/blue bold]")
    plan = plan_restructure(system_name, Path(config.roms_dir))

    for note in plan.notes:
        console.print(f"  [dim]{note}[/dim]")

    if plan.empty:
        console.print(f"  [green]No restructuring needed for {system_name}.[/green]")
        return

    tbl = Table(title=f"Plan ({plan.layout})", box=box.SIMPLE)
    tbl.add_column("From", style="yellow")
    tbl.add_column("→")
    tbl.add_column("To", style="green")
    for m in plan.moves:
        tbl.add_row(Path(m.src).name, "→", str(Path(m.dest).relative_to(Path(plan.roms_dir))))
    console.print(tbl)

    if plan.creates:
        console.print(f"  Will write {len(plan.creates)} playlist(s):")
        for c in plan.creates:
            console.print(f"    [dim]+[/dim] {Path(c.path).relative_to(Path(plan.roms_dir))}")
    if plan.skipped:
        console.print(
            f"  [dim]Skipping {len(plan.skipped)} item(s) "
            f"already organized.[/dim]"
        )

    if not apply_changes:
        console.print(
            "\n[yellow]Dry-run.[/yellow] Re-run with [cyan]--apply[/cyan] to execute."
        )
        return

    try:
        manifest = apply_restructure(plan)
    except FileExistsError as e:
        err_console.print(f"[red]Aborted:[/red] {e}")
        sys.exit(1)
    console.print(
        f"  [green]✓[/green] Applied. Manifest: {manifest.name}\n"
        f"  Run [cyan]spindoctor organize {system_name} --undo[/cyan] to revert."
    )


# ─── backup / restore ─────────────────────────────────────────────────────────

@cli.group("backup")
def backup_group():
    """Back up or restore the SpinDoctor library.

    Copy any combination of components (games, media, databases, emulators,
    rocketlauncher, ledblinky, settings) into a dated backup folder under a
    target directory. Each backup is self-describing and can be restored in
    full or in part later.

    \b
    Subcommands:
      create    Create a new backup
      list      List backups under a target directory
      info      Show what's inside a backup
      restore   Restore a backup back to the original (or current) paths
    """


def _backup_format_includes() -> str:
    from .backup import ALL_COMPONENTS, COMPONENT_ALIASES
    return (
        ", ".join(ALL_COMPONENTS)
        + ", all"
        + " (aliases: "
        + ", ".join(sorted(COMPONENT_ALIASES))
        + ")"
    )


@backup_group.command("create")
@click.option("--target", type=click.Path(file_okay=False), required=True,
              help="Destination folder for the backup. A new dated subfolder "
                   "named 'spindoctor-backup-YYYYMMDD_HHMMSS[-LABEL]/' is "
                   "created under it.")
@click.option("--include", default="all",
              help="Comma-separated components to back up. Choices: roms, "
                   "databases, media, emulators, rocketlauncher, ledblinky, "
                   "settings, all. Aliases: games→roms, hyperspin→databases+media, "
                   "config→settings. Default: all.")
@click.option("--label", default=None,
              help="Optional suffix appended to the backup folder name (e.g. "
                   "'pre-migration', 'weekly').")
@click.option("--apply", "apply_changes", is_flag=True,
              help="Execute the backup. Without this flag, prints a dry-run plan.")
def backup_create(target, include, label, apply_changes):
    """Create a new backup of selected library components.

    \b
    Examples:
      # Dry-run — see what would be backed up
      spindoctor backup create --target E:\\Backups

      # Full backup of everything
      spindoctor backup create --target E:\\Backups --apply

      # Just settings + databases
      spindoctor backup create --target E:\\Backups --include settings,databases --apply

      # Just the games (ROM files)
      spindoctor backup create --target E:\\Backups --include games --apply

      # Tagged backup — folder is suffixed with -pre-migration
      spindoctor backup create --target E:\\Backups --label pre-migration --apply
    """
    from .backup import (
        apply_backup, format_bytes, free_bytes, normalize_components,
        plan_backup,
    )

    config = _cfg()
    target_root = Path(target).expanduser()

    try:
        components = normalize_components(include.split(","))
    except ValueError as e:
        err_console.print(f"[red]{e}[/red]")
        sys.exit(1)

    if not components:
        err_console.print("[red]--include resolved to no components.[/red]")
        sys.exit(1)

    console.print(Panel(f" backup create → {target_root} ", style="bold blue"))
    console.print(f"Components: [cyan]{', '.join(components)}[/cyan]")

    plan = plan_backup(config, target_root, components, label=label)

    if plan.skipped:
        console.print("\n[yellow]Skipped:[/yellow]")
        for s in plan.skipped:
            console.print(f"  [dim]· {s}[/dim]")

    if plan.empty:
        console.print("\n[green]Nothing to back up.[/green]")
        return

    tbl = Table(title="Backup plan", box=box.SIMPLE)
    tbl.add_column("Component", style="cyan")
    tbl.add_column("From", style="yellow")
    tbl.add_column("→")
    tbl.add_column("To", style="green")
    tbl.add_column("Size", justify="right")
    for it in plan.items:
        tbl.add_row(it.component, it.src, "→", it.dest, format_bytes(it.size_bytes))
    console.print(tbl)
    console.print(f"Backup root: [bold]{plan.backup_root}[/bold]")
    total = plan.total_bytes
    console.print(f"Total to copy: [bold]{format_bytes(total)}[/bold]")
    free = free_bytes(target_root)
    if free:
        marker = "[green]✓[/green]" if free > total else "[red]✗[/red]"
        console.print(f"Free at target: {format_bytes(free)} {marker}")
        if free <= total and apply_changes:
            err_console.print(
                "[red]Aborted:[/red] target drive does not have enough free space."
            )
            sys.exit(1)

    if not apply_changes:
        console.print(
            "\n[yellow]Dry-run.[/yellow] Re-run with [cyan]--apply[/cyan] to execute."
        )
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Backing up", total=len(plan.items))

        def _cb(item, status):
            if status == "start":
                progress.update(
                    task,
                    description=f"Backing up {item.component}: {Path(item.src).name}",
                )
            elif status == "done":
                progress.update(task, advance=1)

        try:
            backup_root = apply_backup(plan, config, progress_cb=_cb)
        except (FileExistsError, OSError) as e:
            err_console.print(f"[red]Aborted:[/red] {e}")
            sys.exit(1)

    console.print(f"\n[green]✓[/green] Backup complete: {backup_root}")
    console.print(
        f"  Run [cyan]spindoctor backup restore --backup \"{backup_root}\"[/cyan] "
        f"to restore."
    )


@backup_group.command("list")
@click.option("--target", type=click.Path(file_okay=False), required=True,
              help="Folder where backups live (the same path passed to "
                   "`backup create --target`).")
def backup_list(target):
    """List backups under a target folder."""
    from .backup import format_bytes, list_backups, read_manifest

    target_root = Path(target).expanduser()
    backups = list_backups(target_root)
    if not backups:
        console.print(f"[yellow]No backups found under {target_root}.[/yellow]")
        return

    tbl = Table(title=f"Backups under {target_root}", box=box.SIMPLE)
    tbl.add_column("Backup", style="cyan")
    tbl.add_column("Timestamp")
    tbl.add_column("Components")
    tbl.add_column("Size", justify="right")
    for b in backups:
        try:
            data = read_manifest(b)
            comps = ", ".join(i["component"] for i in data.get("items", []))
            size = sum(i.get("size_bytes", 0) for i in data.get("items", []))
            tbl.add_row(b.name, data.get("timestamp", ""), comps or "[dim]none[/dim]",
                        format_bytes(size))
        except (FileNotFoundError, ValueError):
            tbl.add_row(b.name, "[red]?[/red]", "[red]malformed manifest[/red]", "")
    console.print(tbl)


@backup_group.command("info")
@click.option("--backup", "backup_path", type=click.Path(file_okay=False),
              required=True,
              help="Path to a backup folder (created by `backup create`).")
def backup_info(backup_path):
    """Show what's inside a backup."""
    from .backup import format_bytes, read_manifest

    backup_root = Path(backup_path).expanduser()
    try:
        data = read_manifest(backup_root)
    except (FileNotFoundError, ValueError) as e:
        err_console.print(f"[red]{e}[/red]")
        sys.exit(1)

    console.print(Panel(f" {backup_root.name} ", style="bold blue"))
    console.print(f"Created: [cyan]{data.get('timestamp', '?')}[/cyan]")
    console.print(f"Path:    [dim]{backup_root}[/dim]")

    items = data.get("items", [])
    if not items:
        console.print("\n[yellow]Backup contains no components.[/yellow]")
        return

    tbl = Table(title="Components", box=box.SIMPLE)
    tbl.add_column("Component", style="cyan")
    tbl.add_column("Original source", style="yellow")
    tbl.add_column("Size", justify="right")
    for i in items:
        tbl.add_row(i["component"], i["src"], format_bytes(i.get("size_bytes", 0)))
    console.print(tbl)
    total = sum(i.get("size_bytes", 0) for i in items)
    console.print(f"Total: [bold]{format_bytes(total)}[/bold]")


@backup_group.command("restore")
@click.option("--backup", "backup_path", type=click.Path(file_okay=False),
              required=True,
              help="Path to the backup folder to restore.")
@click.option("--include", default=None,
              help="Comma-separated components to restore (default: every "
                   "component recorded in the backup). Same vocabulary as "
                   "`backup create --include`.")
@click.option("--use-current-paths", is_flag=True,
              help="Restore each component to the path currently set in "
                   "~/.spindoctor/config.json instead of the path recorded "
                   "in the backup manifest. Useful when drive letters changed.")
@click.option("--overwrite", is_flag=True,
              help="Replace existing destination folders. Without this flag, "
                   "restore aborts if any destination is non-empty.")
@click.option("--apply", "apply_changes", is_flag=True,
              help="Execute the restore. Without this flag, prints a dry-run plan.")
def backup_restore(backup_path, include, use_current_paths, overwrite, apply_changes):
    """Restore from a backup back to the library paths.

    \b
    Examples:
      # Dry-run — see what would be restored
      spindoctor backup restore --backup E:\\Backups\\spindoctor-backup-20260428_120000

      # Full restore
      spindoctor backup restore --backup E:\\... --apply

      # Just restore settings (config + favorites)
      spindoctor backup restore --backup E:\\... --include settings --apply

      # Drive letters changed since the backup — route everything to the
      # paths now in config.json
      spindoctor backup restore --backup E:\\... --use-current-paths --apply

      # Replace existing folders on disk
      spindoctor backup restore --backup E:\\... --overwrite --apply
    """
    from .backup import (
        apply_restore, format_bytes, plan_restore,
    )

    backup_root = Path(backup_path).expanduser()
    components = None
    if include:
        components = [c.strip() for c in include.split(",") if c.strip()]

    config_for_routing = _cfg() if use_current_paths else None

    try:
        plan = plan_restore(
            backup_root,
            components=components,
            use_current_config=config_for_routing,
        )
    except (FileNotFoundError, ValueError) as e:
        err_console.print(f"[red]{e}[/red]")
        sys.exit(1)

    console.print(Panel(f" backup restore ← {backup_root.name} ", style="bold blue"))

    if plan.skipped:
        console.print("[yellow]Skipped:[/yellow]")
        for s in plan.skipped:
            console.print(f"  [dim]· {s}[/dim]")

    if plan.empty:
        console.print("\n[green]Nothing to restore.[/green]")
        return

    tbl = Table(title="Restore plan", box=box.SIMPLE)
    tbl.add_column("Component", style="cyan")
    tbl.add_column("From backup", style="yellow")
    tbl.add_column("→")
    tbl.add_column("Restored to", style="green")
    tbl.add_column("Size", justify="right")
    for it in plan.items:
        tbl.add_row(it.component, it.src, "→", it.dest, format_bytes(it.size_bytes))
    console.print(tbl)
    console.print(f"Total to restore: [bold]{format_bytes(plan.total_bytes)}[/bold]")

    # Warn about clobbering
    clobbers = [i for i in plan.items if Path(i.dest).exists()
                and (Path(i.dest).is_file() or any(Path(i.dest).iterdir()))]
    if clobbers and not overwrite:
        console.print(
            "\n[red]The following destinations already exist[/red] "
            "(pass [cyan]--overwrite[/cyan] to replace them):"
        )
        for c in clobbers:
            console.print(f"  · {c.dest}")
        if apply_changes:
            err_console.print(
                "[red]Aborted:[/red] re-run with --overwrite or remove the "
                "existing folders first."
            )
            sys.exit(1)

    if not apply_changes:
        console.print(
            "\n[yellow]Dry-run.[/yellow] Re-run with [cyan]--apply[/cyan] to execute."
        )
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Restoring", total=len(plan.items))

        def _cb(item, status):
            if status == "start":
                progress.update(
                    task,
                    description=f"Restoring {item.component} → {Path(item.dest).name}",
                )
            elif status == "done":
                progress.update(task, advance=1)

        try:
            restored = apply_restore(plan, overwrite=overwrite, progress_cb=_cb)
        except (FileExistsError, OSError) as e:
            err_console.print(f"[red]Aborted:[/red] {e}")
            sys.exit(1)

    console.print(f"\n[green]✓[/green] Restored {restored} component(s).")


# ─── migrate (move library to a new drive) ────────────────────────────────────

@cli.command("migrate")
@click.option("--target", type=click.Path(file_okay=False), default=None,
              help="Destination root folder on the new drive. New per-component "
                   "subfolders (ROMs/, HyperSpin/, ...) are created underneath.")
@click.option("--include", default="all",
              help="Comma-separated components to migrate. Choices: "
                   "roms, hyperspin, emulators, rocketlauncher, ledblinky, all. "
                   "Aliases: games→roms, media/data/databases→hyperspin. "
                   "Default: all.")
@click.option("--systems", default=None,
              help="Comma-separated systems to migrate (only applies to --include roms). "
                   "When set, only those system subfolders are moved and "
                   "roms_dir config is left unchanged.")
@click.option("--apply", "apply_changes", is_flag=True,
              help="Execute the migration. Without this flag, prints a dry-run plan.")
@click.option("--keep-source", is_flag=True,
              help="Copy instead of move — leaves the source intact. Pair with "
                   "--verify for a safe-then-delete-by-hand workflow.")
@click.option("--verify", is_flag=True,
              help="SHA1-verify each file after copy. Only meaningful with --keep-source.")
@click.option("--no-update-config", is_flag=True,
              help="Don't rewrite ~/.spindoctor/config.json with the new paths.")
@click.option("--preserve-names", is_flag=True,
              help="Keep each component's original folder name at the target "
                   "(e.g. D:\\MyArcade\\HS lands at <target>/HS). "
                   "Default: standardized names — Games, HyperSpin, Emulators, "
                   "RocketLauncher, LEDBlinky.")
@click.option("--undo", "undo_path", default=None,
              help="Path to a manifest under ~/.spindoctor/migrations/ to reverse. "
                   "Use 'latest' to undo the most recent migration.")
@click.option("--list-manifests", is_flag=True,
              help="List all migration manifests on disk and exit.")
def migrate(target, include, systems, apply_changes, keep_source, verify,
            no_update_config, preserve_names, undo_path, list_manifests):
    """Migrate the library to a new drive.

    \b
    Move (or copy) ROMs, HyperSpin, Emulators, RocketLauncher, and LEDBlinky
    folders to a new drive in one shot. Updates ~/.spindoctor/config.json so
    SpinDoctor keeps working at the new location. Every applied migration
    writes a manifest you can undo.

    \b
    Examples:
      # See what would move (dry run, every component)
      spindoctor migrate --target E:\\NewCab

      # Move everything and update config
      spindoctor migrate --target E:\\NewCab --apply

      # Move only the ROMs and HyperSpin folder
      spindoctor migrate --target E:\\NewCab --include roms,hyperspin --apply

      # Aliases — these are equivalent to --include roms,hyperspin
      spindoctor migrate --target E:\\NewCab --include games,media --apply

      # Move only specific systems' ROMs (config unchanged)
      spindoctor migrate --target E:\\NewCab --include roms \\
          --systems "MAME,Sony Playstation 3" --apply

      # Safe copy + verify (keeps the original intact)
      spindoctor migrate --target E:\\NewCab --apply --keep-source --verify

      # Reverse the most recent migration
      spindoctor migrate --undo latest
      spindoctor migrate --list-manifests
    """
    from .migrate import (
        ALL_COMPONENTS, MIGRATIONS_DIR, apply_migration, find_latest_manifest,
        format_bytes, free_bytes, list_manifests as list_migrate_manifests,
        normalize_components, plan_migration, undo_migration,
    )

    # ── --list-manifests ──────────────────────────────────────────────────────
    if list_manifests:
        manifests = list_migrate_manifests()
        if not manifests:
            console.print(f"[yellow]No migration manifests under {MIGRATIONS_DIR}.[/yellow]")
            return
        tbl = Table(title="Migration manifests", box=box.SIMPLE)
        tbl.add_column("Manifest", style="cyan")
        tbl.add_column("Target")
        tbl.add_column("Mode")
        for m in manifests:
            try:
                import json as _json
                data = _json.loads(m.read_text(encoding="utf-8"))
                mode = "copy" if data.get("keep_source") else "move"
                tbl.add_row(m.name, data.get("target_root", ""), mode)
            except (OSError, ValueError):
                tbl.add_row(m.name, "[red]?[/red]", "[red]?[/red]")
        console.print(tbl)
        return

    # ── --undo ────────────────────────────────────────────────────────────────
    if undo_path:
        if undo_path == "latest":
            manifest = find_latest_manifest()
            if not manifest:
                err_console.print("[red]No migration manifests to undo.[/red]")
                sys.exit(1)
        else:
            manifest = Path(undo_path)
            if not manifest.exists():
                err_console.print(f"[red]Manifest not found:[/red] {manifest}")
                sys.exit(1)
        console.print(f"[blue bold]Undo migration[/blue bold]: {manifest.name}")
        summary = undo_migration(manifest)
        console.print(
            f"  [green]+[/green] reverted {summary['moves_reverted']} move(s), "
            f"removed {summary['destinations_removed']} copied destination(s)"
        )
        if summary["config_restored"]:
            console.print("  [green]+[/green] config restored from snapshot")
        for err in summary["errors"]:
            console.print(f"  [red]✗[/red] {err}")
        return

    # ── plan / apply path ─────────────────────────────────────────────────────
    if not target:
        err_console.print(
            "[red]--target is required (unless using --undo or --list-manifests).[/red]"
        )
        sys.exit(1)

    config = _cfg()
    target_root = Path(target).expanduser()

    try:
        components = normalize_components(include.split(","))
    except ValueError as e:
        err_console.print(f"[red]{e}[/red]")
        sys.exit(1)

    if not components:
        err_console.print("[red]--include resolved to no components.[/red]")
        sys.exit(1)

    systems_filter = None
    if systems:
        systems_filter = [s.strip() for s in systems.split(",") if s.strip()]
        if "roms" not in components:
            console.print(
                "[yellow]--systems only filters the 'roms' component; "
                "ignoring for everything else.[/yellow]"
            )

    console.print(Panel(f" migrate → {target_root} ", style="bold blue"))
    console.print(f"Components: [cyan]{', '.join(components)}[/cyan]")
    if systems_filter:
        console.print(f"Systems filter (roms only): [cyan]{', '.join(systems_filter)}[/cyan]")

    plan = plan_migration(
        config, target_root, components, systems_filter,
        preserve_names=preserve_names,
    )

    for note in plan.notes:
        console.print(f"  [dim]{note}[/dim]")

    if plan.skipped:
        console.print("\n[yellow]Skipped:[/yellow]")
        for s in plan.skipped:
            console.print(f"  [dim]· {s}[/dim]")

    if plan.empty:
        console.print("\n[green]Nothing to migrate.[/green]")
        return

    tbl = Table(title="Migration plan", box=box.SIMPLE)
    tbl.add_column("Component", style="cyan")
    tbl.add_column("From", style="yellow")
    tbl.add_column("→")
    tbl.add_column("To", style="green")
    tbl.add_column("Size", justify="right")
    for m in plan.moves:
        tbl.add_row(m.component, m.src, "→", m.dest, format_bytes(m.size_bytes))
    console.print(tbl)

    total = plan.total_bytes
    console.print(f"Total to transfer: [bold]{format_bytes(total)}[/bold]")
    free = free_bytes(target_root)
    if free:
        marker = "[green]✓[/green]" if free > total else "[red]✗[/red]"
        console.print(f"Free at target: {format_bytes(free)} {marker}")
        if free <= total and apply_changes:
            err_console.print(
                "[red]Aborted:[/red] target drive does not have enough free space."
            )
            sys.exit(1)

    if plan.config_updates and not no_update_config and not keep_source:
        console.print("\nConfig updates that will be applied:")
        for k, v in plan.config_updates.items():
            console.print(f"  [cyan]{k}[/cyan] → {v}")
    elif keep_source:
        console.print("\n[dim]--keep-source: config will NOT be updated.[/dim]")

    if not apply_changes:
        console.print(
            "\n[yellow]Dry-run.[/yellow] Re-run with [cyan]--apply[/cyan] to execute."
        )
        return

    # ── execute ───────────────────────────────────────────────────────────────
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Migrating", total=len(plan.moves))

        def _cb(move, status):
            if status == "start":
                progress.update(task, description=f"Migrating {move.component}: {Path(move.src).name}")
            elif status == "done":
                progress.update(task, advance=1)

        try:
            manifest = apply_migration(
                plan,
                keep_source=keep_source,
                verify=verify,
                update_config=not no_update_config,
                progress_cb=_cb,
            )
        except (FileExistsError, RuntimeError, OSError) as e:
            err_console.print(f"[red]Aborted:[/red] {e}")
            sys.exit(1)

    console.print(f"\n[green]✓[/green] Migration complete. Manifest: {manifest}")
    console.print(
        f"  Run [cyan]spindoctor migrate --undo {manifest}[/cyan] to revert."
    )
