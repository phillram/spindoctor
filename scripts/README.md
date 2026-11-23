# Scripts

Run from a checkout with dependencies installed.

| Script | Purpose |
|---|---|
| `spindoctor-fav.py` | Source wrapper for Favorites |
| `spindoctor-recent.py` | Source wrapper for Recently Played |
| `spindoctor-stats.py` | Source wrapper for playtime/Most Played |
| `Refresh *.bat` | Convenience calls to pip helpers on PATH |
| `capture_gui_screenshots.py` | Actual GUI pages using isolated synthetic data |
| `generate_command_reference.py` | Compact Click-derived command index; `--check` detects drift |
| `generate_lwax_patterns.py` | Generate the unsigned LED animation library |
| `check_changelog_unreleased.py` | One unreleased changelog section, no hard-wrapped entries |
| `gen_theme_zips.py`, `make_icon.py` | Developer asset generation |

Windows binaries embed wheel workers rather than shipping separate helper EXEs.
Use `install-tools` to generate BATs with the correct embedded-worker path;
the checkout's BATs are not portable binary-install wrappers.
[Helper setup](../docs/standalone-tools.md).

```text
python scripts/spindoctor-fav.py rebuild
python scripts/generate_command_reference.py --check
```

The standalone LWAX script writes immediately to
`~/Downloads/spindoctor-lwax-patterns`, clearing its previous batch. It uses
`~/Downloads/LEDBlinkyInputMap.xml` when present, otherwise the committed
reference map. Prefer `spindoctor ledblinky lwax batch` for explicit preview,
map/output options and Apply. Sign generated LWAX through LEDBlinky's Animation
Editor before use.

Screenshot requirements and privacy boundaries:
[GUI screenshot maintenance](../docs/gui.md#refreshing-screenshots).
