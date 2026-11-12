# SpinDoctor Documentation

A Tkinter GUI + CLI librarian for [HyperSpin](http://www.hyperspin-fe.com/) + [RocketLauncher](https://rocketlauncher.net/) arcade cabinets. Audits ROMs, syncs HyperSpin XML, fetches metadata and media, manages cross-system Favorites / Recently Played / Most Played wheels, and migrates the whole library between drives or PCs.

> **Convention.** Cabinet write commands generally preview until you pass `--apply`; settings/list commands can save immediately. The [Command reference](commands.md) names exceptions. [Recovery from mistakes](workflows.md#recovery-from-mistakes) explains which operations have undo and which permanently delete data.

## Pick your install route

Use [Installation](installation.md) to choose between prebuilt Windows binaries, a pip install and running from a source checkout. For bundle layout and OS requirements, see [Windows binaries](windows-binaries.md).

After installation, launch `spindoctor-gui` for guided forms or `spindoctor` from a terminal for the CLI. Both use the same configuration. The [README quick starts](../README.md#pick-your-install-route) are the shortest path to a first run.

## Where to start

| If you want to… | Read |
|---|---|
| Stand up a cabinet from a blank Windows PC | [First-time setup](setup.md) |
| Move a cabinet from Windows 7 to Windows 10, with a hardware upgrade | [Windows 7 → 10 migration](windows-10-migration.md) |
| Set up a controller for both HyperSpin menu navigation and in-game play | [Controller input (DS4Windows Auto Profiles)](controller-input.md) |
| Find a control on the GUI launcher | [GUI walkthrough](gui.md) |
| Upgrade from SpinDoctor 1.x | [Migrating from 1.x](migrating-from-1.x.md) |
| Get the punchy copy-paste cheatsheet for the most-used commands | [CLI cheatsheet](cli-cheatsheet.md) |
| Look up command behavior and options | [Command reference](commands.md), then `<command> --help` for complete syntax |
| See or change configuration | [Configuration](configuration.md) |
| Do something common (backup, migrate, daily refresh, recovery) | [Workflows](workflows.md) |
| Wire Favorites / Recently Played / Most Played into HyperSpin Tools menu or boot | [Standalone tools](standalone-tools.md) |
| Make HyperSpin's idle mode visit random consoles | [Idle tour](idle-tour.md) |
| Set up backgrounds, themes, sounds, and videos for the synthetic wheels | [Synthetic wheel media](synthetic-wheel-media.md) |
| Set up Sinden / DemulShooter for lightgun systems | [Light guns](lightgun.md) |
| Audit other arcade tools installed on the cabinet | [Standalone tools → Tools audit](standalone-tools.md#tools-audit--what-other-arcade-utilities-does-this-cabinet-already-have) |
| Diagnose an error | [Troubleshooting](troubleshooting.md) |
| Find where SpinDoctor stores its files | [SpinDoctor Files](spindoctor-files.md) |
| Share logs or examples without exposing private details | [Privacy and sharing diagnostics](privacy.md) |
| Understand package boundaries and data flow | [Software architecture](architecture.md) |
| Run and maintain the test suite | [Testing](testing.md) |
| Understand HyperSpin/RocketLauncher file layouts and hardware examples | [Example cabinet reference](cabinet-architecture-reference.md) |

## How the guides fit together

- **README / Installation / Setup:** choose a route, install, then configure a cabinet.
- **GUI walkthrough / Command reference:** look up a control or command; use `--help` for the installed release's complete flag syntax.
- **CLI cheatsheet / Workflows:** copy short examples or follow a multi-step task, with links back to the reference.
- **Troubleshooting:** diagnose symptoms. The cabinet reference supplies deeper layout and integration context, not a required configuration.
- **Software architecture / Project review:** developer-oriented module boundaries and the dated review's findings, respectively.

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
