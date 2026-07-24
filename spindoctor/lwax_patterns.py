#!/usr/bin/env python3
"""Generate a fresh, colour-diverse batch of LEDBlinky ``.lwax`` animations.

Builds on the generic builders in ``spindoctor.lwax`` plus this cabinet's real
layout groups to emit a whole library of raw *unsigned* ``.lwax`` files. The
public entry point is :func:`generate_batch` (controllers, out_dir); it is
shared by three callers so the logic lives in exactly one place:

- ``scripts/generate_lwax_patterns.py`` (the standalone script) via :func:`main`,
- ``spindoctor ledblinky lwax batch`` (the CLI command),
- and the GUI Custom Command dropdown, which shells out to that CLI command.

Design goals:
- ~22 effect families x 5 variants, plus a solid-colour breathe library and two
  colour-cycle files.
- Exactly one "moving fading rainbow" variant per family.
- Every fixed-colour variant draws from a single global palette with **no
  colour reused anywhere in the batch** -- every button value differs file to
  file. Each family spreads over slow / medium / fast timing.

These files still need signing on the cabinet (open in
LEDBlinkyAnimationEditor.exe -> Save As) before LedBlinky Config will manage
them; runtime playback via Settings.ini does not check the signature.
"""
from __future__ import annotations

import colorsys
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .lwax import (
    LwaxAnimation,
    build_alternate,
    build_color_cycle,
    build_fill,
    build_drain,
    build_rain,
    build_rainbow_scroll,
    build_wave,
    merge_animations,
    parse_input_map,
)

# --------------------------------------------------------------------------- #
# This cabinet's layout groups -- copied verbatim from
# .claude/skills/lwax-animation/SKILL.md (single source of truth).
# --------------------------------------------------------------------------- #
LEFT_RIGHT_ORDER = [
    ["P1START", "P1COIN", "P1B1", "P1B5"],
    ["P1B2", "P1B6"],
    ["P1B3", "P1B7"],
    ["P1B4", "P1B8"],
    ["LMOUSE"], ["RMOUSE"], ["SELECT"],
    ["TRACKBALL"],
    ["EXIT"], ["SEARCH"], ["PAUSE"],
    ["P2B1", "P2B5"],
    ["P2B2", "P2START", "P2B6"],
    ["P2B3", "P2COIN", "P2B7"],
    ["P2B4", "P2B8"],
]

ROW_ABOVE = ["P1START", "P1COIN", "LMOUSE", "RMOUSE", "SELECT", "EXIT", "SEARCH", "PAUSE", "P2COIN", "P2START"]
ROW_TOP = ["P1B1", "P1B2", "P1B3", "P1B4", "TRACKBALL", "P2B1", "P2B2", "P2B3", "P2B4"]
ROW_BOTTOM = ["P1B5", "P1B6", "P1B7", "P1B8", "P2B5", "P2B6", "P2B7", "P2B8"]
ROWS = [ROW_ABOVE, ROW_TOP, ROW_BOTTOM]

TRACKBALL_INDEX = next(i for i, g in enumerate(LEFT_RIGHT_ORDER) if "TRACKBALL" in g)
_ring_map: dict[int, list[str]] = {}
for _i, _group in enumerate(LEFT_RIGHT_ORDER):
    _ring_map.setdefault(abs(_i - TRACKBALL_INDEX), []).extend(_group)
RADIAL_RINGS = [_ring_map[d] for d in sorted(_ring_map)]

CYCLONE_LOOP = [[l] for l in ROW_TOP] + [[l] for l in ROW_BOTTOM[::-1]]

RAIN_DROP_GROUPS = [
    ["P1B1", "P1B5"], ["P1B2", "P1B6"], ["P1B3", "P1B7"], ["P1B4", "P1B8"],
    ["P2B1", "P2B5"], ["P2B2", "P2B6"], ["P2B3", "P2B7"], ["P2B4", "P2B8"],
    ["TRACKBALL"], ["LMOUSE"], ["RMOUSE"], ["P1COIN"], ["P1START"],
    ["SELECT"], ["EXIT"], ["SEARCH"], ["PAUSE"], ["P2COIN"], ["P2START"],
]

# Checkerboard: split the left-to-right columns by parity.
CHECKER_A = [l for i, g in enumerate(LEFT_RIGHT_ORDER) if i % 2 == 0 for l in g]
CHECKER_B = [l for i, g in enumerate(LEFT_RIGHT_ORDER) if i % 2 == 1 for l in g]

# The physical admin / cabinet row, left-to-right (see the Master control
# reference in docs/cabinet-architecture-reference.md). These are the six
# controls the user thinks of as "admin buttons".
ADMIN_LABELS = ["LMOUSE", "RMOUSE", "SELECT", "EXIT", "SEARCH", "PAUSE"]

# Maximally-distinct, easy-to-name colours for the calibration animation, in a
# fixed order so callers can print a legend. (name, (r,g,b)) 0-48.
CALIBRATION_LEGEND = [
    ("red",     (48, 0, 0)),
    ("green",   (0, 48, 0)),
    ("blue",    (0, 0, 48)),
    ("yellow",  (48, 48, 0)),
    ("magenta", (48, 0, 48)),
    ("cyan",    (0, 48, 48)),
    ("orange",  (48, 20, 0)),
    ("white",   (48, 48, 48)),
    ("purple",  (24, 0, 48)),
    ("lime",    (20, 48, 0)),
    ("pink",    (48, 16, 32)),
    ("teal",    (0, 44, 36)),
]

# Approximate 2D position per control, for effects that need real geometry
# (ripple rings, spiral/radar sweep): x = column index in LEFT_RIGHT_ORDER,
# y = row band (0 above, 1 top/trackball, 2 bottom). Not physical inches, but
# faithful enough for distance/angle-based effects on this 2-row-per-player grid.
def _build_label_pos():
    xof = {l: i for i, g in enumerate(LEFT_RIGHT_ORDER) for l in g}
    yof = {l: y for y, row in enumerate(ROWS) for l in row}
    return {l: (xof[l], yof.get(l, 1)) for l in xof}

LABEL_POS = _build_label_pos()
ALL_LABELS = list(LABEL_POS)
TRACKBALL_POS = LABEL_POS["TRACKBALL"]

# --------------------------------------------------------------------------- #
# Colour helpers.
# --------------------------------------------------------------------------- #
Color = tuple

def hsv48(h: float, s: float, v: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (round(r * 48), round(g * 48), round(b * 48))

def dim(color, factor: float):
    return tuple(round(c * factor) for c in color)

def _rgb_to_hue(color) -> float:
    """Hue (0..1) of a 0-48 RGB colour, for driving a single-hue plasma."""
    r, g, b = (c / 48 for c in color)
    return colorsys.rgb_to_hsv(r, g, b)[0]

def lighten(color, factor: float):
    return tuple(min(48, round(c + (48 - c) * factor)) for c in color)

# A full-spectrum rainbow used by the rainbow fade + rainbow rain variants.
SPECTRUM = [hsv48(i / 12, 1.0, 1.0) for i in range(12)]

_HUE_NAMES = [
    "red", "orange", "amber", "yellow", "lime", "green",
    "spring", "aqua", "cyan", "azure", "blue", "indigo",
    "violet", "magenta", "rose", "crimson",
]

def _hue_name(h: float) -> str:
    return _HUE_NAMES[int((h % 1.0) * len(_HUE_NAMES)) % len(_HUE_NAMES)]

_SHADES = [
    (1.00, 1.00, "vivid"),
    (1.00, 0.72, "deep"),
    (0.55, 1.00, "soft"),
    (0.85, 0.58, "dark"),
]

def _build_master_palette(n: int = 48):
    """A globally unique, well-spread palette of vivid distinct colours.

    Walks the hue wheel and rotates through four shade profiles so neighbours
    differ in both hue and lightness. Returns ``[(shade, hue, (r,g,b)), ...]``
    where ``shade``/``hue`` are plain lower-case words (e.g. "vivid", "red") --
    the hue word is what ends up in the file name, the shade adds detail in the
    README only.
    """
    palette = []
    for i in range(n):
        h = i / n
        s, v, shade = _SHADES[i % len(_SHADES)]
        palette.append((shade, _hue_name(h), hsv48(h, s, v)))
    return palette

def _stride(entries, step: int):
    """Reorder so sequential consumption hops far around the hue wheel each
    time -- gives every family a diverse, contrasting spread of hues instead of
    a run of near-neighbours. ``step`` must be coprime with ``len(entries)`` so
    the result is a full permutation (48 & 13 are coprime)."""
    n = len(entries)
    return [entries[(i * step) % n] for i in range(n)]

# Large enough that every fixed-colour variant across all families gets a
# globally unique colour. 120 & 37 are coprime, so the stride is a full
# permutation that hops far around the wheel on each take.
MASTER_PALETTE = _stride(_build_master_palette(240), 37)


class Palette:
    """Hands out colours from MASTER_PALETTE with no repeats across the batch."""

    def __init__(self, entries):
        self._entries = list(entries)
        self._i = 0

    def take(self):
        if self._i >= len(self._entries):
            raise RuntimeError("Ran out of unique palette colours; enlarge MASTER_PALETTE.")
        entry = self._entries[self._i]
        self._i += 1
        return entry  # (shade, hue, color)

    def take_n(self, k: int):
        return [self.take() for _ in range(k)]

    @property
    def used(self) -> int:
        return self._i


# --------------------------------------------------------------------------- #
# Speed tiers.
# --------------------------------------------------------------------------- #
FADE_SPEED = {"slow": (64, 45), "medium": (48, 40), "fast": (24, 30)}          # steps_per_leg, duration_ms
WAVE_SPEED = {"slow": (10, 45), "medium": (6, 40), "fast": (3, 30)}            # frames_per_step, duration_ms
BAR_SPEED = {"slow": (7, 45), "medium": (4, 40), "fast": (2, 30)}             # frames_per_step, duration_ms (fill/drain)
RAIN_SPEED = {                                                                 # fps, dur, min_gap, max_gap, total
    "slow": (8, 45, 20, 90, 700),
    "medium": (5, 40, 10, 60, 600),
    "fast": (3, 30, 6, 36, 500),
}
SCROLL_SPEED = {                                                               # total_frames, cycles, duration_ms
    "slow": (160, 1, 45),
    "medium": (96, 1, 40),
    "fast": (60, 2, 30),
}
CHECKER_SPEED = {"slow": 600, "medium": 400, "fast": 200}                      # hold_ms
HEART_SPEED = {"slow": (6, 45, 26), "medium": (4, 40, 16), "fast": (3, 30, 10)}  # up/down frames, dur, rest
STROBE_SPEED = {"slow": (4, 4, 45), "medium": (2, 2, 35), "fast": (1, 1, 25)}    # on, off, dur

# Breathe = whole panel fading a single solid colour in and out. steps_per_leg
# is per half-breath (fade-in or fade-out); duration_ms is per frame. slow ~5.8s
# per full breath, medium ~3.8s, fast ~2.2s.
BREATHE_SPEED = {"slow": (64, 45), "medium": (48, 40), "fast": (36, 30)}        # steps_per_leg, duration_ms

# Named solid colours for the breathe family, spanning the spectrum plus a few
# whites. Values are 0-48 per channel (PAC-LED64 range). Pick favourites by name.
# Three sets: standard bright, extra-vivid (deep/saturated punch), and pastels
# (soft, desaturated). File names get a "vivid_"/"pastel_" prefix accordingly.
BREATHE_COLORS = [
    ("red",        (48, 0, 0)),
    ("crimson",    (48, 0, 8)),
    ("rose",       (48, 4, 20)),
    ("pink",       (48, 12, 30)),
    ("coral",      (48, 16, 10)),
    ("orange",     (48, 18, 0)),
    ("amber",      (48, 30, 0)),
    ("gold",       (48, 38, 0)),
    ("yellow",     (48, 48, 0)),
    ("chartreuse", (32, 48, 0)),
    ("lime",       (18, 48, 0)),
    ("green",      (0, 48, 0)),
    ("emerald",    (0, 48, 18)),
    ("mint",       (0, 48, 28)),
    ("teal",       (0, 44, 36)),
    ("turquoise",  (0, 42, 44)),
    ("cyan",       (0, 48, 48)),
    ("sky",        (0, 28, 48)),
    ("azure",      (0, 16, 48)),
    ("blue",       (0, 0, 48)),
    ("indigo",     (14, 0, 48)),
    ("violet",     (26, 0, 48)),
    ("purple",     (36, 0, 48)),
    ("magenta",    (48, 0, 48)),
    ("white",      (48, 48, 48)),
    ("warm_white", (48, 40, 28)),
]

# Hue anchors used to synthesize the vivid and pastel breathe sets.
_BREATHE_HUES = [
    ("red", 0.00), ("orange", 0.06), ("amber", 0.10), ("yellow", 0.15),
    ("lime", 0.22), ("green", 0.33), ("emerald", 0.42), ("cyan", 0.50),
    ("azure", 0.57), ("blue", 0.66), ("indigo", 0.72), ("violet", 0.78),
    ("purple", 0.82), ("magenta", 0.88), ("pink", 0.94),
]
# Extra-vivid: full saturation + full value -- the deepest, brightest punch.
BREATHE_VIVID = [(f"vivid_{name}", hsv48(h, 1.0, 1.0)) for name, h in _BREATHE_HUES]
# Pastel: low saturation, full value -- soft, milky, gentle.
BREATHE_PASTEL = [(f"pastel_{name}", hsv48(h, 0.35, 1.0)) for name, h in _BREATHE_HUES]

# Speed assigned to the 5 variants of each family (index 4 = the rainbow one).
# Guarantees at least one slow, one medium and one fast per family.
VARIANT_SPEEDS = ["slow", "medium", "fast", "slow", "medium"]


# --------------------------------------------------------------------------- #
# Local "moving fading rainbow" builders (family rainbow variants for effects
# whose library builder only takes a single fixed colour). Same HSV->0-48
# technique as build_rainbow_scroll; built on the generic add_frame primitive.
# --------------------------------------------------------------------------- #
def build_rainbow_comet(controllers, groups, frames_per_step=6, duration_ms=40, trail=3):
    """A single bright front that shifts hue as it travels the loop, dragging a
    fading multi-hue tail behind it -- a glowing rainbow comet."""
    anim = LwaxAnimation(controllers)
    all_labels = [l for g in groups for l in g]
    n = len(groups)
    off = (0, 0, 0)
    for pos in range(n):
        for _ in range(frames_per_step):
            colors = {l: off for l in all_labels}
            for t in range(trail + 1):
                p = (pos - t) % n
                bright = 1.0 - (t / (trail + 1)) * 0.85
                col = hsv48(p / n, 1.0, bright)
                for l in groups[p]:
                    colors[l] = col
            anim.add_frame(duration_ms, colors)
    return anim

def build_rainbow_fill(controllers, groups, frames_per_step=4, duration_ms=40, hold_frames=40):
    """Accumulating bar where each group joins at its own hue, so the panel fills
    into a full rainbow gradient, then the gradient scrolls (glows) once and the
    file loops back to empty."""
    anim = LwaxAnimation(controllers)
    all_labels = [l for g in groups for l in g]
    n = len(groups)
    off = (0, 0, 0)
    lit: list[int] = []
    for idx in range(n):
        lit.append(idx)
        for _ in range(frames_per_step):
            colors = {l: off for l in all_labels}
            for j in lit:
                col = hsv48(j / n, 1.0, 1.0)
                for l in groups[j]:
                    colors[l] = col
            anim.add_frame(duration_ms, colors)
    for f in range(hold_frames):
        phase = f / max(1, hold_frames)
        colors = {}
        for j in range(n):
            col = hsv48(j / n + phase, 1.0, 1.0)
            for l in groups[j]:
                colors[l] = col
        anim.add_frame(duration_ms, colors)
    return anim

def build_rainbow_drain(controllers, groups, frames_per_step=4, duration_ms=40, hold_full_frames=25, hold_empty_frames=10):
    """Starts as a full rainbow gradient, then extinguishes groups one at a time
    -- a rainbow countdown -- holds empty, and loops back to full."""
    anim = LwaxAnimation(controllers)
    all_labels = [l for g in groups for l in g]
    n = len(groups)
    off = (0, 0, 0)

    def full_frame(phase=0.0):
        colors = {}
        for j in range(n):
            col = hsv48(j / n + phase, 1.0, 1.0)
            for l in groups[j]:
                colors[l] = col
        return colors

    for f in range(hold_full_frames):
        anim.add_frame(duration_ms, full_frame(f / max(1, hold_full_frames) * 0.5))

    remaining = list(range(n))
    for gi in range(n):
        remaining.remove(gi)
        for _ in range(frames_per_step):
            colors = {l: off for l in all_labels}
            for j in remaining:
                col = hsv48(j / n, 1.0, 1.0)
                for l in groups[j]:
                    colors[l] = col
            anim.add_frame(duration_ms, colors)

    for _ in range(hold_empty_frames):
        anim.add_frame(duration_ms, {l: off for l in all_labels})
    return anim

def build_rainbow_checker(controllers, group_a, group_b, hold_ms=400, cycles=16):
    """Two interleaved halves swapping in lockstep, with both hues advancing
    around the wheel every cycle -- a glowing rainbow checkerboard."""
    anim = LwaxAnimation(controllers)
    for c in range(cycles):
        hue_a = c / cycles
        hue_b = hue_a + 0.5
        col_a = hsv48(hue_a, 1.0, 1.0)
        col_b = hsv48(hue_b, 1.0, 1.0)
        anim.add_frame(hold_ms, {**{l: col_a for l in group_a}, **{l: col_b for l in group_b}})
        anim.add_frame(hold_ms, {**{l: col_b for l in group_a}, **{l: col_a for l in group_b}})
    return anim


# --------------------------------------------------------------------------- #
# Extra pulse families (local builders on top of add_frame / merge_animations).
# --------------------------------------------------------------------------- #
def _pulse(anim, labels, color, up, down, duration_ms, peak=1.0):
    """Append a single fade-up-then-down pulse of ``color`` across ``labels``."""
    for s in range(up):
        anim.add_frame(duration_ms, {l: dim(color, (s + 1) / up * peak) for l in labels})
    for s in range(down):
        anim.add_frame(duration_ms, {l: dim(color, (1 - (s + 1) / down) * peak) for l in labels})


def build_heartbeat(controllers, color, up=4, down=4, rest_frames=16, duration_ms=40, cycles=6):
    """Whole panel: two quick pulses (a lub-dub) then a rest, repeating."""
    anim = LwaxAnimation(controllers)
    labels = anim.labels
    off = {l: (0, 0, 0) for l in labels}
    for _ in range(cycles):
        _pulse(anim, labels, color, up, down, duration_ms, peak=1.0)
        _pulse(anim, labels, color, up, down, duration_ms, peak=0.7)
        for _ in range(rest_frames):
            anim.add_frame(duration_ms, off)
    return anim


def build_rainbow_heartbeat(controllers, up=4, down=4, rest_frames=16, duration_ms=40, cycles=12):
    """Heartbeat whose colour advances around the wheel every beat."""
    anim = LwaxAnimation(controllers)
    labels = anim.labels
    off = {l: (0, 0, 0) for l in labels}
    for c in range(cycles):
        col1 = hsv48(c / cycles, 1.0, 1.0)
        col2 = hsv48(c / cycles + 0.04, 1.0, 1.0)
        _pulse(anim, labels, col1, up, down, duration_ms, peak=1.0)
        _pulse(anim, labels, col2, up, down, duration_ms, peak=0.7)
        for _ in range(rest_frames):
            anim.add_frame(duration_ms, off)
    return anim


def build_strobe(controllers, color, on_frames=2, off_frames=2, duration_ms=30, cycles=30, rainbow=False):
    """Whole panel flashing on/off. With ``rainbow`` each flash is a new hue."""
    anim = LwaxAnimation(controllers)
    labels = anim.labels
    off = {l: (0, 0, 0) for l in labels}
    for c in range(cycles):
        col = hsv48(c / cycles, 1.0, 1.0) if rainbow else color
        for _ in range(on_frames):
            anim.add_frame(duration_ms, {l: col for l in labels})
        for _ in range(off_frames):
            anim.add_frame(duration_ms, off)
    return anim


def build_marquee(controllers, groups, color, spacing=3, frames_per_step=4, duration_ms=40, rainbow=False):
    """Theater/marquee chase: every ``spacing``-th group lit, the lit set
    marching one step each frame so the gaps travel around the loop."""
    anim = LwaxAnimation(controllers)
    all_labels = [l for g in groups for l in g]
    n = len(groups)
    off = (0, 0, 0)
    for offset in range(n):
        for _ in range(frames_per_step):
            colors = {l: off for l in all_labels}
            for i, group in enumerate(groups):
                if (i - offset) % spacing == 0:
                    col = hsv48(((i - offset) / n) % 1.0, 1.0, 1.0) if rainbow else color
                    for l in group:
                        colors[l] = col
            anim.add_frame(duration_ms, colors)
    return anim


def build_bounce(controllers, groups, color, frames_per_step=4, duration_ms=40, cycles=3, rainbow=False):
    """A VU-meter bar that fills up to full then recedes to empty, repeating."""
    anim = LwaxAnimation(controllers)
    all_labels = [l for g in groups for l in g]
    n = len(groups)
    off = (0, 0, 0)

    def col_for(j):
        return hsv48(j / n, 1.0, 1.0) if rainbow else color

    for _ in range(cycles):
        for level in list(range(1, n + 1)) + list(range(n - 1, -1, -1)):
            for _ in range(frames_per_step):
                colors = {l: off for l in all_labels}
                for j in range(level):
                    for l in groups[j]:
                        colors[l] = col_for(j)
                anim.add_frame(duration_ms, colors)
    return anim


def build_race_from_center(controllers, color_left, color_right, frames_per_step=6, duration_ms=40):
    """Two comets launching from the trackball and racing outward to each edge,
    each side its own colour (merged into one animation)."""
    left = [list(g) for g in reversed(LEFT_RIGHT_ORDER[:TRACKBALL_INDEX])]
    right = [list(g) for g in LEFT_RIGHT_ORDER[TRACKBALL_INDEX + 1:]]
    a = build_wave(controllers, left, color_left, trail_color=dim(color_left, 0.3),
                   frames_per_step=frames_per_step, duration_ms=duration_ms)
    b = build_wave(controllers, right, color_right, trail_color=dim(color_right, 0.3),
                   frames_per_step=frames_per_step, duration_ms=duration_ms)
    return merge_animations(a, b)


def build_rainbow_race(controllers, frames_per_step=5, duration_ms=35):
    """Two rainbow comets racing outward from the trackball to both edges."""
    left = [list(g) for g in reversed(LEFT_RIGHT_ORDER[:TRACKBALL_INDEX])]
    right = [list(g) for g in LEFT_RIGHT_ORDER[TRACKBALL_INDEX + 1:]]
    a = build_rainbow_comet(controllers, left, frames_per_step=frames_per_step, duration_ms=duration_ms)
    b = build_rainbow_comet(controllers, right, frames_per_step=frames_per_step, duration_ms=duration_ms)
    return merge_animations(a, b)


def build_rainbow_breathe(controllers, total_frames=192, duration_ms=45, breaths=4):
    """Whole panel breathing (brightness rising and falling) while its hue
    slowly cycles once around the wheel -- a glowing rainbow breath."""
    anim = LwaxAnimation(controllers)
    labels = anim.labels
    for f in range(total_frames):
        hue = f / total_frames
        val = (1 - math.cos(2 * math.pi * breaths * f / total_frames)) / 2  # 0->1->0
        col = hsv48(hue, 1.0, val)
        anim.add_frame(duration_ms, {l: col for l in labels})
    return anim


# --------------------------------------------------------------------------- #
# Geometry / noise families (ripple, spiral, comet, plasma, twinkle, candle,
# gradient) plus the two multi-colour cycle families. All deterministic.
# --------------------------------------------------------------------------- #
_MAXR = 14.5  # ~ max distance across the LABEL_POS grid


def _dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def build_ripple(controllers, color=None, drops=6, ring_frames=16, gap_frames=6,
                 duration_ms=40, seed=0, rainbow=False):
    """Raindrop impacts: each drop lights an expanding, fading ring out of a
    random button, one after another."""
    import random
    rng = random.Random(seed)
    anim = LwaxAnimation(controllers)
    off = (0, 0, 0)
    for d in range(drops):
        impact = LABEL_POS[ALL_LABELS[rng.randrange(len(ALL_LABELS))]]
        base_hue = rng.random()
        for t in range(ring_frames):
            radius = (t + 1) / ring_frames * _MAXR
            bright = 1 - t / ring_frames
            colors = {l: off for l in ALL_LABELS}
            for l in ALL_LABELS:
                if abs(_dist(LABEL_POS[l], impact) - radius) < 1.1:
                    col = hsv48((base_hue + radius / _MAXR) % 1.0, 1.0, bright) if rainbow \
                        else dim(color, bright)
                    colors[l] = col
            anim.add_frame(duration_ms, colors)
        for _ in range(gap_frames):
            anim.add_frame(duration_ms, {l: off for l in ALL_LABELS})
    return anim


def build_spiral(controllers, color=None, revolutions=3, frames_per_rev=48,
                 width=0.5, duration_ms=40, rainbow=False):
    """A radar-style wedge sweeping around the trackball (the always-lit hub),
    with a fading trail. A wide wedge keeps it legible on this flat 2-row panel,
    where controls cluster near the left/right horizontal rather than all around."""
    anim = LwaxAnimation(controllers)
    cx, cy = TRACKBALL_POS
    ang = {}
    for l, (x, y) in LABEL_POS.items():
        if (x, y) == (cx, cy):
            ang[l] = None  # centre pivot
        else:
            ang[l] = (math.atan2(y - cy, x - cx) / (2 * math.pi)) % 1.0
    off = (0, 0, 0)
    total = revolutions * frames_per_rev
    for f in range(total):
        sweep = (f / frames_per_rev) % 1.0
        colors = {}
        for l, a in ang.items():
            if a is None:
                colors[l] = hsv48(sweep, 1.0, 1.0) if rainbow else color
                continue
            behind = (sweep - a) % 1.0
            if behind < width:
                bright = 1 - behind / width
                colors[l] = hsv48(a, 1.0, bright) if rainbow else dim(color, bright)
            else:
                colors[l] = off
        anim.add_frame(duration_ms, colors)
    return anim


def build_comet(controllers, groups, color=None, tail=3.5, loops=2,
                frames_per_leg=90, duration_ms=40, rainbow=False):
    """A glowing head that eases across the loop and back (slows at each end),
    with a soft glow falling off on both sides -- a comet with gravity."""
    anim = LwaxAnimation(controllers)
    all_labels = [l for g in groups for l in g]
    n = len(groups)
    off = (0, 0, 0)
    total = loops * frames_per_leg
    for f in range(total):
        head = (n - 1) * (1 - math.cos(2 * math.pi * f / frames_per_leg)) / 2  # eased bounce
        colors = {l: off for l in all_labels}
        for i, group in enumerate(groups):
            bright = max(0.0, 1 - abs(i - head) / tail)
            if bright <= 0:
                continue
            col = hsv48((i / n) % 1.0, 1.0, bright) if rainbow else dim(color, bright)
            for l in group:
                colors[l] = col
        anim.add_frame(duration_ms, colors)
    return anim


def build_plasma(controllers, hue=0.0, total_frames=180, duration_ms=45, rainbow=False):
    """A lava-lamp/plasma field of overlapping sine waves. Monochrome mode
    undulates brightness in one hue; rainbow mode drifts the whole hue field.
    Integer wave multipliers keep it seamlessly loopable."""
    anim = LwaxAnimation(controllers)
    for f in range(total_frames):
        t = f / total_frames
        colors = {}
        for l, (x, y) in LABEL_POS.items():
            v = (math.sin(x * 0.5 + 2 * math.pi * t)
                 + math.sin(y * 1.1 + 2 * math.pi * 2 * t)
                 + math.sin((x + y) * 0.4 + 2 * math.pi * 1 * t))
            v = (v + 3) / 6  # 0..1
            if rainbow:
                colors[l] = hsv48((v + t) % 1.0, 1.0, 1.0)
            else:
                colors[l] = hsv48(hue, 1.0, 0.25 + 0.75 * v)
        anim.add_frame(duration_ms, colors)
    return anim


def build_twinkle(controllers, color=None, total_frames=320, twinkles=90,
                  fade=9, duration_ms=45, seed=0, rainbow=False):
    """A calm dark starfield: scattered buttons softly fade in and out at random
    times. Fixed colour, or a different random hue per star in rainbow mode."""
    import random
    rng = random.Random(seed)
    off = (0, 0, 0)
    # brightness[frame][label]
    bright = [dict() for _ in range(total_frames)]
    hues = {}
    for _ in range(twinkles):
        start = rng.randrange(total_frames)
        label = ALL_LABELS[rng.randrange(len(ALL_LABELS))]
        hue = rng.random()
        for k in range(fade):
            fr = start + k
            if fr >= total_frames:
                break
            b = 1 - abs((k - fade / 2) / (fade / 2))  # triangular 0->1->0
            if b > bright[fr].get(label, 0):
                bright[fr][label] = b
                hues[(fr, label)] = hue
    anim = LwaxAnimation(controllers)
    for fr in range(total_frames):
        colors = {l: off for l in ALL_LABELS}
        for label, b in bright[fr].items():
            colors[label] = hsv48(hues[(fr, label)], 0.9, b) if rainbow else dim(color, b)
        anim.add_frame(duration_ms, colors)
    return anim


def build_candle(controllers, color=None, total_frames=260, duration_ms=45,
                 seed=0, rainbow=False):
    """Whole panel glowing like a flame: a smoothed brightness flicker (random
    walk) in one colour. Rainbow mode slowly drifts the hue while it flickers."""
    import random
    rng = random.Random(seed)
    anim = LwaxAnimation(controllers)
    level = 0.7
    for f in range(total_frames):
        target = rng.uniform(0.45, 1.0)
        level += (target - level) * 0.35
        if rainbow:
            col = hsv48((f / total_frames) % 1.0, 0.85, level)
        else:
            col = dim(color, level)
        anim.add_frame(duration_ms, {l: col for l in ALL_LABELS})
    return anim


def build_gradient_breathe(controllers, color_a=None, color_b=None, total_frames=192,
                           duration_ms=45, breaths=3, rainbow=False):
    """A two-colour gradient laid across the panel that both breathes (brightness
    rising/falling) and slowly slides. Rainbow mode uses the full spectrum."""
    anim = LwaxAnimation(controllers)
    groups = LEFT_RIGHT_ORDER
    n = len(groups)
    for f in range(total_frames):
        val = (1 - math.cos(2 * math.pi * breaths * f / total_frames)) / 2
        shift = f / total_frames
        colors = {}
        for i, group in enumerate(groups):
            frac = (i / n + shift) % 1.0
            if rainbow:
                col = hsv48(frac, 1.0, val)
            else:
                blend = (math.sin(2 * math.pi * frac) + 1) / 2  # smooth a<->b<->a
                mixed = tuple(round(color_a[c] + (color_b[c] - color_a[c]) * blend) for c in range(3))
                col = dim(mixed, val)
            for l in group:
                colors[l] = col
        anim.add_frame(duration_ms, colors)
    return anim


def build_breathe_cycle(controllers, colors, steps=48, duration_ms=45):
    """Whole panel breathes one solid colour off->full->off, then the next
    colour, and so on, looping back to the first."""
    anim = LwaxAnimation(controllers)
    labels = anim.labels
    for c in colors:
        for s in range(steps):
            anim.add_frame(duration_ms, {l: dim(c, (s + 1) / steps) for l in labels})
        for s in range(steps):
            anim.add_frame(duration_ms, {l: dim(c, 1 - (s + 1) / steps) for l in labels})
    return anim


def build_pulse_cycle(controllers, colors, groups=None, frames_per_step=6, duration_ms=40):
    """A radial pulse plays one full outward sweep in the first colour, then
    replays it in the next colour, and so on, looping."""
    if groups is None:
        groups = RADIAL_RINGS
    anim = LwaxAnimation(controllers)
    all_labels = [l for g in groups for l in g]
    n = len(groups)
    off = (0, 0, 0)
    for c in colors:
        trail = dim(c, 0.3)
        for pos in range(n):
            for _ in range(frames_per_step):
                frame = {l: off for l in all_labels}
                for l in groups[pos]:
                    frame[l] = c
                for l in groups[(pos - 1) % n]:
                    frame[l] = trail
                anim.add_frame(duration_ms, frame)
    return anim


def build_calibration(controllers, labels=None, duration_ms=500):
    """Light each control in ``labels`` a distinct, easy-to-name colour and hold
    it steady (a static, looping frame) — a mapping/calibration aid.

    Returns ``(animation, legend)`` where ``legend`` is an ordered list of
    ``(label, colour_name)`` so the caller can print exactly which colour was
    assigned to which control label. Every other wired control is left off, so
    only the calibrated buttons light up. ``labels`` defaults to the admin row
    (:data:`ADMIN_LABELS`); pass an explicit list to calibrate other controls.

    Because it addresses controls by their physical label (the same scheme
    ``.lwax`` animations use), running it identifies which *physical* button
    carries which label — run with ``LightFEControls=0`` so nothing overrides it.
    """
    anim = LwaxAnimation(controllers)
    wired = set(anim.labels)
    target = [l for l in (labels if labels is not None else ADMIN_LABELS)]
    unknown = [l for l in target if l not in wired]
    if unknown:
        raise ValueError(f"Unknown control label(s): {unknown}")
    if len(target) > len(CALIBRATION_LEGEND):
        raise ValueError(
            f"Only {len(CALIBRATION_LEGEND)} distinct calibration colours are "
            f"defined; asked to calibrate {len(target)} controls."
        )

    legend = [(label, CALIBRATION_LEGEND[i][0]) for i, label in enumerate(target)]
    colors = {label: CALIBRATION_LEGEND[i][1] for i, label in enumerate(target)}
    # A couple of identical frames so the file loops as a steady hold.
    for _ in range(2):
        anim.add_frame(duration_ms, dict(colors))
    return anim, legend


# --------------------------------------------------------------------------- #
# Build the batch.
# --------------------------------------------------------------------------- #
# File-name rule: plain, readable, lower-case words joined by single
# underscores -- e.g. ``fade_red_lime_slow.lwax``. Never use spaces, em dashes
# (--), en dashes, or runs of hyphens in a file name. ``slugify`` enforces this
# by collapsing every non-alphanumeric run to a single underscore.
def slugify(text: str) -> str:
    out: list[str] = []
    prev_us = False
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    return "".join(out).strip("_")


def generate_batch(controllers, out_dir):
    """Build the whole colour-diverse batch and write every ``.lwax`` file plus
    a ``README.md`` index into ``out_dir`` (clearing any previous batch first).

    Returns ``(written, palette_used)`` where ``written`` is a list of
    ``(filename, frame_count, description)`` tuples and ``palette_used`` is how
    many unique palette colours were consumed. Cabinet-specific: the effects
    reference this panel's control labels, so ``controllers`` must be this
    cabinet's parsed ``LEDBlinkyInputMap.xml``.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear previously-generated files so renamed variants don't leave stale
    # leftovers behind (this is a full-batch regenerator, not an incremental one).
    for pattern in ("*.lwax", "README.txt", "README.md"):
        for stale in out_dir.glob(pattern):
            stale.unlink()

    pal = Palette(MASTER_PALETTE)
    # (family, filename, animation, human description)
    batch: list[tuple[str, str, LwaxAnimation, str]] = []
    used_names: set[str] = set()

    def add(family, color_slug, speed, animation, colorway, effect):
        """Queue a file named ``family_color_speed.lwax`` (underscores only)."""
        base = slugify(f"{family}_{color_slug}_{speed}")
        name = base
        n = 2
        while name in used_names:
            name = f"{base}_{n}"
            n += 1
        used_names.add(name)
        batch.append((family, f"{name}.lwax", animation, f"{effect}; {colorway}; {speed}"))

    # 1. FADE -- whole-panel cross-fade between two unique colours.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        spl, dur = FADE_SPEED[speed]
        (sa, ha, ca), (sb, hb, cb) = pal.take_n(2)
        anim = build_color_cycle(controllers, [ca, cb], steps_per_leg=spl, duration_ms=dur)
        add("fade", f"{ha}_{hb}", speed, anim, f"{sa} {ha} and {sb} {hb}", "whole panel cross fade")
    anim = build_color_cycle(controllers, SPECTRUM, steps_per_leg=FADE_SPEED["medium"][0],
                             duration_ms=FADE_SPEED["medium"][1])
    add("fade", "rainbow", "medium", anim, "full spectrum", "whole panel rainbow fade")

    # 2. SWEEP / CHASE -- travelling fronts across the left-to-right order.
    s = VARIANT_SPEEDS[0]; fps, dur = WAVE_SPEED[s]
    (sh0, h0, c0) = pal.take()
    add("sweep", h0, s, build_wave(controllers, LEFT_RIGHT_ORDER, c0, trail_color=dim(c0, 0.30),
                                   frames_per_step=fps, duration_ms=dur), f"{sh0} {h0}", "left to right comet")
    s = VARIANT_SPEEDS[1]; fps, dur = WAVE_SPEED[s]
    (sh1, h1, c1) = pal.take()
    add("sweep", h1, s, build_wave(controllers, list(reversed(LEFT_RIGHT_ORDER)), c1, trail_color=dim(c1, 0.30),
                                   frames_per_step=fps, duration_ms=dur), f"{sh1} {h1}", "right to left comet")
    s = VARIANT_SPEEDS[2]; fps, dur = WAVE_SPEED[s]
    (sa, ha, ca), (sb, hb, cb) = pal.take_n(2)
    add("sweep", f"{ha}_{hb}", s, build_wave(controllers, LEFT_RIGHT_ORDER, ca, trail_color=cb,
                                             lag=len(LEFT_RIGHT_ORDER) // 2, frames_per_step=fps, duration_ms=dur),
        f"{sa} {ha} chasing {sb} {hb}", "two colour rivalry chase")
    s = VARIANT_SPEEDS[3]; fps, dur = WAVE_SPEED[s]
    (sh3, h3, c3) = pal.take()
    cylon = LEFT_RIGHT_ORDER + LEFT_RIGHT_ORDER[-2:0:-1]
    add("sweep", h3, s, build_wave(controllers, cylon, c3, trail_color=dim(c3, 0.30),
                                   frames_per_step=fps, duration_ms=dur), f"{sh3} {h3}", "cylon ping pong scanner")
    fps, dur = WAVE_SPEED["fast"]
    add("sweep", "rainbow", "fast", build_rainbow_comet(controllers, LEFT_RIGHT_ORDER, frames_per_step=fps,
                                                         duration_ms=dur), "full spectrum", "glowing rainbow comet")

    # 3. RAIN / CONFETTI -- randomly-timed drops.
    for i in range(3):
        speed = VARIANT_SPEEDS[i]
        fps, dur, mn, mx, tot = RAIN_SPEED[speed]
        (sa, ha, ca), (sb, hb, cb) = pal.take_n(2)
        anim = build_rain(controllers, RAIN_DROP_GROUPS, [ca, cb], frames_per_step=fps,
                          duration_ms=dur, total_frames=tot, min_gap_frames=mn, max_gap_frames=mx, seed=i)
        add("rain", f"{ha}_{hb}", speed, anim, f"{sa} {ha} and {sb} {hb}", "rain falling top to bottom")
    # confetti: one-label groups so it twinkles instead of streaking.
    speed = VARIANT_SPEEDS[3]
    fps, dur, mn, mx, tot = RAIN_SPEED[speed]
    (sa, ha, ca), (sb, hb, cb) = pal.take_n(2)
    confetti_groups = [[l] for g in RAIN_DROP_GROUPS for l in g]
    add("confetti", f"{ha}_{hb}", speed,
        build_rain(controllers, confetti_groups, [ca, cb], frames_per_step=fps, duration_ms=dur,
                   total_frames=tot, min_gap_frames=mn, max_gap_frames=mx, seed=42),
        f"{sa} {ha} and {sb} {hb}", "confetti twinkle")
    fps, dur, mn, mx, tot = RAIN_SPEED["medium"]
    add("rain", "rainbow", "medium",
        build_rain(controllers, RAIN_DROP_GROUPS, SPECTRUM, frames_per_step=fps, duration_ms=dur,
                   total_frames=tot, min_gap_frames=mn, max_gap_frames=mx, seed=7),
        "full spectrum", "rainbow rain")

    # 4. SCROLL -- the whole family is rainbow; vary speed / direction / tone.
    tf, cy, dur = SCROLL_SPEED["slow"]
    add("scroll", "right", "slow", build_rainbow_scroll(controllers, LEFT_RIGHT_ORDER, total_frames=tf,
                                                        cycles=cy, duration_ms=dur), "full spectrum",
        "hue gradient scrolling right")
    tf, cy, dur = SCROLL_SPEED["medium"]
    add("scroll", "right", "medium", build_rainbow_scroll(controllers, LEFT_RIGHT_ORDER, total_frames=tf,
                                                          cycles=cy, duration_ms=dur), "full spectrum",
        "hue gradient scrolling right")
    tf, cy, dur = SCROLL_SPEED["fast"]
    add("scroll", "right", "fast", build_rainbow_scroll(controllers, LEFT_RIGHT_ORDER, total_frames=tf,
                                                        cycles=cy, duration_ms=dur), "full spectrum",
        "hue gradient scrolling right, 2 cycles")
    tf, cy, dur = SCROLL_SPEED["medium"]
    add("scroll", "left", "medium", build_rainbow_scroll(controllers, list(reversed(LEFT_RIGHT_ORDER)),
                                                         total_frames=tf, cycles=cy, duration_ms=dur),
        "full spectrum", "hue gradient scrolling left")
    tf, cy, dur = SCROLL_SPEED["slow"]
    add("scroll", "radial", "slow", build_rainbow_scroll(controllers, RADIAL_RINGS, total_frames=tf, cycles=cy,
                                                         duration_ms=dur, saturation=0.8, value=1.0),
        "full spectrum pastel", "rainbow radiating from trackball")

    # 5. FILL (combo-meter) -- accumulating bar radiating from the trackball.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        fps, dur = BAR_SPEED[speed]
        (sh, h, ca) = pal.take()
        add("fill", h, speed, build_fill(controllers, RADIAL_RINGS, ca, flash_color=lighten(ca, 0.6),
                                         frames_per_step=fps, duration_ms=dur), f"{sh} {h}",
            "combo meter fill and flash")
    fps, dur = BAR_SPEED["fast"]
    add("fill", "rainbow", "fast", build_rainbow_fill(controllers, RADIAL_RINGS, frames_per_step=fps,
                                                      duration_ms=dur), "full spectrum",
        "rainbow gradient fill and glow")

    # 6. DRAIN (countdown / fuse) -- extinguish left-to-right.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        fps, dur = BAR_SPEED[speed]
        (sh, h, ca) = pal.take()
        add("drain", h, speed, build_drain(controllers, LEFT_RIGHT_ORDER, ca, flash_color=lighten(ca, 0.6),
                                           frames_per_step=fps, duration_ms=dur), f"{sh} {h}",
            "countdown drain and flash")
    fps, dur = BAR_SPEED["medium"]
    add("drain", "rainbow", "medium", build_rainbow_drain(controllers, LEFT_RIGHT_ORDER, frames_per_step=fps,
                                                          duration_ms=dur), "full spectrum",
        "rainbow countdown drain")

    # 7. CHECKERBOARD -- interleaved halves swapping in lockstep.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        hold = CHECKER_SPEED[speed]
        (sa, ha, ca), (sb, hb, cb) = pal.take_n(2)
        add("checker", f"{ha}_{hb}", speed, build_alternate_wrapper(controllers, CHECKER_A, CHECKER_B, ca, cb, hold),
            f"{sa} {ha} and {sb} {hb}", "checkerboard blink")
    add("checker", "rainbow", "medium", build_rainbow_checker(controllers, CHECKER_A, CHECKER_B,
                                                              hold_ms=CHECKER_SPEED["medium"]),
        "full spectrum", "rainbow checkerboard")

    # 8. RADIAL PULSE -- rings expanding out of / collapsing into the trackball.
    dirs = [("out", RADIAL_RINGS), ("in", list(reversed(RADIAL_RINGS)))]
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        fps, dur = WAVE_SPEED[speed]
        dname, groups = dirs[i % 2]
        (sh, h, c) = pal.take()
        add("radial", f"{h}_{dname}", speed, build_wave(controllers, groups, c, trail_color=dim(c, 0.3),
                                                         frames_per_step=fps, duration_ms=dur),
            f"{sh} {h}", f"radial pulse {dname}ward")
    fps, dur = WAVE_SPEED["fast"]
    add("radial", "rainbow_out", "fast", build_rainbow_comet(controllers, RADIAL_RINGS, frames_per_step=fps,
                                                             duration_ms=dur), "full spectrum",
        "rainbow radial pulse outward")

    # 9. CYCLONE -- a front spinning around the racetrack loop (top then bottom).
    loops = [("cw", CYCLONE_LOOP), ("ccw", CYCLONE_LOOP[::-1])]
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        fps, dur = WAVE_SPEED[speed]
        lname, groups = loops[i % 2]
        (sh, h, c) = pal.take()
        add("cyclone", f"{h}_{lname}", speed, build_wave(controllers, groups, c, trail_color=dim(c, 0.4),
                                                         frames_per_step=fps, duration_ms=dur),
            f"{sh} {h}", f"cyclone spinning {lname}")
    fps, dur = WAVE_SPEED["fast"]
    add("cyclone", "rainbow_cw", "fast", build_rainbow_comet(controllers, CYCLONE_LOOP, frames_per_step=fps,
                                                             duration_ms=dur), "full spectrum",
        "rainbow cyclone")

    # 10. RACE -- two comets launching from the trackball to opposite edges.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        fps, dur = WAVE_SPEED[speed]
        (sa, ha, ca), (sb, hb, cb) = pal.take_n(2)
        add("race", f"{ha}_{hb}", speed, build_race_from_center(controllers, ca, cb, frames_per_step=fps,
                                                                duration_ms=dur),
            f"{sa} {ha} versus {sb} {hb}", "two colours racing out from center")
    add("race", "rainbow", "fast", build_rainbow_race(controllers), "full spectrum",
        "rainbow race out from center")

    # 11. HEARTBEAT -- whole panel lub-dub then rest.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        ud, dur, rest = HEART_SPEED[speed]
        (sh, h, c) = pal.take()
        add("heartbeat", h, speed, build_heartbeat(controllers, c, up=ud, down=ud, rest_frames=rest,
                                                    duration_ms=dur), f"{sh} {h}", "double-thump heartbeat")
    ud, dur, rest = HEART_SPEED["medium"]
    add("heartbeat", "rainbow", "medium", build_rainbow_heartbeat(controllers, up=ud, down=ud, rest_frames=rest,
                                                                  duration_ms=dur), "full spectrum",
        "rainbow heartbeat")

    # 12. STROBE -- rapid whole-panel flashing.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        on, offf, dur = STROBE_SPEED[speed]
        (sh, h, c) = pal.take()
        add("strobe", h, speed, build_strobe(controllers, c, on_frames=on, off_frames=offf, duration_ms=dur,
                                             cycles=30), f"{sh} {h}", "whole-panel strobe")
    on, offf, dur = STROBE_SPEED["fast"]
    add("strobe", "rainbow", "fast", build_strobe(controllers, None, on_frames=on, off_frames=offf,
                                                  duration_ms=dur, cycles=30, rainbow=True),
        "full spectrum", "rainbow strobe")

    # 13. MARQUEE -- theater chase, every 3rd control lit, gaps travelling.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        fps, dur = WAVE_SPEED[speed]
        (sh, h, c) = pal.take()
        add("marquee", h, speed, build_marquee(controllers, LEFT_RIGHT_ORDER, c, spacing=3, frames_per_step=fps,
                                               duration_ms=dur), f"{sh} {h}", "theater marquee chase")
    fps, dur = WAVE_SPEED["medium"]
    add("marquee", "rainbow", "medium", build_marquee(controllers, LEFT_RIGHT_ORDER, None, spacing=3,
                                                      frames_per_step=fps, duration_ms=dur, rainbow=True),
        "full spectrum", "rainbow marquee chase")

    # 14. BOUNCE -- a VU-meter bar filling up and receding, radiating outward.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        fps, dur = BAR_SPEED[speed]
        (sh, h, c) = pal.take()
        add("bounce", h, speed, build_bounce(controllers, RADIAL_RINGS, c, frames_per_step=fps, duration_ms=dur),
            f"{sh} {h}", "VU-meter bounce")
    fps, dur = BAR_SPEED["fast"]
    add("bounce", "rainbow", "fast", build_bounce(controllers, RADIAL_RINGS, None, frames_per_step=fps,
                                                  duration_ms=dur, rainbow=True), "full spectrum",
        "rainbow VU-meter bounce")

    # 15. ROWBLINK -- top button row vs the rest, swapping in lockstep.
    row_other = ROW_ABOVE + ROW_BOTTOM
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        hold = CHECKER_SPEED[speed]
        (sa, ha, ca), (sb, hb, cb) = pal.take_n(2)
        add("rowblink", f"{ha}_{hb}", speed, build_alternate_wrapper(controllers, ROW_TOP, row_other, ca, cb, hold),
            f"{sa} {ha} and {sb} {hb}", "top row vs rest blink")
    add("rowblink", "rainbow", "medium", build_rainbow_checker(controllers, ROW_TOP, row_other,
                                                               hold_ms=CHECKER_SPEED["medium"]),
        "full spectrum", "rainbow row blink")

    # 16. RIPPLE -- expanding fading rings out of random buttons (raindrops).
    RIPPLE_SPEED = {"slow": (20, 45), "medium": (16, 40), "fast": (11, 30)}  # ring_frames, dur
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        rf, dur = RIPPLE_SPEED[speed]
        (sh, h, c) = pal.take()
        add("ripple", h, speed, build_ripple(controllers, c, ring_frames=rf, duration_ms=dur, seed=i),
            f"{sh} {h}", "raindrop ripples")
    rf, dur = RIPPLE_SPEED["medium"]
    add("ripple", "rainbow", "medium", build_ripple(controllers, None, ring_frames=rf, duration_ms=dur,
                                                    seed=9, rainbow=True), "full spectrum", "rainbow ripples")

    # 17. SPIRAL -- a radar wedge sweeping around the trackball.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        fpr, dur = {"slow": (72, 45), "medium": (48, 40), "fast": (30, 30)}[speed]
        (sh, h, c) = pal.take()
        add("spiral", h, speed, build_spiral(controllers, c, frames_per_rev=fpr, duration_ms=dur),
            f"{sh} {h}", "radar spiral sweep")
    add("spiral", "rainbow", "medium", build_spiral(controllers, None, frames_per_rev=48, duration_ms=40,
                                                    rainbow=True), "full spectrum", "rainbow pinwheel")

    # 18. COMET -- an eased head that glides across and back (slows at the ends).
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        fpl, dur = {"slow": (140, 45), "medium": (90, 40), "fast": (56, 30)}[speed]
        (sh, h, c) = pal.take()
        add("comet", h, speed, build_comet(controllers, LEFT_RIGHT_ORDER, c, frames_per_leg=fpl, duration_ms=dur),
            f"{sh} {h}", "gravity comet")
    add("comet", "rainbow", "medium", build_comet(controllers, LEFT_RIGHT_ORDER, None, frames_per_leg=90,
                                                  duration_ms=40, rainbow=True), "full spectrum", "rainbow comet")

    # 19. LAVALAMP -- a slow plasma field of overlapping sine waves.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        tf, dur = {"slow": (240, 50), "medium": (180, 45), "fast": (120, 35)}[speed]
        (sh, h, c) = pal.take()
        hue = _rgb_to_hue(c)
        add("lavalamp", h, speed, build_plasma(controllers, hue=hue, total_frames=tf, duration_ms=dur),
            f"{sh} {h}", "lava-lamp plasma")
    add("lavalamp", "rainbow", "slow", build_plasma(controllers, total_frames=240, duration_ms=50, rainbow=True),
        "full spectrum", "rainbow plasma")

    # 20. TWINKLE -- a calm dark starfield with soft random fades.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        fade, dur = {"slow": (13, 55), "medium": (9, 45), "fast": (6, 35)}[speed]
        (sh, h, c) = pal.take()
        add("twinkle", h, speed, build_twinkle(controllers, c, fade=fade, duration_ms=dur, seed=i),
            f"{sh} {h}", "twinkling stars")
    add("twinkle", "rainbow", "medium", build_twinkle(controllers, None, fade=9, duration_ms=45, seed=5,
                                                      rainbow=True), "full spectrum", "rainbow twinkle")

    # 21. CANDLE -- whole panel flickering like a flame (a coloured flame).
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        dur = {"slow": 55, "medium": 45, "fast": 32}[speed]
        (sh, h, c) = pal.take()
        add("candle", h, speed, build_candle(controllers, c, duration_ms=dur, seed=i), f"{sh} {h}",
            "flame flicker")
    add("candle", "rainbow", "medium", build_candle(controllers, None, duration_ms=45, seed=3, rainbow=True),
        "full spectrum", "rainbow flame flicker")

    # 22. GRADIENT -- a two-colour gradient across the panel, breathing + sliding.
    for i in range(4):
        speed = VARIANT_SPEEDS[i]
        tf, dur = {"slow": (240, 50), "medium": (192, 45), "fast": (140, 35)}[speed]
        (sa, ha, ca), (sb, hb, cb) = pal.take_n(2)
        add("gradient", f"{ha}_{hb}", speed, build_gradient_breathe(controllers, ca, cb, total_frames=tf,
                                                                    duration_ms=dur),
            f"{sa} {ha} into {sb} {hb}", "breathing gradient")
    add("gradient", "rainbow", "slow", build_gradient_breathe(controllers, total_frames=240, duration_ms=50,
                                                             rainbow=True), "full spectrum",
        "breathing rainbow gradient")

    # 23. COLOUR CYCLES -- one whole-panel breathe cycle and one radial-pulse
    # cycle, each stepping through several globally-unique solid colours and
    # looping. (Phill: "a cycle of solid colour changes that repeat".)
    cyc_breathe = [c for (_s, _h, c) in pal.take_n(6)]
    add("breathe", "cycle", "slow", build_breathe_cycle(controllers, cyc_breathe, steps=BREATHE_SPEED["slow"][0],
                                                        duration_ms=BREATHE_SPEED["slow"][1]),
        "6 unique colours in sequence", "solid colours breathing one after another")
    cyc_pulse = [c for (_s, _h, c) in pal.take_n(6)]
    add("pulse", "cycle", "medium", build_pulse_cycle(controllers, cyc_pulse, frames_per_step=6, duration_ms=40),
        "6 unique colours in sequence", "radial pulse repeating in each colour")

    # 24. BREATHE -- whole panel fading one solid colour in and out. One file per
    # named colour so it doubles as a pickable colour library. Slow by default
    # (Phill: "red slowly fading in and out"); build_color_cycle from off ->
    # colour -> off gives the smooth in/out breath. Standard, extra-vivid, and
    # pastel sets, plus one rainbow breath.
    off = (0, 0, 0)
    spl, dur = BREATHE_SPEED["slow"]
    for cname, color in BREATHE_COLORS + BREATHE_VIVID + BREATHE_PASTEL:
        anim = build_color_cycle(controllers, [off, color], steps_per_leg=spl, duration_ms=dur)
        add("breathe", cname, "slow", anim, cname.replace("_", " "), "solid colour fading in and out")
    add("breathe", "rainbow", "slow", build_rainbow_breathe(controllers, duration_ms=BREATHE_SPEED["slow"][1]),
        "full spectrum", "whole panel breathing while cycling hue")

    # --- validate + write ---
    written = []
    for family, filename, animation, desc in batch:
        xml_text = animation.render()
        ET.fromstring(xml_text)  # raises if malformed
        # newline="" so Python's text-mode translation doesn't double the \r on
        # Windows. open(newline=) works on all versions; write_text(newline=) is
        # 3.10+ only (this project supports 3.8).
        with (out_dir / filename).open("w", encoding="utf-8", newline="") as _fh:
            _fh.write(xml_text)
        written.append((filename, len(animation.frames), desc))

    # --- README.md / index (a short guide, not a per-file manifest) ---
    # One line per family with a live file count -- readers pick by the
    # self-describing file names, so there's no need to list all ~170 files.
    family_blurbs = [
        ("fade", "whole panel cross-fades between two colours"),
        ("sweep", "a comet sweeps across the panel (both directions, chase, cylon)"),
        ("rain", "colour drops fall top-to-bottom, out of sync"),
        ("confetti", "single buttons twinkle at random (rain, spread out)"),
        ("scroll", "a hue gradient scrolls across the panel"),
        ("fill", "a bar fills up from the centre, holds, flashes, refills"),
        ("drain", "a full panel empties one step at a time (countdown/fuse)"),
        ("checker", "interleaved halves swap colours in lockstep"),
        ("radial", "rings pulse outward from / inward to the trackball"),
        ("cyclone", "a front spins around the top-then-bottom loop"),
        ("race", "two comets race outward from the trackball to each edge"),
        ("heartbeat", "whole panel double-thumps then rests"),
        ("strobe", "rapid whole-panel flashing"),
        ("marquee", "theatre chase: every 3rd button lit, gaps travelling"),
        ("bounce", "a VU-meter bar fills and recedes"),
        ("rowblink", "top button row blinks against the rest"),
        ("ripple", "expanding fading rings out of random buttons (raindrops)"),
        ("spiral", "a radar wedge sweeps around the trackball hub"),
        ("comet", "an eased head glides across and back, slowing at the ends"),
        ("lavalamp", "a slow plasma field of overlapping waves"),
        ("twinkle", "a calm dark starfield with soft random fades"),
        ("candle", "the whole panel flickers like a flame"),
        ("gradient", "a two-colour gradient breathes and slides"),
        ("breathe", "one solid colour fades in and out (a pick-by-name colour library)"),
        ("pulse", "a radial pulse replays through several colours and loops"),
    ]
    counts = {}
    for filename, _frames, _desc in written:
        fam = filename.split("_", 1)[0]
        counts[fam] = counts.get(fam, 0) + 1

    md = [
        "# SpinDoctor LEDBlinky pattern library",
        "",
        f"{len(written)} raw (**unsigned**) `.lwax` LED animations for this cabinet's "
        "two PAC-LED64 boards, generated by `scripts/generate_lwax_patterns.py`.",
        "",
        "## What's in here",
        "",
        "Effect families, each with four unique-colour variants plus one moving/fading "
        "**rainbow**, spread over slow / medium / fast timing:",
        "",
    ]
    for fam, blurb in family_blurbs:
        if fam in counts:
            md.append(f"- **{fam}** ({counts[fam]}) — {blurb}")
    md += [
        "",
        "Plus a **`breathe_*` colour library** (standard, `vivid_*`, `pastel_*`, and "
        "`breathe_rainbow`) and two looping colour-cycle files (`breathe_cycle`, "
        "`pulse_cycle`).",
        "",
        "## File names",
        "",
        "`family_colour_speed.lwax` — e.g. `fade_red_lime_slow.lwax`, "
        "`breathe_pastel_blue_slow.lwax`, `radial_rainbow_out_fast.lwax`. Speed is this "
        "batch's own slow/medium/fast tier (frame duration × frames-per-step), not a "
        "LedBlinky setting.",
        "",
        "## How to use one",
        "",
        "The files are unsigned; LedBlinky Config validates a signature it only writes "
        "itself, so sign each file you want once:",
        "",
        "1. Copy the `.lwax` to the cabinet.",
        "2. Open it in `LEDBlinkyAnimationEditor.exe` (in `<ledblinky_dir>\\Plugins\\LEDBlinky\\`).",
        "3. **Animation → Save As**, same name, no edits — this signs it.",
        "4. Copy into `<ledblinky_dir>\\lwa\\` and assign it:",
        "",
        "```",
        "spindoctor ledblinky patch-settings --fe-lwa \"<name>.lwax\" --apply   :: front-end active",
        "spindoctor ledblinky patch-settings --ss-lwa \"<name>.lwax\" --apply   :: screen saver",
        "```",
        "",
        "(Runtime playback via `Settings.ini` does not check the signature; the Save-As "
        "round-trip is only needed to manage the file inside LedBlinky Config.)",
        "",
        "## Troubleshooting",
        "",
        "- **\"Animation File has a missing or invalid signature\" in LedBlinky Config** — "
        "expected for a freshly generated file; do the Save-As step above.",
        "- **Plays, but some buttons stay a fixed colour (often white) while browsing** — "
        "that's `Settings.ini` `[FEOptions] LightFEControls=1` overriding the front-end's "
        "active buttons. Set `LightFEControls=0` for a fully synced panel.",
        "",
        "Regenerate this whole folder any time with `python scripts/generate_lwax_patterns.py`.",
    ]
    (out_dir / "README.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    return written, pal.used


# build_alternate lives in the library; wrap so the call site above reads the
# same as the local rainbow builders.
def build_alternate_wrapper(controllers, group_a, group_b, color_a, color_b, hold_ms):
    return build_alternate(controllers, group_a, group_b, color_a, color_b, hold_ms=hold_ms, cycles=8)


def default_output_dir() -> Path:
    """Where the standalone script and the CLI's ``lwax batch`` write by default."""
    return Path.home() / "Downloads" / "spindoctor-lwax-patterns"


def reference_input_map() -> Path:
    """The committed reference map, used when no fresh export is in ~/Downloads."""
    return Path(__file__).resolve().parent.parent / "docs" / "reference" / "LEDBlinkyInputMap.xml"


def resolve_input_map(explicit: "Path | None" = None) -> "Path | None":
    """Pick the input map to use: an explicit path, else a fresh export in
    ~/Downloads, else the committed reference copy. Returns None if none exist."""
    if explicit is not None:
        return explicit if Path(explicit).exists() else None
    downloads_map = Path.home() / "Downloads" / "LEDBlinkyInputMap.xml"
    if downloads_map.exists():
        return downloads_map
    ref = reference_input_map()
    return ref if ref.exists() else None


def main() -> int:
    """Standalone entry point (used by ``scripts/generate_lwax_patterns.py``):
    resolve the input map + default output dir, then generate the batch."""
    input_map = resolve_input_map()
    if input_map is None:
        print("ERROR: no LEDBlinkyInputMap.xml found in ~/Downloads or the repo "
              "reference copy.", file=sys.stderr)
        return 1
    print(f"Using input map: {input_map}")
    controllers = parse_input_map(input_map)
    out_dir = default_output_dir()
    written, palette_used = generate_batch(controllers, out_dir)
    print(f"Wrote {len(written)} .lwax files + README.md to {out_dir}")
    print(f"Unique palette colours consumed: {palette_used} / {len(MASTER_PALETTE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
