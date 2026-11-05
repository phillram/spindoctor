---
name: lwax-animation
description: Build and sign LEDBlinky .lwax animations using the configured input map. Use for LED animation, fade and pattern requests, or Missing Signature troubleshooting.
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
- `spindoctor ledblinky lwax calibrate` creates a button-mapping aid.
- Preview first. Pass `--apply` only when the destination and scope are approved.

```bat
spindoctor ledblinky lwax fade --color FF0000 --color 00FF00
spindoctor ledblinky lwax fade --color FF0000 --color 00FF00 --apply
spindoctor ledblinky lwax batch
```

Fade/calibrate default to `<output_dir>/LEDBlinky/lwax/`; batch defaults to
`~/Downloads/spindoctor-lwax-patterns/`. Read each command's `--help` before
overriding destinations. Batch refreshes its output directory, so keep signed
files and custom work elsewhere.

## Reuse the layout and builders

- Generic builders and parsers: `spindoctor/lwax.py`.
- Batch effects and example layout groups: `spindoctor/lwax_patterns.py`.
- Source-checkout wrapper: `scripts/generate_lwax_patterns.py`.
- Committed example input map: `docs/reference/LEDBlinkyInputMap.xml`.

Use the configured cabinet's input map and verify its physical layout before
generating spatial effects. The committed map and grouped positions are examples,
not a universal wiring standard. Do not copy a second set of `LEFT_RIGHT_ORDER`,
`RADIAL_RINGS` or label positions into this skill.

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
python -m pytest -q tests/test_lwax.py tests/test_lwax_patterns.py
```

XML tests do not validate the editor's signature or physical wiring. Confirm final
playback on the target hardware. Follow [Privacy guidance](../../../docs/privacy.md)
when sharing maps, logs or screenshots.
