# Workflows

CLI examples use the pip name `spindoctor`; binary users use `spindoctor-cli`.
Preview cabinet changes first, then repeat with `--apply`. Check
[exceptions](commands.md#safety), and keep an independent backup.

## Adding your first system

Finish [setup](setup.md), confirm games launch in RocketLauncher, then:

```text
spindoctor systems
spindoctor add-system "Nintendo Entertainment System"
spindoctor add-system "Nintendo Entertainment System" --apply
spindoctor doctor
```

Use **GUI → Systems** for the same workflow. Unknown extensions/shared folders
need [system overrides](configuration.md#per-system-overrides).

## Daily wheel refresh

```text
spindoctor fav rebuild --apply
spindoctor recent rebuild --apply
spindoctor stats-report build-wheel --apply
```

Or use **Custom Wheels → Refresh selected**, install a Refresh All helper,
or enable startup refresh. Rebuilds are not automatically scheduled by
installing SpinDoctor. [Helper setup](standalone-tools.md).

`fav add SYSTEM GAME` and `fav sync` save the favorites store immediately.
Rebuild to publish it to HyperSpin. Recent/Most Played read RocketLauncher
statistics, not an independent SpinDoctor play tracker.

## Weekly maintenance

1. Back up settings and databases.
2. Run `doctor`, `audit --all`, `stats`, duplicate/disc/archive checks and DAT
   verification as needed. `doctor --apply` repairs only supported safe cases.
3. Preview `curate --system MAME --action archive`; inspect chosen variants
   before applying. `--action delete` is permanent.
4. Fetch missing metadata/media for source systems, not generated wheels;
   [generate](generate-media.md) what can't be fetched.
5. Refresh custom wheels and test representative games.

## Backup & restore

```text
spindoctor backup create --target E:\Backups --label weekly --include settings,databases
spindoctor backup create --target E:\Backups --label weekly --include settings,databases --apply
spindoctor backup list --target E:\Backups
spindoctor backup info --backup E:\Backups\<backup-folder>
spindoctor backup restore --backup E:\Backups\<backup-folder>
```

Replace the placeholder with the actual folder. Full snapshots default to all
components: ROMs, databases, media, emulators, RocketLauncher, LEDBlinky and
SpinDoctor settings. `hyperspin` means databases/media, **not** every frontend
file or Windows dependency. Back those up separately.

Backups are ordinary directories with manifests. Inspect incomplete/failed
snapshots before trusting them. `settings` contains credentials.
Restore previews first; `--overwrite` replaces existing files.
`--use-current-paths` uses the paths configured on the destination PC.
Keep the backup outside the source tree.

## Migration

**Same drive letters on a new PC:** point configuration at the existing folders;
no move is needed. Restore drivers, runtimes and startup tasks separately.

**New drive on the same PC:**

```text
spindoctor migrate --target E:\Cabinet --keep-source --verify
spindoctor migrate --target E:\Cabinet --keep-source --verify --apply
spindoctor doctor
```

Copy mode keeps the source while verifying the copy. Without `--keep-source`,
migration moves files. Components include ROMs, HyperSpin, emulators,
RocketLauncher and LEDBlinky; inspect the plan for nested/shared paths.
Do not remove originals until launch checks pass.

**New PC:** create a backup, configure destination paths there, then preview
`backup restore --use-current-paths`. Include settings deliberately, since they
can contain old paths/credentials. A SpinDoctor snapshot is not a Windows image.

**Already moved manually:** update configuration and system overrides;
use `repath-system --help` for PCLauncher prefixes. Emulator-internal paths
(RetroArch, Dolphin, ScummVM, framefiles, virtual drives) are not universally
rewritten. Regenerate helper scripts and scheduled tasks after moving the EXE.

## Managing PC games

```text
spindoctor add-pc-system "PC Games" --no-menu --no-system-media --no-game-media
spindoctor pc-rename "PC Games"
spindoctor pc-fix-exe "PC Games" "Sample Game" --list-candidates
spindoctor game remove --system "PC Games" "Sample Game" --remove-pclauncher
```

`add-pc-system` synchronizes new/stale wheel entries and launcher INIs.
`pc-rename` regenerates launcher INIs only, not wheel XML.
Use `--overwrite-pclauncher` only when you intend to replace existing launchers.
Removing a wheel entry does not uninstall/delete the game.

## Launch tests

```text
spindoctor test --system MAME --count 3
spindoctor test --system MAME --count 3 --with-hyperspin --apply
```

Windows tests launch through RocketLauncher, look for startup failures,
error windows/logs, hangs and black screens, save a screenshot, then close the
game. These heuristics do not prove that gameplay or controls work.
Leave the cabinet idle; screenshots can include the whole monitor.

Default sampling is three games per system. PCLauncher, custom wheels and
configured skipped systems are excluded unless requested. Options include
genre/game selection, duration, resume and re-testing failures.
Reports are in `~/.spindoctor/tests/<run>/report.html`, with CSV/JSON and logs.

RocketLauncher statistics are backed up and restored after each game.
`--cleanup report` lists new files (default); `remove` backs up and removes
eligible new files, never pre-existing ones; `off` disables tracking.
Use **Stop after this game** for a clean end. After a crash/forced stop, run
`spindoctor test --recover`; ranked-wheel rebuilds refuse unfinished runs.

## Managing intro videos

Set `intro_randomizer_dir` to the pool folder and `intro_video_target` to the
file HyperSpin actually plays. Then:

```text
spindoctor introvideo list
spindoctor introvideo add D:\Downloads\Intro.mp4
spindoctor introvideo swap
spindoctor introvideo install-autorun
```

Repeat modifying commands with `--apply`. Remove/restore retires/re-enables
pool files without permanent deletion. Swap overwrites the configured target.
Logon autorun and wheel refresh are separate scheduled tasks; re-register both
after moving/upgrading the EXE. Do not swap while HyperSpin is reading the intro.

The consoles' own start-up logos, which emulators play before a game, are a
separate setting in each emulator: `boot-intros` turns them on or off
([start-up logos](start-up-logos.md)).

## Recovery from mistakes

Close affected cabinet software first. Sidecar backups and manifests are
command-specific, not universal guarantees.

| Operation | Recovery |
|---|---|
| XML/INI edits with a `.bak` | Inspect `backup sidecar --help`, or restore a reviewed backup |
| Migration | `migrate --undo latest` or a manifest path, with `--apply` to commit |
| Curation archive | `curate --undo --apply` (latest supported archive run) |
| Media import | `media-scan --undo --apply` |
| Generated media | `generate-media undo --apply` (the last batch put in) |
| Batch edit / rename / clone | Owning command's `--undo <manifest>` and Apply gate |
| Misplaced / restructure | Owning command's undo; manifests live in the ROM tree |
| Theme swap | `theme-apply --undo latest` |
| Scrub | `scrub-restore` using its backup |
| Backup snapshot | `backup restore`, inspect first |
| Permanent delete / discarded recovery data | Independent backup only |

Use `--help` before undo: argument forms and gates differ. The GUI's
**File → View logs & manifests → Undo this run** dispatches supported recovery;
some categories undo only the newest run, not the selected older record.

Handled Ctrl+C can preserve partial progress; GUI termination, crashes and
power loss may bypass cleanup. Atomic replacement protects individual files,
not an entire operation. Keep failed manifests and unfinished test journals
until recovery is complete. [Storage map](spindoctor-files.md).
