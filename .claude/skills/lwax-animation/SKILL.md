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

The CLI only builds a **uniform color-cycle fade** across the chosen controls. For anything spatial (sweeps, chases, radial pulses, rain), don't extend the CLI — the column/row/ring groupings needed are cabinet-specific data, not general-purpose flags, and a one-off script is faster than designing flag syntax for it. This matches explicit user feedback: CLI flags felt like *more* work than the Animation Editor's built-in wizard for a single simple fade; the CLI only pays for itself on effects that are tedious to hand-build frame-by-frame in the editor (spatial/randomized ones). Use the Python API directly:

- `LwaxAnimation.add_frame(duration_ms, {label: (r, g, b), ...})` — fully generic per-frame, per-control primitive. Everything else is built on this.
- `build_color_cycle(controllers, colors, steps_per_leg, duration_ms, labels)` — uniform fade through N colors (what the CLI wraps).
- `build_wave(controllers, groups, lead_color, trail_color=None, lag=1, frames_per_step, duration_ms)` — moves a leading color (plus an optional trailing second color a few groups behind) across an ordered list of label-groups, wrapping continuously. `groups[i]` is "whatever occupies position i" — reuse this same function for left/right sweeps, up/down sweeps, *and* radial pulses; direction is entirely the order `groups` is passed in (reverse the list to reverse direction, no separate flag).
- `build_rain(controllers, drop_groups, colors, frames_per_step, total_frames, min_gap_frames, max_gap_frames, seed)` — independent, randomly-timed drop sequences per group (each lights its labels in order, e.g. top-then-bottom), so multiple columns flash out of sync. Deterministic given `seed` — regenerating with "make it slower" just means changing one parameter, output is otherwise identical.

### This cabinet's layout groups (inferred from the panel diagram + pin table in the arch doc — confirm with the user before trusting blindly, cheap to redo if wrong)

**Columns, left to right** (14 groups — use for left/right sweeps, and as the ring order for a trackball-centered radial pulse: ring 0 = column 1):

```python
COLUMNS = [
    ["TRACKBALL", "LMOUSE", "RMOUSE"],
    ["P1COIN"], ["P1START"],
    ["P1B1", "P1B5"], ["P1B2", "P1B6"], ["P1B3", "P1B7"], ["P1B4", "P1B8"],
    ["SELECT", "EXIT", "SEARCH", "PAUSE"],
    ["P2B1", "P2B5"], ["P2B2", "P2B6"], ["P2B3", "P2B7"], ["P2B4", "P2B8"],
    ["P2COIN"], ["P2START"],
]
```

**Rows, top to bottom** (only 3 bands exist — this cabinet's button grid has just 2 rows per player):

```python
ROW_ABOVE = ["TRACKBALL", "LMOUSE", "RMOUSE", "P1COIN", "P1START",
             "SELECT", "EXIT", "SEARCH", "PAUSE", "P2COIN", "P2START"]
ROW_TOP = ["P1B1", "P1B2", "P1B3", "P1B4", "P2B1", "P2B2", "P2B3", "P2B4"]
ROW_BOTTOM = ["P1B5", "P1B6", "P1B7", "P1B8", "P2B5", "P2B6", "P2B7", "P2B8"]
ROWS = [ROW_ABOVE, ROW_TOP, ROW_BOTTOM]
```

**Rain drop groups** (top-to-bottom per column; single-row controls get a degenerate 1-element "drop" so the whole panel participates, not just the two player button grids):

```python
RAIN_DROP_GROUPS = [
    ["P1B1", "P1B5"], ["P1B2", "P1B6"], ["P1B3", "P1B7"], ["P1B4", "P1B8"],
    ["P2B1", "P2B5"], ["P2B2", "P2B6"], ["P2B3", "P2B7"], ["P2B4", "P2B8"],
    ["TRACKBALL"], ["LMOUSE"], ["RMOUSE"], ["P1COIN"], ["P1START"],
    ["SELECT"], ["EXIT"], ["SEARCH"], ["PAUSE"], ["P2COIN"], ["P2START"],
]
```

A worked example generating 7 effects (4 directional sweeps, rain, and an outward/inward radial pulse) lives in this session's history — recreate similarly: parse the real `LEDBlinkyInputMap.xml`, call `build_wave`/`build_rain` with the groups above and whatever colors/timings are requested, validate with `xml.etree.ElementTree.fromstring()` before handing the file over.

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

`tests/test_lwax.py` covers the parser, the generic builder, and all three presets (`build_color_cycle`, `build_wave`, `build_rain`) against a small synthetic `LEDBlinkyInputMap.xml`. Run `python3 -m pytest tests/test_lwax.py -q` after touching `spindoctor/lwax.py`.
