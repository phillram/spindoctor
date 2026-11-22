"""AHK keymapper hotkeys that RocketLauncher's menu navigation keys replace.

RocketLauncher turns its menu navigation keys (``[Navigation]`` in
``Settings\\RocketLauncher.ini``) into hotkeys with AutoHotkey's ``Hotkey``
command, switching them on for a menu and off afterwards.  With the
**Internal** AHK keymapper a profile is appended to the same script, where
that command takes over an existing hotkey of the same name: a plain
``w::`` or ``~w::`` in the profile then never fires.  ``*w::`` (any
modifiers) is a different hotkey, and so are remaps such as ``w::c``, which
AutoHotkey builds as wildcard hotkeys.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ._ahk import iter_ahk_code_lines
from .ledblinky_profiles import _AHK_CONTEXT_RE, _AHK_MOUSE_KEYS, RocketLauncherIndex, _ini_value
from .rocketlauncher import _read_rl_ini, _read_windows_text

# RocketLauncher 1.2's own values where the setting is missing.
_DEFAULT_NAVIGATION = {
    "Navigation_Up_Key": "Up", "Navigation_Down_Key": "Down",
    "Navigation_Left_Key": "Left", "Navigation_Right_Key": "Right",
    "Navigation_Select_Key": "Enter",
    "Navigation_P2_Up_Key": "Numpad8", "Navigation_P2_Down_Key": "Numpad2",
    "Navigation_P2_Left_Key": "Numpad4", "Navigation_P2_Right_Key": "Numpad6",
    "Navigation_P2_Select_Key": "NumpadEnter",
}
_ALIASES = {"return": "enter", "esc": "escape"}
# "Hold 2000:", "D600:", "S:" and "T:" options RocketLauncher puts before a key.
_OPTION_RE = re.compile(r"^(?:[SDT]\d*|H\d*)\s*:\s*", re.I)
_HOTKEY_RE = re.compile(r"([~*$!^+#<>]*)([^\s:&]+)::(.*)")
# Every key name AutoHotkey v1 accepts as a remap's target, any character included.
_KEY_NAME_RE = re.compile(
    r"[^\s]|f\d{1,2}|numpad\w+|(?:l|r)?(?:shift|ctrl|control|alt|win)|appskey|space|tab|enter|esc|escape|"
    r"backspace|bs|delete|del|insert|ins|home|end|pgup|pgdn|up|down|left|right|capslock|scrolllock|numlock|"
    r"printscreen|pause|ctrlbreak|help|sleep|(?:browser|volume|media|launch)_\w+|sc[0-9a-f]{1,3}|vk[0-9a-f]{1,2}", re.I)
_REMAP_PREFIX_RE = re.compile(r"^[~*$!^+#<>]+")
# Profile names RocketLauncher loads for the front end and for itself, not for games.
_NOT_FOR_GAMES = {"hyperspin", "rocketlauncher"}


@dataclass(frozen=True)
class PlainHotkey:
    """A hotkey with no ``*``: ``w::``, ``~w::`` or ``$w::``."""

    line: int
    text: str
    key: str


@dataclass(frozen=True)
class ReplacedHotkey:
    """A plain hotkey on a key that is also one of RocketLauncher's navigation keys."""

    hotkey: PlainHotkey
    setting: str
    value: str


def _normalise(key: str) -> str:
    name = key.strip().lstrip("~*$").lower()
    return _ALIASES.get(name, name)


def navigation_keys(settings: Path) -> dict[str, tuple[str, str]]:
    """``key -> (setting, its value)`` for each single keyboard navigation key.

    Several keys are separated by ``|``; a combination (``A & B``) or a
    joystick button isn't one keyboard key and is left out.
    """
    section = _read_rl_ini(settings / "RocketLauncher.ini").get("navigation", {})
    out: dict[str, tuple[str, str]] = {}
    for setting, default in _DEFAULT_NAVIGATION.items():
        value = section.get(setting.lower()) or default
        for part in value.split("|"):
            part = _OPTION_RE.sub("", part.strip())
            key = _normalise(part)
            if key and "&" not in key and "joy" not in key:
                out.setdefault(key, (setting, value))
    return out


def plain_hotkeys(text: str) -> Iterator[PlainHotkey]:
    """Hotkeys in an AHK profile that start with neither ``*`` nor a modifier.

    Remaps (``r::1``) and hotkeys inside an ``#If`` context are left out:
    a remap is a wildcard hotkey, and a context variant is a hotkey of its own.
    """
    conditional = False
    for number, code in iter_ahk_code_lines(text):
        stripped = code.strip()
        context = _AHK_CONTEXT_RE.fullmatch(stripped)
        if context:
            conditional = bool(context.group(1))
            continue
        match = _HOTKEY_RE.fullmatch(stripped)
        if conditional or not match or set(match.group(1)) - {"~", "$"}:
            continue
        if _is_remap(match.group(3).strip()):
            continue
        yield PlainHotkey(line=number, text=stripped, key=_normalise(match.group(2)))


def _is_remap(target: str) -> bool:
    """Whether what follows `::` is a key to send (`r::1`, `w::^c`), not a hotkey body.

    `r::return` does nothing on purpose: it's a body, not the Return key.
    """
    name = _REMAP_PREFIX_RE.sub("", target) if len(target) > 1 else target
    return bool(_KEY_NAME_RE.fullmatch(name)) or name.lower() in _AHK_MOUSE_KEYS


def replaced_hotkeys(text: str, navigation: dict[str, tuple[str, str]]) -> list[ReplacedHotkey]:
    """Plain hotkeys in *text* that RocketLauncher's navigation keys take over."""
    return [ReplacedHotkey(h, *navigation[h.key]) for h in plain_hotkeys(text) if h.key in navigation]


def internal_ahk_method(index: RocketLauncherIndex, system: str) -> bool:
    """Whether *system* uses RocketLauncher's Internal AHK keymapper.

    As ``ahk_keymapper_on`` reads it, but for ``Internal`` only: an External
    profile is a script of its own, which the ``Hotkey`` command can't reach.
    """
    key = ("Keymapper", "Keymapper_AHK_Method")
    method = _ini_value(index.settings / system / "RocketLauncher.ini", *key)
    if method is None or method.lower() == "use_global":
        method = _ini_value(index.settings / "Global RocketLauncher.ini", *key)
    return (method or "").lower() == "internal"


def game_profiles(ahk_dir: Path) -> Iterator[tuple[str, Path]]:
    """``(system, profile)`` for each AHK profile RocketLauncher can load for a game.

    ``<system>.ahk`` and ``_Default.ahk`` at the top, then
    ``<system>\\<game or emulator>.ahk``.
    """
    if not ahk_dir.is_dir():
        return
    for entry in sorted(ahk_dir.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_dir():
            for path in sorted(entry.iterdir(), key=lambda p: p.name.lower()):
                if path.is_file() and path.suffix.lower() == ".ahk":
                    yield entry.name, path
        elif entry.suffix.lower() == ".ahk" and entry.stem.lower() not in _NOT_FOR_GAMES:
            yield entry.stem, entry


def scan_profiles(config) -> tuple[list[tuple[str, Path, list[ReplacedHotkey]]], int]:
    """Profiles with replaced hotkeys, and how many Internal-keymapper profiles were read."""
    index = RocketLauncherIndex(config)
    navigation = navigation_keys(index.settings)
    internal: dict[str, bool] = {}
    found = []
    checked = 0
    for system, path in game_profiles(index.ahk_dir):
        if system not in internal:
            internal[system] = internal_ahk_method(index, system)
        if not internal[system]:
            continue
        checked += 1
        hits = replaced_hotkeys(_read_windows_text(path), navigation)
        if hits:
            found.append((system, path, hits))
    return found, checked
