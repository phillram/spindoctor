"""Score how much an LEDBlinky ``.lwax`` animation flashes.

Replays a file frame by frame against the input map (the same carry-forward
rule LEDBlinky uses: a controller's ``Intensity`` holds until redeclared) and
measures, per loop:

- ``panel_flash_hz``: whole-panel brightness flashes per second. A flash is an
  up-and-down swing of at least 25% of full brightness in the panel average.
- ``panel_worst_1s``: the same, in the busiest 1-second window.
- ``sync_blink_hz``: times per second that half or more of the buttons snap
  together (a hard cut: some channel jumps by 16 or more, a third of full, in
  one frame).
- ``snaps_per_led_hz``: hard cuts per button per second, how busy a chase is.
- ``max_led_flicker_hz`` / ``mean_led_flicker_hz``: the fastest and the average
  single-button on/off rate (swings of at least 40%).

The loop wraps, so a reset from the last frame back to the first counts too.
:attr:`FlashScore.tier` sorts the result:

=============  ==============================================================
``strobe``     whole panel flashes 2.5 or more times a second
``blink``      half the panel or more hard-cuts together 4+ times a second
``borderline`` lockstep cuts 1.5+ times a second, or 2+ panel flashes in 1 s
``busy``       2.5+ hard cuts per button per second, no panel-wide flashing
``smooth``     everything else
=============  ==============================================================

A port of ``Analyze-LwaxFlash.ps1``, the scorer the example cabinet's
animation pool was sorted with; values are rounded the way .NET's
``Math.Round`` rounds them so the tiers agree.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, Union

from .lwax import LwaxAnimation, LwaxController

TIER_TITLES: Dict[str, str] = {
    "strobe": "Strobe",
    "blink": "Fast blink",
    "borderline": "Borderline",
    "busy": "Fast motion",
    "smooth": "Smooth",
}

PANEL_FLASH_THRESHOLD = 0.25   # panel-average swing that counts as a flash
LED_FLICKER_THRESHOLD = 0.40   # single-button swing that counts as on/off
HARD_CUT = 16                  # channel jump in one frame that counts as a snap


@dataclass(frozen=True)
class FlashScore:
    frames: int
    loop_sec: float
    min_frame_ms: int
    panel_flash_hz: float
    panel_worst_1s: float
    sync_blink_hz: float
    snaps_per_led_hz: float
    max_led_flicker_hz: float
    mean_led_flicker_hz: float

    @property
    def tier(self) -> str:
        if self.panel_flash_hz >= 2.5:
            return "strobe"
        if self.sync_blink_hz >= 4:
            return "blink"
        if self.sync_blink_hz >= 1.5 or self.panel_worst_1s >= 2:
            return "borderline"
        if self.snaps_per_led_hz >= 2.5:
            return "busy"
        return "smooth"

    @property
    def tier_title(self) -> str:
        return TIER_TITLES[self.tier]


def _net_round(value: float, digits: int) -> float:
    """``Math.Round(value, digits)`` as .NET does it: scale, round half to even, unscale."""
    power = 10.0 ** digits
    return round(value * power) / power


def _transitions(series: Sequence[float], t_start: Sequence[float], threshold: float) -> List[float]:
    """Start times of opposing swings of at least ``threshold``, with hysteresis.

    The series is a loop: it is walked twice and only the second pass is
    recorded, so the result is the steady state, wrap-around included.
    """
    n = len(series)
    times: List[float] = []
    hi = lo = series[0]
    direction = 0
    for k in range(2 * n):
        v = series[k % n]
        record = False
        if direction == 0:
            if v >= lo + threshold:
                direction, hi, record = 1, v, True
            elif v <= hi - threshold:
                direction, lo, record = -1, v, True
            lo = min(lo, v)
            hi = max(hi, v)
        elif direction == 1:
            if v > hi:
                hi = v
            elif v <= hi - threshold:
                direction, lo, record = -1, v, True
        else:
            if v < lo:
                lo = v
            elif v >= lo + threshold:
                direction, hi, record = 1, v, True
        if record and k >= n:
            times.append(t_start[k % n])
    return times


def _worst_window(times: Sequence[float], loop_ms: float, window_ms: float) -> int:
    """Most swings inside any ``window_ms`` stretch of the looping animation."""
    if not times:
        return 0
    copies = int(math.ceil(window_ms / loop_ms)) + 2
    stamps = sorted(t + c * loop_ms for c in range(copies) for t in times)
    best = j = 0
    for i, start in enumerate(stamps):
        if start > (copies - 1) * loop_ms:
            break
        while j < len(stamps) and stamps[j] < start + window_ms:
            j += 1
        best = max(best, j - i)
    return best


def decode_lwax(xml_text: str, controllers: Sequence[LwaxController]) -> "Tuple[List[int], List[List[Tuple[int, int, int]]]]":
    """Frame durations and the colour every wired control shows in each frame.

    Controls are in label order (sorted). A single-colour port lights all three
    channels. Works on raw and editor-signed files (both carry ``Id=``).
    """
    labels = sorted({p.label for c in controllers for p in c.ports if p.label})
    index = {label: i for i, label in enumerate(labels)}
    current = {c.id: [0] * len(c.ports) for c in controllers}
    durations: List[int] = []
    colors: List[List[Tuple[int, int, int]]] = []
    root = ET.fromstring(xml_text)
    for frame in root.findall("Frame"):
        durations.append(int(frame.get("Duration", "0")))
        for el in frame.findall("Intensity"):
            values = current.get(el.get("Id", ""))
            if values is None:
                continue
            for i, v in enumerate(el.get("Value", "").split(",")[: len(values)]):
                values[i] = int(v)
        rgb = [[0, 0, 0] for _ in labels]
        for controller in controllers:
            values = current[controller.id]
            for i, port in enumerate(controller.ports):
                if not port.label:
                    continue
                cell = rgb[index[port.label]]
                if port.channel == "R":
                    cell[0] = values[i]
                elif port.channel == "G":
                    cell[1] = values[i]
                elif port.channel == "B":
                    cell[2] = values[i]
                else:
                    cell[0] = cell[1] = cell[2] = values[i]
        colors.append([(c[0], c[1], c[2]) for c in rgb])
    if not durations:
        raise ValueError("No <Frame> elements found.")
    if not labels:
        raise ValueError("The input map has no wired controls.")
    return durations, colors


def score_frames(durations: Sequence[int], colors: Sequence[Sequence[Tuple[int, int, int]]]) -> FlashScore:
    """Score decoded frames (see :func:`decode_lwax`)."""
    n = len(durations)
    count = len(colors[0]) if colors else 0
    if n == 0 or count == 0:
        raise ValueError("Nothing to score: no frames or no wired controls.")
    loop_ms = float(sum(durations))
    if loop_ms <= 0:
        raise ValueError("Frames have no duration.")
    t_start: List[float] = []
    acc = 0.0
    for d in durations:
        t_start.append(acc)
        acc += d

    bright = [[max(colors[i][x]) / 48.0 for i in range(n)] for x in range(count)]
    panel = []
    for i in range(n):
        total = 0.0
        for x in range(count):
            total += bright[x][i]
        panel.append(total / count)

    panel_swings = _transitions(panel, t_start, PANEL_FLASH_THRESHOLD)
    loop_sec = loop_ms / 1000.0

    snaps = sync = 0
    if n > 1:
        for i in range(n):
            j = (i + 1) % n
            cut = 0
            for x in range(count):
                a, b = colors[i][x], colors[j][x]
                if max(abs(b[0] - a[0]), abs(b[1] - a[1]), abs(b[2] - a[2])) >= HARD_CUT:
                    cut += 1
            snaps += cut
            if cut * 2 >= count:
                sync += 1

    max_hz = sum_hz = 0.0
    for x in range(count):
        hz = len(_transitions(bright[x], t_start, LED_FLICKER_THRESHOLD)) / 2.0 / loop_sec
        max_hz = max(max_hz, hz)
        sum_hz += hz

    return FlashScore(
        frames=n,
        loop_sec=_net_round(loop_sec, 2),
        min_frame_ms=min(durations),
        panel_flash_hz=_net_round(len(panel_swings) / 2.0 / loop_sec, 2),
        panel_worst_1s=_net_round(_worst_window(panel_swings, loop_ms, 1000) / 2.0, 1),
        sync_blink_hz=_net_round(sync / loop_sec, 2),
        snaps_per_led_hz=_net_round(snaps / count / loop_sec, 2),
        max_led_flicker_hz=_net_round(max_hz, 2),
        mean_led_flicker_hz=_net_round(sum_hz / count, 2),
    )


def score_xml(xml_text: str, controllers: Sequence[LwaxController]) -> FlashScore:
    """Score ``.lwax`` XML text."""
    return score_frames(*decode_lwax(xml_text, controllers))


def score_lwax(path: Union[str, Path], controllers: Sequence[LwaxController]) -> FlashScore:
    """Score a ``.lwax`` file. Raises ``ValueError`` if it isn't a readable animation."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise ValueError(f"{path} is not UTF-8 text: {e}") from e
    try:
        return score_xml(text, controllers)
    except ET.ParseError as e:
        raise ValueError(f"Could not parse {path}: {e}") from e


def score_animation(animation: LwaxAnimation) -> FlashScore:
    """Score an animation as it renders, so exactly what the cabinet would play."""
    return score_xml(animation.render(), animation.controllers)
