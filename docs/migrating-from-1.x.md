# Upgrading from 1.x

Back up `.spindoctor` and the cabinet before upgrading. Current releases retain
the main CLI and settings file, but add many commands and a substantially expanded
GUI. Use the current [GUI guide](gui.md), not the old tab layout.

## Windows binaries

v3 downloads contain **one independent EXE per zip**:

- `spindoctor.exe`: GUI, double-click to launch.
- `spindoctor-cli.exe`: CLI, run from a terminal.

Old releases used `spindoctor.exe` for the CLI and `spindoctor-gui.exe` for the
GUI. Separate Favorites/Recent/Stats EXEs are replaced by embedded `--run-tool`
workers. Do not mix EXEs from different releases.

Regenerate `install-tools` helpers and re-enable startup refresh/intro autorun:
old scripts/tasks can point to removed EXEs. Keep the new EXE in a stable path.

## Settings and behavior

Configuration remains in `.spindoctor/config.json`; there is no required library
reimport. New fields acquire defaults. Metadata source selection can migrate to
`auto` once. The last GUI page is now saved by name with a legacy index fallback.
Apply remains off on startup.

Preview changes and read [safety exceptions](commands.md#safety).
New recovery records/formats are not guaranteed readable by old versions.

## Rollback

Close all workers, restore the old application **and matching saved cabinet/config
snapshot**, then regenerate its helper/task paths. Replacing the EXE alone does
not undo changes already applied to the library.
