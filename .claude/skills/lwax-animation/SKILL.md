---
name: lwax-animation
description: Build, flash-check and sign LEDBlinky .lwax animations using the configured input map. Use for LED animation, fade, pattern, colourway and "too flashy" requests, or Missing Signature troubleshooting.
---

# LEDBlinky animation workflow

Use the maintained implementation rather than duplicating animation geometry or
reconstructing an old conversation. User-facing options and signing steps live in
[Command reference](../../../docs/commands.md#ledblinky-lwax-fade); hardware and
format notes live in the
[example cabinet reference](../../../docs/cabinet-architecture-reference.md#ledblinky-animation-files-lwax).

## Generate

- `spindoctor ledblinky lwax fade` builds a uniform color-cycle fade.
- `spindoctor ledblinky lwax batch` generates the pattern library.
- `spindoctor ledblinky lwax cute` builds one smooth `cute_*` pattern, or a new
  colourway of one (`--list` shows the patterns and their colour slots).
- `spindoctor ledblinky lwax flash-check` scores files Strobe / Fast blink /
  Borderline / Fast motion / Smooth. Read-only; run it on anything new.
- `spindoctor ledblinky lwax calibrate` creates a button-mapping aid.
- Preview first. Pass `--apply` only when the destination and scope are approved.

```bat
spindoctor ledblinky lwax fade --color FF0000 --color 00FF00
spindoctor ledblinky lwax fade --color FF0000 --color 00FF00 --apply
spindoctor ledblinky lwax batch
spindoctor ledblinky lwax cute --theme cute_koi_pond --color2 FF9FFF --color2 D435FF --color2 B500D4 --color2 80009F
spindoctor ledblinky lwax flash-check <file or folder>
```

For a smooth request ("no flashing", "something cute"), start from a `cute_*`
pattern or a `_soft` fill/drain rather than a new effect. Keep the flashing
families (strobe, heartbeat, checker, marquee, flashing fill/drain) as they are:
a cabinet can archive them, but they stay makeable.

Fade/calibrate/cute default to `<output_dir>/LEDBlinky/lwax/`; batch defaults to
`~/Downloads/spindoctor-lwax-patterns/`. Read each command's `--help` before
overriding destinations. Batch refreshes its output directory, so keep signed
files and custom work elsewhere.

## Reuse the layout and builders

- Generic builders and parsers: `spindoctor/lwax.py` (`build_fill` / `build_drain`
  take `fade_reset_frames` for a flash-free, faded reset).
- Batch effects and example layout groups: `spindoctor/lwax_patterns.py`.
- Cute patterns, their 100 themes and the physical panel coordinates they use
  (`PANEL_POS`): `spindoctor/lwax_cute.py`. A new colourway is a `CuteTheme`
  (`p1` main palette, `p2`/`p3` backgrounds or second palette, `seed`), not new code.
- Flash scorer: `spindoctor/lwax_flash.py` (`score_animation`, `score_lwax`).
- Source-checkout wrapper: `scripts/generate_lwax_patterns.py`.
- Committed example input map: `docs/reference/LEDBlinkyInputMap.xml`.

Use the configured cabinet's input map and verify its physical layout before
generating spatial effects. The committed map and grouped positions are examples,
not a universal wiring standard. Do not copy a second set of `LEFT_RIGHT_ORDER`,
`RADIAL_RINGS`, `PANEL_POS` or label positions into this skill.

The cute set's built-in themes are pinned byte for byte to the files first made on
the example cabinet (`tests/test_lwax_cute.py`), and the batch's older files are
pinned too (`tests/test_lwax_patterns.py`). Add new themes or families; don't change
an existing one's palette, seed or timing unless asked, since signed copies are
installed.

For a layout change, get a diagram or description confirmed first. If a photo is
needed, ask permission and do not commit it. Preserve intentional grouping choices
unless the user asks to change them. Generated names should remain readable,
lowercase underscore-separated slugs.

## Sign and install

Generated `.lwax` files are **unsigned** and do not load directly in LEDBlinky.
Open the raw file in `LEDBlinkyAnimationEditor.exe`, then use **Animation → Save
As** to sign it and adapt controller IDs to the target input map. Hand-editing the
signed XML can invalidate it.

Copy the signed output into `<ledblinky_dir>/lwa/`, then select it through the
LEDBlinky GUI or `ledblinky patch-settings`. Do not automate the editor or overwrite
installed signed files unless explicitly asked.

If navigation buttons remain static during an animation, check
`Settings.ini` → `[FEOptions] LightFEControls`: `1` lights frontend controls
independently, while `0` allows the full animation. This is a cabinet choice, not
a setting to change automatically.

## Validate

After changing the parser/builders or effects, run:

```text
python -m pytest -q tests/test_lwax.py tests/test_lwax_patterns.py tests/test_lwax_cute.py tests/test_lwax_flash.py
```

XML tests do not validate the editor's signature or physical wiring. Confirm final
playback on the target hardware. Follow [Privacy guidance](../../../docs/privacy.md)
when sharing maps, logs or screenshots.
