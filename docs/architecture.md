# Software architecture

The Tkinter GUI (`gui.py`) builds forms, reads library/config state and invokes
CLI/standalone workers as subprocesses. Click (`cli.py`) owns command parsing,
progress, orchestration and command-specific Apply policy. Domain modules own
the library operations. There is no background server.

Frozen v3 EXEs embed all workers and media, dispatching `--run-tool`.
Pip console scripts and source wrappers call the same implementations.

## Module map

| Area | Main modules |
|---|---|
| Configuration/discovery | `config`, `database`, `rocketlauncher`, `rl_rom_paths` |
| Inspection/integrity | `audit`, `health`, `self_doctor`, `fileinfo`, `verify`, `romheaders` |
| Metadata/media | `scraper`, `matcher`, `media`, `media_scan` |
| Editing/organization | `edit`, `mainmenu`, `wheel_start`, `organize`, `curate`, `misplaced` |
| Smart wheels | `favorites`, `recent`, `playtime`, `medialink`, `_wheels` |
| Backup/move/recovery | `backup`, `migrate`, `cleanup`, `_undo` |
| Game-launch tests | `gametest`, related `gametest_*` modules, Win32 capture/process helpers |
| Hardware/frontend | `ledblinky*`, `lightgun`, `rl_user_functions`, `introvideo`, `autostart` |
| Cabinet helpers | `toolkit_helpers`, `cabinet_power`, `toolkit_screen`, `display_mode`, `button_lights`, `idle_tour`, `startup_script` |
| Themes/animations | `themes`, `preview`, `lwax`, `lwax_patterns`, `lwax_cute`, `lwax_flash` |

`_utils` supplies filesystem primitives; `_text` handles legacy editable text;
`_net` HTTP sessions; `_compat` platform differences; `_errors` error messages;
`_singleton` the GUI lock. Keep domain policy out of generic helpers.

## Shared pipelines

Favorites and ranked wheels share `favorites._write_synthetic_wheel`. Selection,
ordering, validation and dry-run policies remain with callers. Write replacement
files before pruning orphan launchers/media. Custom synthetic targets require
ownership evidence, not just a PCLauncher directory.

Bulk matching uses reusable normalized scoring and per-operation media snapshots.
Do not persist a filesystem snapshot across writes. Metadata response caches
hash full identities; preserved LEDBlinky library entries are not response caches.

## Safety boundaries

Apply is a command policy, not a property of every domain function.
Settings/list commands and helper-file generation can write without it.
Atomic writers replace individual files via same-filesystem temporary files,
not whole operations transactionally. Collision checks are not concurrent
reservations. Do not run competing writers against a cabinet.

Recovery differs by command: sidecars, manifests, unfinished-work journals or
no undo for permanent deletion. Normal interrupts and forced process termination
are distinct. Launch tests journal owned processes and statistics backups.
See [recovery](workflows.md#recovery-from-mistakes),
[storage](spindoctor-files.md) and the
[historical review](project-review.md#remaining-risks-and-follow-up-work).

## Compatibility and validation

Maintain Python 3.8/Win7-compatible application code and legacy INI encodings.
Linux/macOS tests do not validate Windows hardware.
Run [focused tests/lint](testing.md), the generated command-index check and
[EXE isolation smoke](../build/README.md) when relevant.
[Cabinet formats](cabinet-architecture-reference.md) are separate from this map.
