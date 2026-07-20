"""Generic builder for LEDBlinky ``.lwax`` animation files.

See ``docs/cabinet-architecture-reference.md`` → "LEDBlinky Animation Files
(.lwax)" for the full story. Short version:

- ``.lwax`` is XML: one ``<Frame Duration="ms">`` per animation step, each
  holding an ``<Intensity>`` (0-48 brightness) and ``<State>`` (0/1 on-off)
  element per LED controller, addressed by ``Device``/``Id``.
- Values persist frame-to-frame unless redeclared — this module only
  redeclares ``Intensity``/``State`` for a controller when its values changed
  from the previous frame, matching the format LedBlinky's own Animation
  Editor produces.
- **A file built by this module cannot be loaded by LedBlinky as-is.**
  LedBlinky Config validates a per-file signature this module cannot
  reproduce (confirmed to be content-derived but not any standard hash under
  a wide search — most likely a keyed signature baked into the LedBlinky
  binary). The one confirmed way to get a valid file: open the generated
  file in ``LEDBlinkyAnimationEditor.exe`` (ships in
  ``<ledblinky_dir>\\Plugins\\LEDBlinky\\``) and use Animation → Save As
  with no edits — the editor signs whatever it saves.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import Config

RGB_CHANNELS = ("R", "G", "B")


@dataclass(frozen=True)
class LwaxPort:
    """One physical output port on an LED controller."""

    number: int          # 1-indexed, matches LEDBlinkyInputMap.xml's port number=
    label: str            # control label, e.g. "P1B1", "TRACKBALL"; "" if unwired
    channel: str          # "R", "G", "B" for RGB ports; "" for single-color/unwired


@dataclass(frozen=True)
class LwaxController:
    """One LED controller (board) as declared in LEDBlinkyInputMap.xml."""

    hw_type: str          # numeric type code string, e.g. "3" (PACLED64)
    id: str                # controller id, e.g. "1", "2"
    name: str              # e.g. "PACLED64"
    ports: tuple[LwaxPort, ...]   # length = total port count on the board (e.g. 64)


def parse_input_map(path: Path) -> list[LwaxController]:
    """Parse ``LEDBlinkyInputMap.xml`` into a list of :class:`LwaxController`.

    Raises ``ValueError`` if the file is missing or malformed.
    """
    if not path.exists():
        raise ValueError(f"LEDBlinkyInputMap.xml not found at {path}")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise ValueError(f"Could not parse {path}: {e}") from e

    controllers: list[LwaxController] = []
    for ctrl_el in root.findall("ledController"):
        ports = tuple(
            LwaxPort(
                number=int(port_el.get("number", "0")),
                label=port_el.get("label", "") or "",
                channel=port_el.get("type", "") or "",
            )
            for port_el in sorted(
                ctrl_el.findall("port"), key=lambda p: int(p.get("number", "0"))
            )
        )
        controllers.append(
            LwaxController(
                hw_type=ctrl_el.get("type", ""),
                id=ctrl_el.get("id", ""),
                name=ctrl_el.get("name", ""),
                ports=ports,
            )
        )
    return controllers


# label -> list of (controller, ports-for-that-label-in-channel-order)
ControlMap = "dict[str, list[tuple[LwaxController, list[LwaxPort]]]]"


def controls_by_label(controllers: list[LwaxController]) -> ControlMap:
    """Group each controller's ports by label.

    RGB controls yield their 3 ports in R, G, B order; single-color controls
    (blank ``channel``) yield a single-element list. A label appearing on
    more than one controller (unusual, but not disallowed by the format)
    gets an entry per controller.
    """
    result: "dict[str, list[tuple[LwaxController, list[LwaxPort]]]]" = {}
    for controller in controllers:
        by_label: "dict[str, list[LwaxPort]]" = {}
        for port in controller.ports:
            if not port.label:
                continue
            by_label.setdefault(port.label, []).append(port)
        for label, ports in by_label.items():
            # Stable R, G, B order when channel info is present.
            ports_sorted = sorted(
                ports,
                key=lambda p: RGB_CHANNELS.index(p.channel) if p.channel in RGB_CHANNELS else 0,
            )
            result.setdefault(label, []).append((controller, ports_sorted))
    return result


Color = "tuple[int, int, int]"  # (R, G, B), each 0-48


@dataclass
class LwaxFrame:
    duration_ms: int
    colors: "dict[str, Color]" = field(default_factory=dict)


class LwaxAnimation:
    """Builds a sequence of frames addressed by control label, and renders
    the raw (unsigned) ``.lwax`` XML for them.

    Frame 0 implicitly starts every control at ``(0, 0, 0)`` / off. Each
    subsequent call to :meth:`add_frame` only needs to specify the labels
    whose color changed — everything else carries forward, matching how
    LedBlinky's own animations encode holds and fades.
    """

    def __init__(self, controllers: list[LwaxController]):
        self.controllers = controllers
        self._control_map = controls_by_label(controllers)
        self.frames: list[LwaxFrame] = []

    @property
    def labels(self) -> list[str]:
        """All labels (real, wired controls) found in the input map, sorted."""
        return sorted(self._control_map.keys())

    def add_frame(self, duration_ms: int, colors: "Optional[dict[str, Color]]" = None) -> int:
        """Append a frame. ``colors`` maps label -> (r, g, b), 0-48 each, for
        every label whose color should change starting this frame; omitted
        labels keep whatever color they last had (or (0,0,0) if never set).

        Returns the new frame's index (0-based).
        """
        colors = colors or {}
        unknown = set(colors) - set(self._control_map)
        if unknown:
            raise ValueError(f"Unknown control label(s): {sorted(unknown)}")
        for r, g, b in colors.values():
            for v in (r, g, b):
                if not 0 <= v <= 48:
                    raise ValueError(f"Color channel out of range 0-48: {(r, g, b)}")
        self.frames.append(LwaxFrame(duration_ms=duration_ms, colors=dict(colors)))
        return len(self.frames) - 1

    def _resolved_colors(self) -> "list[dict[str, Color]]":
        """Per-frame full color map (every known label), forward-filled."""
        current: "dict[str, Color]" = {label: (0, 0, 0) for label in self._control_map}
        resolved = []
        for frame in self.frames:
            current.update(frame.colors)
            resolved.append(dict(current))
        return resolved

    def render(self) -> str:
        """Render the raw (unsigned) ``.lwax`` XML text.

        Uses ``Device="<name>" Id="<id>"`` attributes with the real board
        IDs read from the input map — confirmed to import cleanly into
        LEDBlinkyAnimationEditor.exe, which rewrites them to its own
        ``LedHwType=`` form on Save As.
        """
        if not self.frames:
            raise ValueError("Animation has no frames; call add_frame() first.")

        resolved = self._resolved_colors()
        lines = ['<?xml version="1.0" encoding="utf-8"?>', "<LEDAnimation>"]

        prev_intensity: "dict[tuple[str, str], list[int]]" = {}
        prev_state: "dict[tuple[str, str], list[int]]" = {}

        for frame_idx, (frame, colors) in enumerate(zip(self.frames, resolved)):
            lines.append(f'  <Frame Number="{frame_idx + 1}" Duration="{frame.duration_ms}">')
            for controller in self.controllers:
                key = (controller.name, controller.id)
                intensity = [0] * len(controller.ports)
                state = [0] * len(controller.ports)
                for i, port in enumerate(controller.ports):
                    if not port.label:
                        continue
                    r, g, b = colors[port.label]
                    channel_value = {"R": r, "G": g, "B": b}.get(port.channel, r)
                    intensity[i] = channel_value
                    # State just marks "this port is wired" — it stays 1 for
                    # every real port for the whole animation regardless of
                    # the port's instantaneous color value. Intensity alone
                    # carries the visible fade; this matches every confirmed
                    # real file (slowfadeupdown.lwax, the signed rgbfade2.lwax).
                    state[i] = 1

                intensity_changed = frame_idx == 0 or intensity != prev_intensity.get(key)
                state_changed = frame_idx == 0 or state != prev_state.get(key)

                if intensity_changed:
                    csv = ",".join(str(v) for v in intensity)
                    lines.append(
                        f'    <Intensity Device="{controller.name}" Id="{controller.id}" Value="{csv}"/>'
                    )
                if state_changed:
                    csv = ",".join(str(v) for v in state)
                    lines.append(
                        f'    <State Device="{controller.name}" Id="{controller.id}" Value="{csv}"/>'
                    )
                prev_intensity[key] = intensity
                prev_state[key] = state
            lines.append("  </Frame>")

        lines.append("</LEDAnimation>")
        return "\r\n".join(lines) + "\r\n"


def build_color_cycle(
    controllers: list[LwaxController],
    colors: "list[Color]",
    steps_per_leg: int = 48,
    duration_ms: int = 40,
    labels: "Optional[list[str]]" = None,
) -> LwaxAnimation:
    """Fade every control (or just ``labels``, if given) through ``colors``
    in order, looping back to the first color at the end.

    ``steps_per_leg`` frames are generated per color-to-color transition,
    one intensity unit of change per frame for the smoothest possible fade.
    Needs at least 2 colors.
    """
    if len(colors) < 2:
        raise ValueError("Need at least 2 colors to cycle between.")
    animation = LwaxAnimation(controllers)
    target_labels = labels if labels is not None else animation.labels
    unknown = set(target_labels) - set(animation.labels)
    if unknown:
        raise ValueError(f"Unknown control label(s): {sorted(unknown)}")

    num_legs = len(colors)
    for leg in range(num_legs):
        start = colors[leg]
        end = colors[(leg + 1) % num_legs]
        for step in range(steps_per_leg):
            t = step / steps_per_leg
            frame_color = tuple(
                round(start[c] + (end[c] - start[c]) * t) for c in range(3)
            )
            animation.add_frame(duration_ms, {label: frame_color for label in target_labels})
    return animation


def resolve_input_map_path(config: Config) -> Path:
    if not config.ledblinky_dir:
        raise ValueError(
            "ledblinky_dir not configured. Run: spindoctor config set ledblinky_dir <path>"
        )
    return Path(config.ledblinky_dir) / "LEDBlinkyInputMap.xml"
