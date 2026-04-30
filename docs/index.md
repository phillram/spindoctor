# SpinDoctor Documentation

A command-line librarian for [HyperSpin](http://www.hyperspin-fe.com/) + [RocketLauncher](https://rocketlauncher.net/) arcade cabinets. Audits ROMs, syncs HyperSpin XML, fetches metadata and media, manages cross-system Favorites / Recently Played / Most Played wheels, and migrates the whole library between drives or PCs.

> **Convention.** Commands that modify files are dry-run by default — re-run with `--apply` to commit. Read-only commands (`audit`, `inspect`, `report`, `systems`, `find-dupes`, `verify`, `check-discs`, `stats`, `doctor`) need no flag and never modify anything.

## Where to start

| If you want to… | Read |
|---|---|
| Install SpinDoctor | [Installation](installation.md) |
| Stand up a cabinet from a blank Windows PC | [First-time setup](setup.md) |
| Look up a specific command | [Command reference](commands.md) |
| See or change configuration | [Configuration](configuration.md) |
| Do something common (backup, migrate, daily refresh, recovery) | [Workflows](workflows.md) |
| Wire Favorites / Recently Played / Most Played into HyperSpin Tools menu or boot | [Standalone tools](standalone-tools.md) |
| Set up Sinden / DemulShooter for lightgun systems | [Light guns](lightgun.md) |
| Audit other arcade tools installed on the cabinet | [Standalone tools → Tools audit](standalone-tools.md#tools-audit--what-other-arcade-utilities-does-this-cabinet-already-have) |
| Diagnose an error | [Troubleshooting](troubleshooting.md) |

## What SpinDoctor is, and isn't

It is a librarian: it reads and writes HyperSpin databases, RocketLauncher configs, media folders, ROM folders, and its own caches. It does *not* install HyperSpin, RocketLauncher, or any emulator, and it does *not* download ROMs or BIOS. Get those in place, then SpinDoctor automates the rest.

## Project layout

```
spindoctor/        ← Python package (the CLI)
scripts/           ← Standalone wrappers + Windows .bat files
docs/              ← You are here
tests/
```

The standalone tools in `scripts/` are documented in [Standalone tools](standalone-tools.md).
