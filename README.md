# SpinDoctor 🩺🕹️

A command-line librarian for [HyperSpin](http://www.hyperspin-fe.com/) + [RocketLauncher](https://rocketlauncher.net/) arcade cabinets. Audits ROMs, syncs HyperSpin XML, fetches metadata and media, validates ROM integrity, manages cross-system Favorites / Recently Played / Most Played wheels, reports on playtime, and migrates the whole library between drives or PCs — all from a single CLI.

> **Dry-run by default.** Commands that modify files preview their plan unless invoked with `--apply`. Read-only commands (`audit`, `inspect`, `report`, `systems`, `find-dupes`, `verify`, `check-discs`, `stats`, `doctor`) need no flag.

## Quick start

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
| [First-time setup](docs/setup.md) | Step-by-step from a blank Windows PC to a working cabinet |
| [Configuration](docs/configuration.md) | Config keys, per-system overrides, filesystem considerations |
| [Command reference](docs/commands.md) | Every command, grouped by purpose |
| [Workflows](docs/workflows.md) | First-system add, daily refresh, weekly maintenance, **backup**, **migration**, **recovery** |
| [Standalone tools](docs/standalone-tools.md) | Favorites / Recent / Most Played wheels — Tools menu and boot wiring; **tools-audit** for cataloguing other arcade utilities |
| [Light guns](docs/lightgun.md) | Sinden + DemulShooter wiring per system |
| [Troubleshooting](docs/troubleshooting.md) | FAQ + common errors |

Start at [docs/index.md](docs/index.md) for a guided table of contents.

## What it does, in one paragraph

SpinDoctor reads and writes your existing HyperSpin databases, RocketLauncher configs, media folders, ROM folders, and its own caches. It is **not** an installer — it does not install HyperSpin, RocketLauncher, or any emulator, and does not download ROMs or BIOS. Get those in place, then SpinDoctor automates the librarian work: stub creation, metadata + media fetching, integrity verification, cross-system Favorites / Recently Played / Most Played wheels, drive-to-drive migration with rollback, and incremental dated backups.

## Reporting issues

Open an issue at the [project repository](https://github.com/phillram/spindoctor).
