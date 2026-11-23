# CLI cheatsheet

Examples use `spindoctor` (pip); binary users use `spindoctor-cli`.
Use exact system/game names from your database. Commands below preview unless
otherwise noted. Add `--apply` only after reviewing the plan.
[Safety and all commands](commands.md).

## Discover and diagnose

```text
spindoctor --help
spindoctor systems
spindoctor doctor
spindoctor self-doctor
spindoctor tools-audit
spindoctor audit --system MAME --detailed
spindoctor audit --all --report D:\Reports\audit.csv
spindoctor inspect --system MAME --game 1942
spindoctor find-global "house of the dead"
spindoctor find-dupes --all --by-content
spindoctor find-misplaced
spindoctor find-orphan-media
spindoctor check-discs --all
spindoctor check-archive-ext
spindoctor verify --system MAME --dat D:\DATs\MAME.dat
spindoctor stats
spindoctor preview --all --output-dir D:\Preview --open
```

Content deduplication ignores recognized NES/FDS/SNES ROM headers, including
inside supported archives; it does not imply wrapper files are byte-identical.

## Systems and games

```text
spindoctor add-system "Nintendo Entertainment System"
spindoctor add-pc-system "PC Games"
spindoctor mainmenu show
spindoctor mainmenu sort alpha
spindoctor wheel-start
spindoctor wheel-start --system MAME --set first
spindoctor game list --system MAME
spindoctor game sort --system MAME
spindoctor game remove --system MAME 1942
spindoctor rename --system MAME --game oldname --to newname
spindoctor clone --system MAME --game 1942 --to "1942 (variant)"
spindoctor batch-edit --system MAME --filter "genre=*Shooter*" --set "genre=Shooter"
spindoctor curate --system MAME --action archive
```

`game remove` removes a database entry, not the ROM. For PC entries add
`--remove-pclauncher` to remove the launcher too. Close HyperSpin before
`wheel-start --apply`.

## Metadata and media

```text
spindoctor update-db --system MAME
spindoctor fetch-meta --system MAME --auto-best
spindoctor fetch-media --system MAME --types wheel,background,video
spindoctor fetch-steam-media --system "PC Games" --game Hades --steam-id 1145360
spindoctor media-scan D:\MediaPack --system MAME
spindoctor generate-media list --all
spindoctor generate-media wheel-pictures --system MAME
spindoctor generate-media record --system MAME --count 5
spindoctor generate-media placeholders --no-video-clip
spindoctor generate-media put-in
spindoctor generate-media undo
spindoctor generate-config
spindoctor theme-scan --keyword controller
spindoctor theme-apply D:\Packs\Buttons
spindoctor theme-fill --system MAME --default
```

`--auto-best` accepts ambiguous provider matches. Use per-game overrides for
known IDs, or skip ambiguity in unattended work. Zero-byte media is missing.
`generate-media` works offline and stages its files until `put-in`;
[guide](generate-media.md).

## Wheels and cabinet helpers

```text
spindoctor fav add MAME 1942
spindoctor fav sync
spindoctor fav rebuild
spindoctor recent rebuild --limit 20
spindoctor stats-report
spindoctor stats-report build-wheel --limit 25
spindoctor install-tools --tool refresh-all --add-to-system Toolkit
spindoctor install-tools --tool idle-tour
spindoctor toolkit idle-tour --self-test
spindoctor introvideo list
spindoctor introvideo swap
```

`fav add/sync` save immediately. `install-tools` writes helpers even in preview;
`--apply` gates registration. Power, display and LED-reset Toolkit actions are
live. See [helpers](standalone-tools.md) and [idle tour](idle-tour.md).

## Lighting and guns

```text
spindoctor ledblinky --help
spindoctor ledblinky setup
spindoctor ledblinky audit
spindoctor ledblinky lwax cute --list
spindoctor ledblinky lwax cute --theme cute_koi_moonlight
spindoctor ledblinky lwax batch
spindoctor ledblinky lwax flash-check D:\Animations
spindoctor lightgun detect
spindoctor lightgun audit
spindoctor lightgun configure --system "Sega Naomi"
```

LWAX generation is unsigned; save through LEDBlinky's Animation Editor before
use. Flash scoring is descriptive, not a medical/photosensitivity guarantee.

## Launch tests

```text
spindoctor test --system MAME --count 3
spindoctor test --system MAME --count 3 --with-hyperspin --apply
spindoctor test --resume
spindoctor test --only-failed
spindoctor test --recover
```

Tests launch real games only with `--apply` on Windows. Recovery acts on an
unfinished run. See [test safety and reports](workflows.md#launch-tests).

## Backup, migration and cleanup

```text
spindoctor backup create --target E:\Backups --include settings,databases
spindoctor backup list --target E:\Backups
spindoctor backup info --backup E:\Backups\<backup-folder>
spindoctor backup restore --backup E:\Backups\<backup-folder>
spindoctor backup sidecar --help
spindoctor diff E:\Backups\<backup-folder>
spindoctor migrate --target E:\Cabinet --keep-source --verify
spindoctor cleanup categories
spindoctor cleanup audit
spindoctor cleanup run --include metadata-cache
```

Replace `<backup-folder>` before running. [Recovery syntax varies by command](workflows.md#recovery-from-mistakes);
cleanup/deletion is not automatically undoable.

## Configuration

```text
spindoctor config init
spindoctor config show
spindoctor config verify-credentials
spindoctor config set default_metadata_source auto
spindoctor config system set "MAME (Vector)" --rom-path J:\Games\MAME
spindoctor config game-override set "PC Games" Hades --steam-app-id 1145360
```

Configuration changes save immediately. Do not publish `config show` output
without checking it for credentials and private paths.
