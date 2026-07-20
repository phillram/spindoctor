---
name: lwax-animation
description: Build and sign a new LedBlinky .lwax animation file for this cabinet's LED buttons. Use whenever asked to create, adjust, or troubleshoot a LED animation/fade/pattern for the arcade cabinet's PAC-LED64 boards, or when a .lwax file fails to load with a "Missing Signature" error.
---

# LedBlinky .lwax animation workflow

Full background/investigation: `docs/cabinet-architecture-reference.md` → **"LEDBlinky Animation Files (.lwax)"**. Read that section before doing anything non-routine here — it has the confirmed file format, the hardware channel map, and every gotcha discovered so far. This skill is the short version for routine "make me a new pattern" requests.

## The one hard rule

**Never hand-author or hand-edit `.lwax` XML directly and expect it to load in LedBlinky.** LedBlinky Config validates a per-file signature that cannot be reproduced outside its own `LEDBlinkyAnimationEditor.exe` — every attempt to reverse it (SHA-1/256/384/512/MD5/RIPEMD-160, many canonicalizations) failed. There is a two-step workflow that reliably works; don't skip step 2.

## Step 1 — generate the raw (unsigned) file

Use `spindoctor ledblinky lwax fade` (in `spindoctor/lwax.py` + the `ledblinky lwax` CLI group in `spindoctor/cli.py`). It reads the cabinet's real board/port layout from `<ledblinky_dir>\LEDBlinkyInputMap.xml`, so it's correct for any controller count/type without hardcoding.

```bat
spindoctor ledblinky lwax fade --color FF0000 --color 00FF00 --color 0000FF
:: dry-run: shows detected controllers, control count, frame count -- writes nothing

spindoctor ledblinky lwax fade --color FF0000 --color 00FF00 --color 0000FF --apply
:: writes <output_dir>/LEDBlinky/lwax/fade.lwax

spindoctor ledblinky lwax fade --color FF0000 --color 0000FF --labels P1B1,P1B2,P1B3 --name red_blue_fade --apply
:: only fades specific controls, custom output name
```

Key options:
- `--color RRGGBB` (repeatable, ≥2 required) — colors cycle in the order given and loop back to the first.
- `--labels a,b,c` — restrict to specific control labels (see `LEDBlinkyInputMap.xml` for the exact label spelling per board; defaults to every wired control).
- `--steps-per-leg N` (default 48) and `--duration-ms N` (default 40) — tune fade smoothness/speed. Total per-leg time ≈ `steps-per-leg * duration-ms` ms. Lower `steps-per-leg` = choppier/faster; higher `duration-ms` = slower overall.
- `--output PATH` — write to an exact path instead of the default `output_dir` location.

This only builds a **uniform color-cycle fade** across the chosen controls today. For anything else (chases, per-control staggering, non-uniform timing), use the `spindoctor.lwax` module directly — `LwaxAnimation.add_frame(duration_ms, {label: (r, g, b), ...})` is a fully generic per-frame, per-control API; `build_color_cycle()` is just one preset built on top of it. Write a short one-off script importing `parse_input_map`/`LwaxAnimation` rather than extending the CLI for a single ad-hoc request.

## Step 2 — sign it (manual, on the cabinet, every time)

The generated file **will not load** until this happens:

1. Copy the file to the cabinet if not already there.
2. Open `LEDBlinkyAnimationEditor.exe` (`<ledblinky_dir>\Plugins\LEDBlinky\LEDBlinkyAnimationEditor.exe` — already installed, no download needed).
3. **Animation → Open**, select the generated file.
4. **Animation → Save As**, same filename, no edits. This is the step that signs it and rewrites the placeholder `Device="PACLED64" Id="0"` attributes to the real `LedHwType=<code> Id=<real id>` pairing.
5. Copy the signed output into `<ledblinky_dir>\lwa\`.
6. Assign it via `spindoctor ledblinky patch-settings --fe-lwa "<name>.lwax" --apply` (or `--ss-lwa`, or by hand in LedBlinky Config) and test through the real HyperSpin frontend — **not** the Animation Editor's own "Run LED Animation" preview, which is known to flash/stutter unreliably on this cabinet even when the real playback path is smooth.

Do not attempt to automate step 2 with GUI scripting (AutoHotkey etc.) unless explicitly asked — it was considered and deliberately skipped as not worth the fragility for a 10-second manual step.

## Known gotcha: `LightFEControls=1`

If the resulting animation looks right except some buttons stay a static color (commonly white) while browsing HyperSpin: that's `Settings.ini`'s `[FEOptions] LightFEControls=1` (UI label: **"Light HyperSpin Controls"**) overriding HyperSpin's active-navigation buttons with a fixed color, by design — not a bug in the generated file. It's an either/or: fixed "this button is usable" color on those specific controls (`=1`, customizable via LedBlinky Config's Controls Editor FE edit mode, not stuck at white) or full-panel synced animation with no exceptions (`=0`). Confirmed fix already applied on this cabinet: `LightFEControls=0`.

## Tests

`tests/test_lwax.py` covers the parser, the generic builder, and the fade preset against a small synthetic `LEDBlinkyInputMap.xml`. Run `python3 -m pytest tests/test_lwax.py -q` after touching `spindoctor/lwax.py`.
