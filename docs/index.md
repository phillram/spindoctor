# SpinDoctor Documentation

A Tkinter GUI + CLI librarian for [HyperSpin](http://www.hyperspin-fe.com/) + [RocketLauncher](https://rocketlauncher.net/) arcade cabinets. Audits ROMs, syncs HyperSpin XML, fetches metadata and media, manages cross-system Favorites / Recently Played / Most Played wheels, and migrates the whole library between drives or PCs.

> **Convention.** Commands that modify files are dry-run by default — re-run with `--apply` to commit. Read-only commands (`audit`, `inspect`, `report`, `systems`, `find-dupes`, `find-global`, `verify`, `check-discs`, `check-archive-ext`, `stats`, `doctor`, `self-doctor`, `tools-audit`, `theme-scan`, `mainmenu show`, `find-misplaced` without `--apply`, `lightgun audit`, `lightgun detect` without `--apply`) need no flag and never modify anything.

## Pick your install route

SpinDoctor ships in three forms. Pick the one that fits, then either click your way through the GUI or stay on the command line:

| Route | Best for | Walkthrough |
|---|---|---|
| 🪟 **Prebuilt Windows binaries** | Cabinets where you don't want to install Python. Two bundles: **modern** (Windows 10/11, shared runtime) and **Win7** (Windows 7 SP1+, five standalone `.exe`s). Both include a GUI launcher. | [Windows binaries](windows-binaries.md) |
| 🐍 **Pip install from source** | Dev machines, custom builds, anyone already on Python 3.8+. Cross-platform. | [Installation](installation.md) |
| 📂 **Source-on-disk, no install** | Locked-down boxes where `pip install` isn't an option but Python is. | [Installation → Running without `pip install`](installation.md#running-without-pip-install) |

Then pick how to launch:

| Mode | When to use it | How |
|---|---|---|
| 🖱️ **GUI launcher** (`spindoctor-gui`) | First-time setup, refreshing wheels, casual use | Double-click `spindoctor-gui.exe` (binary route) or run `spindoctor-gui` (pip route). See the [GUI walkthrough](gui.md). |
| ⌨️ **CLI** (`spindoctor`) | Every command, scripts, scheduled tasks, advanced workflows | Open `cmd.exe` and run `spindoctor …`. See the [Command reference](commands.md). |

## Where to start

| If you want to… | Read |
|---|---|
| Stand up a cabinet from a blank Windows PC | [First-time setup](setup.md) |
| Find a control on the GUI launcher | [GUI walkthrough](gui.md) |
| Upgrade from SpinDoctor 1.x | [Migrating from 1.x](migrating-from-1.x.md) |
| Get the punchy copy-paste cheatsheet for the most-used commands | [CLI cheatsheet](cli-cheatsheet.md) |
| Look up a specific command (every flag, every option) | [Command reference](commands.md) |
| See or change configuration | [Configuration](configuration.md) |
| Do something common (backup, migrate, daily refresh, recovery) | [Workflows](workflows.md) |
| Wire Favorites / Recently Played / Most Played into HyperSpin Tools menu or boot | [Standalone tools](standalone-tools.md) |
| Set up backgrounds, themes, sounds, and videos for the synthetic wheels | [Synthetic wheel media](synthetic-wheel-media.md) |
| Set up Sinden / DemulShooter for lightgun systems | [Light guns](lightgun.md) |
| Audit other arcade tools installed on the cabinet | [Standalone tools → Tools audit](standalone-tools.md#tools-audit--what-other-arcade-utilities-does-this-cabinet-already-have) |
| Diagnose an error | [Troubleshooting](troubleshooting.md) |
| Find where SpinDoctor stores its files | [SpinDoctor Files](spindoctor-files.md) |

## What SpinDoctor is, and isn't

It is a librarian: it reads and writes HyperSpin databases, RocketLauncher configs, media folders, ROM folders, and its own caches. It does *not* install HyperSpin, RocketLauncher, or any emulator, and it does *not* download ROMs or BIOS. Get those in place, then SpinDoctor automates the rest — including Sinden / DemulShooter wiring per system and an inventory of the third-party arcade tools the cabinet has accumulated.

## Project layout

```
spindoctor/        ← Python package (CLI + GUI module)
scripts/           ← Standalone wrappers + Windows .bat files
build/             ← PyInstaller driver that produces the Windows .exe zip
docs/              ← You are here
tests/
```

The standalone tools in `scripts/` are documented in [Standalone tools](standalone-tools.md). The frozen Windows binaries (CLI + GUI) come from `build/build_windows.py` — see [Windows binaries → Building from source](windows-binaries.md#building-from-source).
