# SpinDoctor 🩺🕹️

A command-line librarian for [HyperSpin](http://www.hyperspin-fe.com/) + [RocketLauncher](https://rocketlauncher.net/) arcade cabinets. Audits ROMs, syncs HyperSpin XML, fetches metadata and media, validates ROM integrity against No-Intro / Redump / TOSEC DATs, manages cross-system Favorites / Recently Played / Most Played wheels, reports on playtime, wires Sinden / DemulShooter for light-gun systems, inventories the third-party tools already installed on your cabinet, and migrates the whole library between drives or PCs — all from a single CLI.

SpinDoctor is a librarian, **not** an installer. It does not install HyperSpin, RocketLauncher, or any emulator, and it does not download ROMs or BIOS. Get those in place, then SpinDoctor automates the rest.

> **Dry-run by default.** Commands that modify files preview their plan unless invoked with `--apply`. Read-only commands (`audit`, `inspect`, `report`, `systems`, `find-dupes`, `verify`, `check-discs`, `stats`, `doctor`, `tools-audit`, `find-global`, `lightgun detect`, `lightgun audit`) need no flag. Most destructive commands also write a manifest under `~/.spindoctor/` and accept `--undo` to roll back.

## Quick start

Two install paths — pick one:

**Prebuilt Windows binaries** (no Python required, runs on Windows 7 SP1 +):

1. Grab `spindoctor-windows-vX.Y.Z.zip` from the [latest release](https://github.com/phillram/spindoctor/releases).
2. Extract to e.g. `C:\spindoctor\` and add the folder to `PATH`.
3. Double-click `spindoctor-gui.exe` for the windowed launcher, **or** open `cmd.exe` and run `spindoctor config init`. (`spindoctor.exe` is a CLI — double-clicking it just flashes a console and exits, [by design](docs/windows-binaries.md#double-clicking-spindoctorexe-flashes-a-window-that-closes-instantly).)

**From source** (Python 3.8+):

```bat
git clone https://github.com/phillram/spindoctor C:\spindoctor
cd C:\spindoctor
pip install -e .[all]
spindoctor config init
spindoctor systems
spindoctor add-system "Nintendo Entertainment System" --apply
```

For a complete first-time walkthrough on a blank Windows PC (Python, HyperSpin, RocketLauncher, emulators, BIOS, ROMs), see [docs/setup.md](docs/setup.md).

## Documentation

| | |
|---|---|
| [Installation](docs/installation.md) | Python deps, optional extras, console scripts |
| [Windows binaries](docs/windows-binaries.md) | Standalone `.exe` files — no Python required, runs on Windows 7 SP1 + |
| [First-time setup](docs/setup.md) | Step-by-step from a blank Windows PC to a working cabinet |
| [Configuration](docs/configuration.md) | Config keys, per-system overrides, filesystem considerations |
| [Command reference](docs/commands.md) | Every command, grouped by purpose |
| [Workflows](docs/workflows.md) | First-system add, daily refresh, weekly maintenance, backup, migration, recovery |
| [Standalone tools](docs/standalone-tools.md) | Favorites / Recent / Most Played wheels — Tools menu and boot wiring; tools-audit for cataloguing other arcade utilities |
| [Light guns](docs/lightgun.md) | Sinden + DemulShooter wiring per system |
| [Troubleshooting](docs/troubleshooting.md) | FAQ + common errors |

Start at [docs/index.md](docs/index.md) for a guided table of contents, or skim [CHANGELOG.md](CHANGELOG.md) for what shipped in each release.

## Common starting points

| If you want to… | Run |
|---|---|
| See every command and what it does | `spindoctor --help` |
| Inventory the tools already on this cabinet | `spindoctor tools-audit` |
| Self-diagnose paths, binaries, and DB integrity | `spindoctor doctor` |
| Audit one system's ROMs vs. the HyperSpin DB | `spindoctor audit --system MAME` |
| Verify ROM integrity against a No-Intro / Redump DAT | `spindoctor verify --system NES --dat path\to.dat` |
| Find a game across every system | `spindoctor find-global "house of the dead"` |
| Edit metadata across many games at once | `spindoctor batch-edit --system MAME --filter genre=Action --set rating=5 --apply` |
| Wire a Sinden lightgun for a system | `spindoctor lightgun configure --system "Sega Naomi" --apply` |
| Refresh Favorites / Recently Played / Most Played | `spindoctor-fav rebuild --apply && spindoctor-recent rebuild --apply && spindoctor-stats build-wheel --apply` |
| Snapshot the library before risky work | `spindoctor backup create --target E:\Backups --apply` |
| Migrate to a new drive | `spindoctor migrate --target E:\Cab --apply` |

## Reporting issues

Open an issue at the [project repository](https://github.com/phillram/spindoctor).
