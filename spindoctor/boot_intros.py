"""Console start-up logos on or off, for every emulator that has the setting.

A real console plays its own start-up logo before each game: the Game Boy's
scrolling "Nintendo", the PlayStation and PlayStation 2 logos, the GameCube
cube, the Dreamcast swirl.  The logo is part of the console's boot ROM or
BIOS, so an emulator can only play it when it has that file, and each
emulator keeps the choice in its own settings file under its own name: a
RetroArch core in its core options (``gambatte_gb_bootloader``), DuckStation
as ``[BIOS] PatchFastBoot``, Dolphin as ``[Core] SkipIPL``.

This module finds the emulators RocketLauncher starts (the ``Emu_Path`` of
each ``Emulators.ini`` section, as ``doctor`` reads them), reads that one
setting and changes it, keeping the rest of each file byte for byte.  The
setting names and values come from each emulator's own source code (listed in
``docs/start-up-logos.md``); an emulator without such a setting is listed as
having none, never given a made-up key.

Turning a logo on is refused for an emulator whose boot ROM or BIOS isn't
found: the missing file is named instead, so no emulator is set up to need a
file it can't read.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterable, Optional

from ._text import read_editable_text, write_windows_text
from ._utils import unique_path


class BootIntroError(Exception):
    """A request this module can't carry out (e.g. an unknown emulator name)."""


@dataclass(frozen=True)
class Need:
    """A file the logo needs: any one of *names*, ignoring case.

    For a RetroArch core the file is looked for in RetroArch's system folder
    or one of the ``subdirs`` below it.  A file the emulator finds by its
    contents rather than its name (melonDS DS's firmware) is given by its
    possible ``sizes`` and the ``magic`` bytes at offset ``magic_at``.
    """
    what: str
    names: tuple[str, ...] = ()
    subdirs: tuple[str, ...] = ("",)
    sizes: tuple[int, ...] = ()
    magic: bytes = b""
    magic_at: int = 0


# (folder, settings file, its text) -> (files found, files missing)
NeedsCheck = Callable[[Path, Path, str], "tuple[list[str], list[str]]"]


@dataclass(frozen=True)
class IntroSetting:
    """One emulator's start-up logo setting.

    ``on`` is the value that plays the logo and ``off`` the one that skips
    it; ``default_on`` is what the emulator does while the key is absent.
    ``same_keys`` are switched together with ``key`` (one per console, as
    Gearboy's).  ``also_on`` are ``(key, value, absent_ok)`` settings the logo
    needs as well, written while turning it on (``absent_ok``: the key's
    default already is that value).  ``blocked_by`` are ``(key, value, why)``
    settings under which the logo can't play, so turning it on is refused.

    With ``any_need`` one found file is enough (each covers its own console or
    region, and the emulator skips the logo of one whose file is missing);
    otherwise every file in ``needs`` must be there.
    """
    id: str
    name: str
    consoles: str
    key: str
    on: str
    off: str
    default_on: bool
    same_keys: tuple[str, ...] = ()
    also_on: tuple[tuple[str, str, bool], ...] = ()
    blocked_by: tuple[tuple[str, str, str], ...] = ()
    needs: tuple[Need, ...] = ()
    any_need: bool = False
    note: str = ""
    # RetroArch cores: the core DLL names (no ``.dll``), the core's own name
    # (RetroArch's options folder and file) and its options' key prefix.
    cores: tuple[str, ...] = ()
    library: str = ""
    prefix: str = ""
    # Standalone emulators: Emu_Path exe name prefixes (and a word the exe
    # name must contain), the settings file's section and line style, where
    # the file can be, and how to look for the files the logo needs.
    exes: tuple[str, ...] = ()
    exe_has: str = ""
    section: str = ""
    style: str = "ini"           # "ini", "toml" or "opt" (RetroArch's key = "value")
    separator: str = " = "
    locate: Optional[Callable[[Path], list]] = None
    check: Optional[NeedsCheck] = None

    @property
    def retroarch(self) -> bool:
        return bool(self.cores)

    @property
    def keys(self) -> tuple[str, ...]:
        return (self.key,) + self.same_keys

    @property
    def fmt(self) -> str:
        """The settings file's line style; core options are always RetroArch's."""
        return "opt" if self.cores else self.style

    @property
    def has_needs(self) -> bool:
        return bool(self.needs) or self.check is not None

    def for_exe(self, exe: str) -> bool:
        e = exe.lower()
        return bool(self.exes) and e.startswith(self.exes) and self.exe_has in e


# ── Reading and writing one setting ───────────────────────────────────────────

_SECTION_RE = re.compile(r"^\s*\[\[?\s*([^\[\]]*?)\s*\]\]?\s*(?:[;#].*)?$")
_KEY_RE = re.compile(r"^(\s*)([^=\s;#\[][^=]*?)(\s*=\s*)(.*)$")
_TRUE = ("true", "1", "yes", "on", "enabled")
_FALSE = ("false", "0", "no", "off", "disabled")


def _parse_value(raw: str, style: str) -> tuple[str, str]:
    """Split a line's value from what follows it: ``(value, rest)``.

    RetroArch writes ``key = "value"``; TOML values here are booleans or
    quoted strings, then an optional ``# comment``; INI values run to the end
    of the line.
    """
    if style == "opt":
        m = re.match(r'^"([^"]*)"(.*)$', raw)
        return (m.group(1), m.group(2)) if m else (raw.strip(), "")
    if style == "toml":
        m = re.match(r"""^("[^"]*"|'[^']*'|[^\s#]*)(.*)$""", raw)
        value = m.group(1) if m else raw
        return value.strip("\"'"), (m.group(2) if m else "")
    return raw.strip(), ""


def _format_value(value: str, style: str) -> str:
    return f'"{value}"' if style == "opt" else value


def _key_matches(found: str, key: str, style: str) -> bool:
    # The INI readers here (Qt's, SimpleIni, Flycast's) ignore key case;
    # TOML and RetroArch keys are exact.
    return found.lower() == key.lower() if style == "ini" else found == key


def read_value(text: str, key: str, section: str = "", style: str = "ini") -> Optional[str]:
    """The value of *key* in *section* ("" = before any section), or None."""
    current = ""
    value = None
    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m and style != "opt":
            current = m.group(1)
            continue
        if current.lower() != section.lower():
            continue
        km = _KEY_RE.match(line)
        if km and _key_matches(km.group(2), key, style):
            value = _parse_value(km.group(4), style)[0]
            if style != "ini":
                break           # TOML and RetroArch: the first line counts
    return value


def set_value(text: str, key: str, value: str, section: str = "", style: str = "ini",
              separator: str = " = ", newline: str = "\n") -> str:
    """*text* with *key* in *section* set to *value*; everything else kept.

    Every line of the key in that section is rewritten in place (its indent,
    spacing and comment kept).  A missing key goes after the section's last
    setting, and a missing section at the end of the file.  New lines use the
    file's own line ending.
    """
    lines = text.splitlines(keepends=True)
    ending = next((ln[len(ln.rstrip("\r\n")):] for ln in lines if ln.endswith(("\n", "\r"))), newline)
    new_line = f"{key}{separator}{_format_value(value, style)}{ending}"
    current = ""
    found = False
    last_setting: Optional[int] = None    # the section's last non-blank line
    header: Optional[int] = None
    first_header: Optional[int] = None
    out = []
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        m = _SECTION_RE.match(body)
        if m and style != "opt":
            current = m.group(1)
            if first_header is None:
                first_header = i
            if section and current.lower() == section.lower() and header is None:
                header = i
                last_setting = i
            out.append(line)
            continue
        if current.lower() == section.lower():
            km = _KEY_RE.match(body)
            if km and _key_matches(km.group(2), key, style):
                _old, rest = _parse_value(km.group(4), style)
                out.append(f"{km.group(1)}{km.group(2)}{km.group(3)}"
                           f"{_format_value(value, style)}{rest}{line[len(body):]}")
                found = True
                last_setting = i
                continue
            if body.strip():
                last_setting = i
        out.append(line)
    if found:
        return "".join(out)

    def tail(blank: bool) -> str:
        t = "".join(out)
        if t and not t.endswith(("\n", "\r")):
            t += ending
        return t + (ending if blank and t.strip() else "")

    if section and header is None:
        return f"{tail(True)}[{section}]{ending}{new_line}"
    if last_setting is None:
        if not section and first_header is not None:
            out.insert(first_header, new_line)       # keys before the first section
            return "".join(out)
        return tail(False) + new_line
    if not out[last_setting].endswith(("\n", "\r")):
        out[last_setting] += ending
    out.insert(last_setting + 1, new_line)
    return "".join(out)


def is_on(value: Optional[str], setting: IntroSetting) -> bool:
    """Whether *value* (None = key absent) plays the logo.

    A value that is neither ``on`` nor ``off`` counts by its meaning when both
    are yes/no words ("True" for "true", "1" for "yes"); otherwise the
    emulator ignores it, as RetroArch does, and its default applies.
    """
    if value is None:
        return setting.default_on
    v = value.strip().lower()
    if v == setting.on.lower():
        return True
    if v == setting.off.lower():
        return False
    on, off = setting.on.lower(), setting.off.lower()
    if {on, off} <= set(_TRUE + _FALSE) and v in _TRUE + _FALSE:
        return (v in _TRUE) == (on in _TRUE)
    return setting.default_on


# ── Finding files ────────────────────────────────────────────────────────────

def _ci_child(folder: Path, name: str) -> Optional[Path]:
    """*folder*'s entry called *name*, ignoring case (as Windows does)."""
    direct = folder / name
    if direct.exists():
        return direct
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if entry.name.lower() == name.lower():
                    return Path(entry.path)
    except OSError:
        pass
    return None


def _ci_path(base: Path, *parts: str) -> Optional[Path]:
    found = base
    for part in parts:
        if not part:
            continue
        nxt = _ci_child(found, part)
        if nxt is None:
            return None
        found = nxt
    return found


def _find_need(need: Need, folders: Iterable[Path]) -> Optional[Path]:
    for folder in folders:
        for sub in need.subdirs:
            base = _ci_path(folder, *PureWindowsPath(sub).parts) if sub else folder
            if base is None or not base.is_dir():
                continue
            for name in need.names:
                hit = _ci_child(base, name)
                if hit is not None and hit.is_file():
                    return hit
            if need.sizes:
                hit = _find_by_contents(need, base)
                if hit is not None:
                    return hit
    return None


def _find_by_contents(need: Need, folder: Path) -> Optional[Path]:
    try:
        with os.scandir(folder) as it:
            entries = sorted(it, key=lambda e: e.name.lower())
    except OSError:
        return None
    for entry in entries:
        try:
            if not entry.is_file() or entry.stat().st_size not in need.sizes:
                continue
            with open(entry.path, "rb") as f:
                f.seek(need.magic_at)
                if f.read(len(need.magic)) == need.magic:
                    return Path(entry.path)
        except OSError:
            continue
    return None


def _need_text(need: Need, where: Iterable[Path]) -> str:
    names = " or ".join(need.names) if need.names else "a file"
    places = ", ".join(dict.fromkeys(str(p.joinpath(*PureWindowsPath(sub).parts)) if sub else str(p)
                                     for p in where for sub in need.subdirs))
    return f"{names} ({need.what}) in {places}" if places else f"{names} ({need.what})"


def _check_files(needs: Iterable[Need], folders: list[Path]) -> tuple[list[str], list[str]]:
    found, missing = [], []
    for need in needs:
        hit = _find_need(need, folders)
        if hit is not None:
            found.append(str(hit))
        else:
            missing.append(_need_text(need, folders))
    return found, missing


def _documents() -> Path:
    return Path.home() / "Documents"


def _env_folder(name: str) -> Optional[Path]:
    value = os.environ.get(name, "")
    return Path(value) if value else None


def _config_path(value: str, base: Path) -> Path:
    """A path from an emulator's settings: absolute, or from *base*."""
    pw = PureWindowsPath(value)
    if pw.drive or Path(value).is_absolute():
        return Path(value)
    return base.joinpath(*pw.parts)


# ── RetroArch ────────────────────────────────────────────────────────────────

# RetroArch's built-in folders on Windows for a key a config leaves out
# (":" is the folder retroarch.exe is in).  The value "default" is different:
# RetroArch reads it as empty (see _ra_layout).
_RA_DEFAULTS = {
    "rgui_config_directory": ":\\config",
    "system_directory": ":\\system",
    "libretro_directory": ":\\cores",
}
_RA_LAYOUT_KEYS = ("global_core_options", "core_options_path") + tuple(_RA_DEFAULTS)
_RA_LEGACY_FILE = "retroarch-core-options.cfg"


def _read_ra_cfg(path: Path) -> dict[str, str]:
    """``key = "value"`` lines of a RetroArch config (first line of a key wins)."""
    out: dict[str, str] = {}
    try:
        text = read_editable_text(path)
    except OSError:
        return out
    for line in text.splitlines():
        km = _KEY_RE.match(line)
        if km and not line.lstrip().startswith("#"):
            out.setdefault(km.group(2).strip(), _parse_value(km.group(4), "opt")[0])
    return out


def _ra_folder(value: str, exe_dir: Path) -> Path:
    v = value.strip()
    if v.startswith(":"):
        v = v[1:].lstrip("\\/")
        return exe_dir.joinpath(*PureWindowsPath(v).parts) if v else exe_dir
    # RocketLauncher starts RetroArch in its own folder.
    return _config_path(v, exe_dir)


@dataclass(frozen=True)
class RetroArchLayout:
    """Where one RetroArch config keeps core options, BIOS files and cores."""
    options_dir: Path            # <core name>\<core name>.opt live under it
    system_dir: Optional[Path]   # None: "default", i.e. each game's own folder
    cores_dir: Path
    legacy_file: Path            # retroarch-core-options.cfg (or core_options_path)
    global_mode: bool            # global_core_options = "true": only legacy_file is used


def _ra_layout(cfg: dict[str, str], exe_dir: Path, cfg_dir: Path) -> RetroArchLayout:
    def value(key: str) -> Optional[str]:
        """The key's value; None for "default" or empty, which RetroArch reads as unset."""
        v = cfg.get(key, _RA_DEFAULTS.get(key, "")).strip()
        return None if not v or v.lower() == "default" else v

    options = value("rgui_config_directory")
    # An unset config folder is the folder the loaded config is in.
    options_dir = _ra_folder(options, exe_dir) if options else cfg_dir
    system = value("system_directory")
    cores = value("libretro_directory")
    legacy = value("core_options_path")
    return RetroArchLayout(
        options_dir=options_dir,
        system_dir=_ra_folder(system, exe_dir) if system else None,
        cores_dir=_ra_folder(cores or _RA_DEFAULTS["libretro_directory"], exe_dir),
        legacy_file=_ra_folder(legacy, exe_dir) if legacy else cfg_dir / _RA_LEGACY_FILE,
        global_mode=cfg.get("global_core_options", "false").strip().lower() == "true",
    )


def retroarch_layouts(exe_dir: Path) -> list[RetroArchLayout]:
    """Every folder layout a RetroArch install starts with.

    ``retroarch.cfg`` beside the exe, plus the configs RocketLauncher starts
    it with (``-c config\\<System>.cfg``): the ``.cfg`` files in its config
    folder that set a folder or the core options mode.  A config loaded with
    ``-c`` replaces retroarch.cfg, so each is read on its own against
    RetroArch's defaults.  With no config at all, the defaults.
    """
    # retroarch.cfg, or RetroArch's defaults for a start without -c.
    main = _ci_child(exe_dir, "retroarch.cfg")
    sources = [(_read_ra_cfg(main) if main is not None and main.is_file() else {}, exe_dir)]
    first = _ra_layout(sources[0][0], exe_dir, exe_dir)
    try:
        cfgs = sorted(p for p in first.options_dir.glob("*.cfg") if p.is_file())
    except OSError:
        cfgs = []
    for path in cfgs:
        if path.name.lower() == _RA_LEGACY_FILE:
            continue
        cfg = _read_ra_cfg(path)
        if any(k in cfg for k in _RA_LAYOUT_KEYS):
            sources.append((cfg, path.parent))
    layouts: list[RetroArchLayout] = []
    for cfg, cfg_dir in sources:
        layout = _ra_layout(cfg, exe_dir, cfg_dir)
        if layout not in layouts:
            layouts.append(layout)
    return layouts


def _ra_core_files(setting: IntroSetting, layouts: list[RetroArchLayout]) -> list[Path]:
    """The core options files *setting*'s key lives in, for every layout.

    The core's own ``<core name>.opt`` (created when missing), or the shared
    ``retroarch-core-options.cfg`` with ``global_core_options`` on; plus every
    per-game and per-folder ``.opt`` already in the core's options folder:
    RetroArch reads one of those *instead of* the core's file for that game,
    so each needs the key too.
    """
    files: list[Path] = []
    for layout in layouts:
        folder = _ci_path(layout.options_dir, setting.library) or layout.options_dir / setting.library
        own = (layout.legacy_file if layout.global_mode
               else _ci_child(folder, f"{setting.library}.opt") or folder / f"{setting.library}.opt")
        extra = []
        try:
            extra = sorted((p for p in folder.glob("*.opt") if p.is_file()),
                           key=lambda p: p.name.lower())
        except OSError:
            pass
        for path in [own] + extra:
            if path not in files:
                files.append(path)
    return files


def _ra_seed(setting: IntroSetting, path: Path, layouts: list[RetroArchLayout]) -> str:
    """Starting text for a core's new ``.opt`` file.

    RetroArch fills a core's options file it hasn't written yet from the old
    shared ``retroarch-core-options.cfg``, once.  A new file holding only the
    logo key would skip that, so it starts with the core's lines from there.
    """
    for layout in layouts:
        if path.parent.parent != layout.options_dir or not layout.legacy_file.is_file():
            continue
        try:
            text = read_editable_text(layout.legacy_file)
        except OSError:
            return ""
        lines = [ln for ln in text.splitlines(keepends=True)
                 if setting.prefix and ln.lstrip().startswith(setting.prefix)]
        return "".join(ln if ln.endswith(("\n", "\r")) else ln + "\n" for ln in lines)
    return ""


def _ra_core_dll(layout: RetroArchLayout, core: str) -> Optional[Path]:
    hit = _ci_child(layout.cores_dir, f"{core}.dll")
    return hit if hit is not None and hit.is_file() else None


def _ra_has_core(cores: Iterable[str], layouts: list[RetroArchLayout]) -> bool:
    return any(_ra_core_dll(layout, core) is not None for layout in layouts for core in cores)


# ── Standalone emulators: where their settings and BIOS files are ────────────

def _duckstation_files(folder: Path) -> list[Path]:
    # Portable when portable.txt or settings.ini is beside the exe; otherwise
    # Documents\DuckStation if that folder exists, else %LOCALAPPDATA%.
    if _ci_child(folder, "portable.txt") or _ci_child(folder, "settings.ini"):
        return [_ci_child(folder, "settings.ini") or folder / "settings.ini"]
    docs = _documents() / "DuckStation"
    if docs.is_dir():
        return [docs / "settings.ini"]
    local = _env_folder("LOCALAPPDATA")
    return [local / "DuckStation" / "settings.ini"] if local else []


def _pcsx2_files(folder: Path) -> list[Path]:
    # Portable when portable.ini or portable.txt is beside the exe.
    if _ci_child(folder, "portable.ini") or _ci_child(folder, "portable.txt"):
        return [_ci_path(folder, "inis", "PCSX2.ini") or folder / "inis" / "PCSX2.ini"]
    return [_documents() / "PCSX2" / "inis" / "PCSX2.ini"]


def _dolphin_user(folder: Path) -> list[Path]:
    # portable.txt: the User folder beside the exe.  Otherwise (with no
    # registry override) Documents\Dolphin Emulator if it exists, else
    # %APPDATA%\Dolphin Emulator.
    if _ci_child(folder, "portable.txt"):
        return [_ci_child(folder, "User") or folder / "User"]
    docs = _documents() / "Dolphin Emulator"
    if docs.is_dir():
        return [docs]
    appdata = _env_folder("APPDATA")
    return [appdata / "Dolphin Emulator"] if appdata else []


def _dolphin_files(folder: Path) -> list[Path]:
    return [_ci_path(user, "Config", "Dolphin.ini") or user / "Config" / "Dolphin.ini"
            for user in _dolphin_user(folder)]


def _dolphin_check(folder: Path, settings: Path, _text: str) -> tuple[list[str], list[str]]:
    # Dolphin refuses to start a GameCube disc whose region has no IPL
    # ("the GC IPL could not be found"), so every region needs one.
    user = settings.parent.parent
    found, missing = [], []
    for region in ("USA", "EUR", "JAP"):
        f, m = _check_files([Need(f"GameCube IPL, {region}", ("IPL.bin",))],
                            [user / "GC" / region, folder / "Sys" / "GC" / region])
        found += f
        missing += m
    return found, missing


def _flycast_files(folder: Path) -> list[Path]:
    return [_ci_child(folder, "emu.cfg") or folder / "emu.cfg"]


def _flycast_check(folder: Path, _settings: Path, text: str) -> tuple[list[str], list[str]]:
    # Looked for in Dreamcast.BiosPath, then data\, then the content folders.
    folders = []
    bios = read_value(text, "Dreamcast.BiosPath", "config")
    if bios:
        folders.append(_config_path(bios, folder))
    folders.append(folder / "data")
    for content in (read_value(text, "Dreamcast.ContentPath", "config") or "").split(";"):
        if content.strip():
            folders.append(_config_path(content.strip(), folder))
    return _check_files([Need("Dreamcast BIOS", ("dc_boot.bin", "dc_bios.bin"))], folders)


def _xemu_files(folder: Path) -> list[Path]:
    # Portable when xemu.toml is beside the exe; otherwise SDL's user folder.
    out = [_ci_child(folder, "xemu.toml") or folder / "xemu.toml"]
    appdata = _env_folder("APPDATA")
    if appdata:
        out.append(appdata / "xemu" / "xemu" / "xemu.toml")
    return out


def _melonds_toml(folder: Path) -> list[Path]:
    sub = _ci_child(folder, "portable")
    base = sub if sub is not None and sub.is_dir() else folder
    return [_ci_child(base, "melonDS.toml") or base / "melonDS.toml"]


def _melonds_ini(folder: Path) -> list[Path]:
    return [_ci_child(folder, "melonDS.ini") or folder / "melonDS.ini"]


def _melonds_paths(section: str, style: str) -> NeedsCheck:
    """melonDS boots the DS firmware only with all three of its own files."""
    def check(_folder: Path, settings: Path, text: str) -> tuple[list[str], list[str]]:
        found, missing = [], []
        where = f"[{section}] " if section else ""
        for key, what in (("BIOS9Path", "DS ARM9 BIOS"), ("BIOS7Path", "DS ARM7 BIOS"),
                          ("FirmwarePath", "DS firmware")):
            value = read_value(text, key, section, style)
            path = _config_path(value, settings.parent) if value else None
            if path is not None and path.is_file():
                found.append(str(path))
            elif path is not None:
                missing.append(f"{path} ({what}, {where}{key} in {settings})")
            else:
                missing.append(f"{what} ({where}{key} is empty in {settings})")
        return found, missing
    return check


# ── The settings, from each emulator's source ────────────────────────────────
# Keys, values and defaults were read from each project's source on GitHub in
# November 2026 (files and lines in docs/start-up-logos.md).  Values are case
# sensitive: RetroArch ignores a core option value that isn't one of the
# core's own, and uses the default.

_SYS = "system folder"
_PS1_BIOS = ("scph5500.bin", "scph5501.bin", "scph5502.bin")

SETTINGS: tuple[IntroSetting, ...] = (
    # ── RetroArch cores ──
    IntroSetting(
        "gambatte", "Gambatte", "Game Boy, Game Boy Color",
        "gambatte_gb_bootloader", "enabled", "disabled", default_on=True,
        needs=(Need("Game Boy boot ROM", ("gb_bios.bin",)),
               Need("Game Boy Color boot ROM", ("gbc_bios.bin",))),
        any_need=True, cores=("gambatte_libretro",), library="Gambatte", prefix="gambatte_",
        note="Also decides whether Game Boy games in GBC/GBA mode start as a Game Boy Color "
             "(only with gbc_bios.bin and the boot ROM on)."),
    IntroSetting(
        "mgba", "mGBA", "Game Boy Advance (and Game Boy, Game Boy Color)",
        "mgba_skip_bios", "OFF", "ON", default_on=True,
        also_on=(("mgba_use_bios", "ON", True),),
        needs=(Need("Game Boy Advance BIOS", ("gba_bios.bin",)),
               Need("Game Boy boot ROM", ("gb_bios.bin",)),
               Need("Game Boy Color boot ROM", ("gbc_bios.bin",)),
               Need("Super Game Boy BIOS", ("sgb_bios.bin",))),
        any_need=True, cores=("mgba_libretro",), library="mGBA", prefix="mgba_",
        note="Off keeps the BIOS and skips only its logo (mgba_skip_bios)."),
    IntroSetting(
        "gearboy", "Gearboy", "Game Boy, Game Boy Color",
        "gearboy_bootrom_dmg", "Enabled", "Disabled", default_on=False,
        same_keys=("gearboy_bootrom_gbc",),
        needs=(Need("Game Boy boot ROM", ("dmg_boot.bin",)),
               Need("Game Boy Color boot ROM", ("cgb_boot.bin",))),
        any_need=True, cores=("gearboy_libretro",), library="Gearboy", prefix="gearboy_"),
    IntroSetting(
        "gearsystem", "Gearsystem", "Master System, Game Gear",
        "gearsystem_bios_sms", "Enabled", "Disabled", default_on=False,
        same_keys=("gearsystem_bios_gg",),
        needs=(Need("Master System BIOS", ("bios.sms",)), Need("Game Gear BIOS", ("bios.gg",))),
        any_need=True, cores=("gearsystem_libretro",), library="Gearsystem", prefix="gearsystem_"),
    IntroSetting(
        "genesis-plus-gx", "Genesis Plus GX", "Mega Drive / Genesis, Master System, Game Gear",
        "genesis_plus_gx_bios", "enabled", "disabled", default_on=False,
        needs=(Need("Mega Drive TMSS BIOS", ("bios_MD.bin",)),
               Need("Master System BIOS", ("bios_U.sms", "bios_E.sms", "bios_J.sms")),
               Need("Game Gear BIOS", ("bios.gg",))),
        any_need=True, cores=("genesis_plus_gx_libretro",), library="Genesis Plus GX",
        prefix="genesis_plus_gx_",
        note="Sega CD games always start through the CD BIOS: no setting skips it."),
    IntroSetting(
        "genesis-plus-gx-wide", "Genesis Plus GX Wide", "Mega Drive / Genesis, Master System, Game Gear",
        "genesis_plus_gx_wide_bios", "enabled", "disabled", default_on=False,
        needs=(Need("Mega Drive TMSS BIOS", ("bios_MD.bin",)),
               Need("Master System BIOS", ("bios_U.sms", "bios_E.sms", "bios_J.sms")),
               Need("Game Gear BIOS", ("bios.gg",))),
        any_need=True, cores=("genesis_plus_gx_wide_libretro",), library="Genesis Plus GX Wide",
        prefix="genesis_plus_gx_wide_"),
    IntroSetting(
        "beetle-psx", "Beetle PSX", "PlayStation",
        "beetle_psx_skip_bios", "disabled", "enabled", default_on=True,
        needs=(Need("PlayStation BIOS", _PS1_BIOS + ("scph5503.bin", "scph7003.bin", "scph5552.bin")),),
        cores=("mednafen_psx_libretro",), library="Beetle PSX", prefix="beetle_psx_",
        note="Without a Sony BIOS it runs its built-in OpenBIOS, which has no logo."),
    IntroSetting(
        "beetle-psx-hw", "Beetle PSX HW", "PlayStation",
        "beetle_psx_hw_skip_bios", "disabled", "enabled", default_on=True,
        needs=(Need("PlayStation BIOS", _PS1_BIOS + ("scph5503.bin", "scph7003.bin", "scph5552.bin")),),
        cores=("mednafen_psx_hw_libretro",), library="Beetle PSX HW", prefix="beetle_psx_hw_"),
    IntroSetting(
        "pcsx-rearmed", "PCSX ReARMed", "PlayStation",
        "pcsx_rearmed_show_bios_bootlogo", "enabled", "disabled", default_on=False,
        blocked_by=(("pcsx_rearmed_bios", "HLE",
                     "pcsx_rearmed_bios is HLE, which has no logo: set it to auto first"),),
        needs=(Need("PlayStation BIOS", _PS1_BIOS + ("psxonpsp660.bin", "scph101.bin",
                                                     "scph7001.bin", "scph1001.bin")),),
        cores=("pcsx_rearmed_libretro",), library="PCSX-ReARMed", prefix="pcsx_rearmed_"),
    IntroSetting(
        "swanstation", "SwanStation", "PlayStation",
        "swanstation_BIOS_PatchFastBoot", "false", "true", default_on=True,
        needs=(Need("PlayStation BIOS", _PS1_BIOS),),
        cores=("swanstation_libretro",), library="SwanStation", prefix="swanstation_"),
    IntroSetting(
        "flycast-core", "Flycast", "Dreamcast",
        "reicast_hle_bios", "disabled", "enabled", default_on=True,
        needs=(Need("Dreamcast BIOS", ("dc_boot.bin", "dc_bios.bin"), subdirs=("dc",)),),
        cores=("flycast_libretro",), library="Flycast", prefix="reicast_",
        note="Off runs Flycast's built-in BIOS (no swirl). Flycast still picks the real BIOS "
             "for the few games that need it."),
    IntroSetting(
        "melonds-ds", "melonDS DS", "Nintendo DS",
        "melonds_boot_mode", "native", "direct", default_on=False,
        also_on=(("melonds_sysfile_mode", "native", True),),
        needs=(Need("DS ARM7 BIOS", ("bios7.bin",), subdirs=("", "melonDS DS")),
               Need("DS ARM9 BIOS", ("bios9.bin",), subdirs=("", "melonDS DS")),
               Need("DS firmware", ("firmware.bin",), subdirs=("", "melonDS DS"),
                    sizes=(131072, 262144, 524288), magic=b"MAC", magic_at=8)),
        cores=("melondsds_libretro",), library="melonDS DS", prefix="melonds_",
        note="On boots the DS firmware's start-up screen before the game."),
    IntroSetting(
        "melonds-core", "melonDS (legacy core)", "Nintendo DS",
        "melonds_boot_directly", "disabled", "enabled", default_on=False,
        needs=(Need("DS ARM7 BIOS", ("bios7.bin",)), Need("DS ARM9 BIOS", ("bios9.bin",)),
               Need("DS firmware", ("firmware.bin",))),
        cores=("melonds_libretro",), library="melonDS", prefix="melonds_"),
    IntroSetting(
        "desmume", "DeSmuME", "Nintendo DS",
        "desmume_boot_into_bios", "enabled", "disabled", default_on=False,
        also_on=(("desmume_use_external_bios", "enabled", False),
                 ("desmume_cpu_mode", "interpreter", False)),
        needs=(Need("DS ARM7 BIOS", ("bios7.bin",)), Need("DS ARM9 BIOS", ("bios9.bin",)),
               Need("DS firmware", ("firmware.bin",))),
        cores=("desmume_libretro",), library="DeSmuME", prefix="desmume_",
        note="On also needs its external BIOS and the interpreter CPU (slower than its JIT)."),
    IntroSetting(
        "virtual-jaguar", "Virtual Jaguar", "Atari Jaguar",
        "virtualjaguar_bios", "enabled", "disabled", default_on=False,
        cores=("virtualjaguar_libretro",), library="Virtual Jaguar", prefix="virtualjaguar_",
        note="Its boot ROMs are built in (cartridge games; Jaguar CD has its own setting)."),
    IntroSetting(
        "dolphin-core", "Dolphin", "GameCube",
        "dolphin_skip_gc_bios", "disabled", "enabled", default_on=False,
        needs=(Need("GameCube IPL", ("IPL.bin",),
                    subdirs=tuple(f"dolphin-emu\\Sys\\GC\\{r}" for r in ("USA", "EUR", "JAP", "DEV"))),),
        cores=("dolphin_libretro",), library="dolphin-emu", prefix="dolphin_"),
    # ── Standalone emulators ──
    IntroSetting(
        "duckstation", "DuckStation", "PlayStation",
        "PatchFastBoot", "false", "true", default_on=True, section="BIOS",
        exes=("duckstation",), locate=_duckstation_files,
        note="[Main] DisableAllEnhancements = true plays the logo whatever this says."),
    IntroSetting(
        "pcsx2", "PCSX2", "PlayStation 2",
        "EnableFastBoot", "false", "true", default_on=False, section="EmuCore",
        exes=("pcsx2",), exe_has="qt", locate=_pcsx2_files,
        note="A -fastboot / -slowboot on the command line or a per-game setting wins over this."),
    IntroSetting(
        "dolphin", "Dolphin", "GameCube",
        "SkipIPL", "False", "True", default_on=False, section="Core",
        exes=("dolphin",), locate=_dolphin_files, check=_dolphin_check,
        note="GameCube only; Wii games never show it."),
    IntroSetting(
        "flycast", "Flycast", "Dreamcast",
        "UseReios", "no", "yes", default_on=True, section="config",
        exes=("flycast",), locate=_flycast_files, check=_flycast_check,
        note="Off runs Flycast's built-in BIOS (no swirl). Flycast still picks the real BIOS "
             "for the few games that need it."),
    IntroSetting(
        "xemu", "xemu", "Xbox",
        "skip_boot_anim", "false", "true", default_on=True, section="general", style="toml",
        exes=("xemu",), locate=_xemu_files,
        note="Off shortens the Xbox boot animation."),
    IntroSetting(
        "melonds", "melonDS", "Nintendo DS",
        "DirectBoot", "false", "true", default_on=False, section="Emu", style="toml",
        also_on=(("ExternalBIOSEnable", "true", False),),
        exes=("melonds",), locate=_melonds_toml, check=_melonds_paths("DS", "toml"),
        note="On boots the DS firmware's start-up screen before the game."),
    IntroSetting(
        "melonds", "melonDS", "Nintendo DS",
        "DirectBoot", "0", "1", default_on=False, separator="=",
        also_on=(("ExternalBIOSEnable", "1", False),),
        exes=("melonds",), locate=_melonds_ini, check=_melonds_paths("", "ini")),
)

# RetroArch cores with no start-up logo setting: core DLL -> (name, why).
RETROARCH_NO_SETTING: dict[str, tuple[str, str]] = {
    "sameboy_libretro": ("SameBoy", "always plays its own boot ROMs"),
    "picodrive_libretro": ("PicoDrive", "no setting; Sega CD always starts through its BIOS"),
    "prosystem_libretro": ("ProSystem", "plays the 7800 BIOS whenever the file is there"),
    "opera_libretro": ("Opera", "no setting"),
    "neocd_libretro": ("NeoCD", "no setting"),
    "mednafen_saturn_libretro": ("Beetle Saturn", "no setting"),
    "yabause_libretro": ("Yabause", "only an HLE BIOS switch, which also changes how games run"),
    "kronos_libretro": ("Kronos", "only an HLE BIOS switch, which also changes how games run"),
    "yabasanshiro_libretro": ("YabaSanshiro", "only an HLE BIOS switch, which also changes how games run"),
    "mednafen_pcfx_libretro": ("Beetle PC-FX", "no setting"),
    "mednafen_pce_libretro": ("Beetle PCE", "no setting"),
    "mednafen_pce_fast_libretro": ("Beetle PCE Fast", "no setting"),
    "mesen_libretro": ("Mesen", "no setting for the Famicom Disk System BIOS"),
    "fceumm_libretro": ("FCEUmm", "no setting for the Famicom Disk System BIOS"),
    "nestopia_libretro": ("Nestopia", "no setting for the Famicom Disk System BIOS"),
}

# Standalone emulators with none: exe name prefix -> (name, why).  The
# closed-source ones may have one, but nothing SpinDoctor can check.
PROGRAMS_NO_SETTING: dict[str, tuple[str, str]] = {
    "pcsx2": ("PCSX2 1.x", "only the --fullboot command-line switch"),
    "mednafen": ("Mednafen", "no setting"),
    "cemu": ("Cemu", "no setting"),
    "rpcs3": ("RPCS3", "no setting"),
    "vita3k": ("Vita3K", "no setting"),
    "azahar": ("Azahar", "no setting"),
    "citra": ("Citra", "no setting"),
    "lime3ds": ("Lime3DS", "no setting"),
    "project64": ("Project64", "no setting"),
    "snes9x": ("Snes9x", "no setting"),
    "supermodel": ("Supermodel", "no setting"),
    "ppsspp": ("PPSSPP", "its GameBootAnimation needs files from a PSP firmware; not covered"),
    "ssf": ("SSF", "closed source: no setting to check"),
    "demul": ("Demul", "closed source: no setting to check"),
    "bigpemu": ("BigPEmu", "closed source: no setting to check"),
    "redream": ("Redream", "closed source: no setting to check"),
    "fusion": ("Kega Fusion", "closed source: no setting to check"),
}


# ── What is on the cabinet ───────────────────────────────────────────────────

@dataclass(eq=False)
class Target:
    """One emulator (or RetroArch core) on the cabinet with a logo setting."""
    setting: IntroSetting
    program: str                     # emulator folder name ("RetroArch 1.22.2")
    folder: Path
    used_by: list[str] = field(default_factory=list)   # RocketLauncher emulator names
    files: list[Path] = field(default_factory=list)    # where the key is set
    values: dict = field(default_factory=dict)         # (file, key) -> value, None = absent
    also: dict = field(default_factory=dict)           # (file, key) -> value of also_on keys
    blocked: str = ""                # a blocked_by reason that applies
    found: list[str] = field(default_factory=list)     # needed files found
    missing: list[str] = field(default_factory=list)   # needed files not found
    problem: str = ""                # why it can't be changed at all
    layouts: list = field(default_factory=list)        # RetroArch layouts (cores only)

    @property
    def label(self) -> str:
        """Shown name: the emulator or core, then its folder unless that's the same."""
        if self.program.lower() == self.setting.name.lower():
            return self.setting.name
        return f"{self.setting.name} ({self.program})"

    @property
    def also_ok(self) -> bool:
        for (_path, key), value in self.also.items():
            want, absent_ok = next((v, ok) for k, v, ok in self.setting.also_on if k == key)
            if value is None and not absent_ok:
                return False
            if value is not None and value.strip().lower() != want.lower():
                return False
        return True

    @property
    def state(self) -> Optional[bool]:
        """True: logo on, False: off, None: files or keys disagree, or nothing read."""
        states = {is_on(v, self.setting) for v in self.values.values()}
        if len(states) != 1:
            return None
        on = states.pop()
        return on and self.also_ok and not self.blocked

    @property
    def can_turn_on(self) -> bool:
        if not self.setting.has_needs:
            return True
        if self.setting.any_need:
            return bool(self.found)
        return not self.missing

    def matches(self, name: str) -> bool:
        n = name.strip().lower()
        return n in (self.setting.id, self.setting.name.lower(), self.program.lower(),
                     self.label.lower()) or n in (u.lower() for u in self.used_by)


@dataclass
class NoSetting:
    """An emulator on the cabinet that has no start-up logo setting."""
    name: str
    program: str
    reason: str


@dataclass
class Survey:
    targets: list[Target] = field(default_factory=list)
    no_setting: list[NoSetting] = field(default_factory=list)


def _read_values(target: Target) -> None:
    s = target.setting
    for path in target.files:
        text = ""
        if path.is_file():
            try:
                text = read_editable_text(path)
            except (OSError, UnicodeDecodeError) as e:
                target.problem = f"can't read {path}: {e}"
        for key in s.keys:
            target.values[(path, key)] = read_value(text, key, s.section, s.fmt) if text else None
        for key, _value, _ok in s.also_on:
            target.also[(path, key)] = read_value(text, key, s.section, s.fmt) if text else None
        for key, value, why in s.blocked_by:
            current = read_value(text, key, s.section, s.fmt) if text else None
            if current is not None and current.strip().lower() == value.lower():
                target.blocked = why


def _retroarch_targets(folder: Path, program: str,
                       used_by: list[str]) -> tuple[list[Target], list[NoSetting]]:
    layouts = retroarch_layouts(folder)
    systems = list(dict.fromkeys(layout.system_dir for layout in layouts))
    targets = []
    for setting in SETTINGS:
        if not setting.retroarch or not _ra_has_core(setting.cores, layouts):
            continue
        t = Target(setting, program, folder, list(used_by), _ra_core_files(setting, layouts),
                   layouts=layouts)
        _read_values(t)
        if setting.needs:
            if None in systems:
                t.missing.append("system_directory is \"default\", so the core looks beside "
                                 "each game: set RetroArch's system folder first")
            # Each config's system folder needs the files: a wheel started
            # with another config looks only in its own.
            for folder in (s for s in systems if s is not None):
                found, missing = _check_files(setting.needs, [folder])
                t.found += found
                t.missing += missing
        targets.append(t)
    plain = [NoSetting(f"{name} ({program})", program, reason)
             for core, (name, reason) in RETROARCH_NO_SETTING.items()
             if _ra_has_core((core,), layouts)]
    return targets, plain


def _program_target(setting: IntroSetting, folder: Path, program: str,
                    used_by: list[str]) -> Target:
    candidates = setting.locate(folder) if setting.locate else []
    path = next((p for p in candidates if p.is_file()), None)
    t = Target(setting, program, folder, list(used_by))
    if path is None:
        where = candidates[0] if candidates else folder
        t.problem = f"settings file not found ({where}); start {setting.name} once so it writes one"
        return t
    t.files = [path]
    _read_values(t)
    if setting.check is not None:
        try:
            text = read_editable_text(path)
        except OSError:
            text = ""
        t.found, t.missing = setting.check(folder, path, text)
    return t


def _program_folders(config) -> dict[Path, tuple[str, list[str]]]:
    """Emulator folder -> (exe name, RocketLauncher emulator names).

    From the ``Emu_Path`` of every section of ``Global Emulators.ini`` and of
    each system's ``Emulators.ini``.  Without RocketLauncher (or with no
    emulator entries), the folders one level under ``emulators_dir`` that hold
    a known emulator's exe.
    """
    from .health import _rl_emulator_entries, _subfolders

    found: dict[Path, tuple[str, list[str]]] = {}
    for section, _exe, candidates in _rl_emulator_entries(config):
        for candidate in candidates:
            if candidate.is_file():
                _name, names = found.setdefault(candidate.parent, (candidate.name, []))
                if section not in names:
                    names.append(section)
                break
    if not found and getattr(config, "emulators_dir", ""):
        for sub in _subfolders(Path(config.emulators_dir)):
            exe = _known_exe(sub)
            if exe:
                found[sub] = (exe, [])
    return found


def _exe_family(exe: str) -> str:
    e = exe.lower()
    if e.startswith("retroarch"):
        return "retroarch"
    if any(s.for_exe(e) for s in SETTINGS):
        return "setting"
    if any(e.startswith(prefix) for prefix in PROGRAMS_NO_SETTING):
        return "none"
    return ""


def _known_exe(folder: Path) -> str:
    try:
        with os.scandir(folder) as it:
            exes = sorted(e.name for e in it if e.name.lower().endswith(".exe") and e.is_file())
    except OSError:
        return ""
    return next((e for e in exes if _exe_family(e) not in ("", "none")), "")


def survey(config) -> Survey:
    """Every emulator on the cabinet with a start-up logo setting, and its state."""
    result = Survey()
    for folder, (exe, used_by) in sorted(_program_folders(config).items(),
                                         key=lambda kv: (kv[0].name.lower(), str(kv[0]))):
        program = folder.name
        family = _exe_family(exe)
        if family == "retroarch":
            targets, plain = _retroarch_targets(folder, program, used_by)
            result.targets += targets
            result.no_setting += plain
        elif family == "none":
            name, reason = next(v for k, v in PROGRAMS_NO_SETTING.items() if exe.lower().startswith(k))
            result.no_setting.append(NoSetting(name, program, reason))
        elif family == "setting":
            options = [s for s in SETTINGS if s.for_exe(exe)]
            # Settings that share an exe name (melonDS 1.x's TOML, 0.9's INI):
            # the first whose file exists, else the first.
            built = [_program_target(s, folder, program, used_by) for s in options]
            result.targets.append(next((t for t in built if not t.problem), built[0]))
    return result


# ── Planning and writing a change ────────────────────────────────────────────

@dataclass
class Change:
    target: Target
    file: Path
    key: str
    old: Optional[str]           # None: the key (or the file) isn't there yet
    new: str


@dataclass
class Plan:
    turn_on: bool
    changes: list[Change] = field(default_factory=list)
    already: list[Target] = field(default_factory=list)
    refused: list[tuple[Target, str]] = field(default_factory=list)

    def targets(self) -> list[Target]:
        seen: list[Target] = []
        for c in self.changes:
            if c.target not in seen:
                seen.append(c.target)
        return seen


def select(found: Survey, names: Iterable[str]) -> list[Target]:
    """The targets *names* pick (all of them for no names).

    A name is a setting name from ``boot-intros list`` (``gambatte``), an
    emulator or core name, an emulator folder name or a RocketLauncher
    emulator name, in any case.
    """
    names = [n for n in names if n.strip()]
    if not names:
        return list(found.targets)
    picked: list[Target] = []
    unknown = []
    for name in names:
        hits = [t for t in found.targets if t.matches(name)]
        if not hits:
            unknown.append(name)
        for t in hits:
            if t not in picked:
                picked.append(t)
    if unknown:
        known = sorted({t.setting.id for t in found.targets})
        plain = [x.name for x in found.no_setting
                 if any(n.strip().lower() in (x.name.lower(), x.program.lower(),
                                              x.name.split(" (")[0].lower()) for n in unknown)]
        msg = f"no start-up logo setting found for: {', '.join(unknown)}"
        if plain:
            msg += f" ({'; '.join(plain)}: no such setting)"
        msg += f". Names here: {', '.join(known) if known else 'none'}"
        raise BootIntroError(msg)
    return picked


def plan(targets: Iterable[Target], turn_on: bool) -> Plan:
    """What turning the logo on (or off) for *targets* would change."""
    result = Plan(turn_on)
    for t in targets:
        s = t.setting
        if t.problem:
            result.refused.append((t, t.problem))
            continue
        if turn_on and t.blocked:
            result.refused.append((t, t.blocked))
            continue
        if turn_on and not t.can_turn_on:
            result.refused.append((t, "needs " + "; ".join(t.missing)))
            continue
        want = s.on if turn_on else s.off
        changes = []
        for path in t.files:
            for key in s.keys:
                old = t.values.get((path, key))
                if is_on(old, s) != turn_on:
                    changes.append(Change(t, path, key, old, want))
            if turn_on:
                for key, value, absent_ok in s.also_on:
                    old = t.also.get((path, key))
                    if (old is None and not absent_ok) or (
                            old is not None and old.strip().lower() != value.lower()):
                        changes.append(Change(t, path, key, old, value))
        if changes:
            result.changes += changes
        else:
            result.already.append(t)
    return result


def _backup(path: Path, config) -> Optional[Path]:
    """Copy *path* to ``<name>.<YYYYMMDD_HHMMSS>.bak`` beside it (or in
    ``backup_dir\\Emulators\\<folder>``) when ``backup_before_modify`` is on."""
    if not getattr(config, "backup_before_modify", True) or not path.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = getattr(config, "backup_dir", "")
    if folder:
        target = Path(folder) / "Emulators" / path.parent.name / f"{path.name}.{stamp}.bak"
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        target = path.with_name(f"{path.name}.{stamp}.bak")
    target = unique_path(target)
    shutil.copy2(path, target)
    return target


@dataclass
class Written:
    file: Path
    backup: Optional[Path] = None
    created: bool = False
    error: str = ""


def write_plan(result: Plan, config) -> list[Written]:
    """Write *result*'s changes: one backup and one write per file.

    A RetroArch core's options file that doesn't exist yet is created, from
    the core's lines in the old shared options file when there is one.
    """
    by_file: dict[Path, list[Change]] = {}
    for change in result.changes:
        by_file.setdefault(change.file, []).append(change)
    written = []
    for path, changes in by_file.items():
        t = changes[0].target
        s = t.setting
        try:
            created = not path.is_file()
            text = read_editable_text(path) if not created else (
                _ra_seed(s, path, t.layouts) if s.retroarch else "")
            for c in changes:
                text = set_value(text, c.key, c.new, s.section, s.fmt, s.separator)
            backup = _backup(path, config)
            write_windows_text(path, text)
            written.append(Written(path, backup, created))
        except (OSError, UnicodeError) as e:
            written.append(Written(path, error=str(e)))
    return written
