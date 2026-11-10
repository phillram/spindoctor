"""``doctor`` findings for the games ``spindoctor test`` picked.

A launch test only sees whether a game starts.  These notes add what the
``doctor`` checks know about the same game, so a result can say "passed, but
no key presses Start" or "passed, but HyperSpin won't show it":

* **Coin/Start** (:mod:`spindoctor.coin_start`): a MAME or Supermodel game
  whose own Coin 1 / Start binding no key can press.
* **User Functions** (:mod:`spindoctor.rl_user_functions`): problems in the
  ``.ahk`` files RocketLauncher runs for this game, its system, its emulator
  or every launch (a missing program, a key mapper left running).
* **HyperSpin ROMs only**: with ``[filters] roms_only=true`` HyperSpin lists
  only the games it finds in ``[exe info] rompath``; RocketLauncher can
  launch a game HyperSpin hides.
* **Spaces in game names**: a name with a leading or trailing space, which
  HyperSpin looks for media under as written.

The checks only read files.  ``doctor`` reports them per wheel; these are the
same findings for one game at a time.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .config import Config
from .rl_rom_paths import _RomLookup, _raw_game_names, _resolve_rom_path
from .rocketlauncher import _read_rl_ini


def add_notes(config: Config, games: list, look: Optional[_RomLookup] = None) -> None:
    """Set ``doctor`` on each :class:`spindoctor.gametest.PlannedGame` in *games*."""
    if not games:
        return
    look = look or _RomLookup(Path(config.rocketlauncher_dir))
    coin = _CoinStart(look)
    user = _UserFunctions(config)
    hs = _HyperSpinFilter(config)
    raw_names: dict[str, dict[str, str]] = {}
    for g in games:
        notes: list[str] = []
        try:
            notes += coin.notes(g.system, g.game)
            notes += user.notes(g.system, g.game, g.emulator)
            if g.system not in raw_names:
                raw_names[g.system] = _raw_game_names(g.system, config.databases_dir)
            raw = raw_names[g.system]
            notes += hs.notes(g.system, g.game, raw)
            if g.game in raw:
                notes.append(f"Spaces in game names: the database writes it as {raw[g.game]!r}, "
                             "so HyperSpin looks for its media under that name")
        except Exception:  # noqa: BLE001 - a note must never stop a test run
            continue
        g.doctor = "; ".join(notes)


class _CoinStart:
    """Coin/Start per game: the emulator's own readers, as ``doctor`` builds them."""

    def __init__(self, look: _RomLookup):
        from .ledblinky_profiles import MESS_DRIVERS, MESS_PER_GAME_DRIVER

        self.look = look
        self.readers: dict[tuple[str, str], object] = {}
        self.overrides: dict[str, dict] = {}
        self.mess = {s.lower() for s in (*MESS_DRIVERS, *MESS_PER_GAME_DRIVER)}

    def _reader(self, system: str, emulator: str):
        from .coin_start import inputs_for
        from .health import _EMU_PATH_KEYS

        if not emulator or system.lower() in self.mess:
            return None
        found = self.look.system(system)
        data = found[2] if found else {}
        section = data.get(emulator.lower(), self.look.global_emus.get(emulator.lower(), {}))
        raw = next((section[k] for k in _EMU_PATH_KEYS if section.get(k)), "")
        path = _resolve_rom_path(raw.strip().strip('"'), self.look.rl_dir) if raw else None
        if path is None:
            return None
        key = (os.path.normcase(str(path.parent)), path.name.lower())
        if key not in self.readers:
            self.readers[key] = inputs_for(path.parent, path.name) if path.parent.is_dir() else None
        return self.readers[key]

    def notes(self, system: str, game: str) -> list[str]:
        from .coin_start import check_game

        if system not in self.overrides:
            self.overrides[system] = self.look.game_overrides(system)
        emu, other = self.overrides[system].get(game.lower(), ("", ""))
        target = other or system
        found = self.look.system(target)
        default = found[2][found[1]].get("default_emulator", "") if found else ""
        reader = self._reader(target, emu or default)
        if reader is None:
            return []
        finding = check_game(reader, game)
        if finding is None:
            return []
        return [f"Coin/Start: {finding.text()}; no key presses it ({reader.fix()})"]


class _UserFunctions:
    """User Functions findings that apply to one game's launch."""

    def __init__(self, config: Config):
        from .lightgun import index_user_functions
        from .rl_user_functions import scan_user_functions

        self.findings: dict[str, list] = {}
        self.index = None
        if not config.rocketlauncher_dir:
            return
        self.index = index_user_functions(Path(config.rocketlauncher_dir))
        if self.index.files:
            self.findings = scan_user_functions(self.index, _emulator_systems(config))

    def notes(self, system: str, game: str, emulator: str) -> list[str]:
        if not self.findings:
            return []
        s, g, e = system.lower(), game.lower(), emulator.lower()
        keys = [f"{s}/{g}.ahk", f"{s}.ahk", f"{s}/emulators/{e}.ahk", f"emulators/{e}.ahk", "global.ahk"]
        out = []
        for key in keys:
            for f in self.findings.get(key, ()):
                out.append(f"User Functions {self.index.label(key)}: {f.text}")
        return out


def _emulator_systems(config: Config) -> dict[str, set[str]]:
    """Lower-cased emulator → the Main Menu wheels that launch with it, as the
    ``doctor`` User Functions check passes it."""
    from .health import _main_menu_wheels
    from .lightgun import _system_emulators, system_settings_ini

    rl = Path(config.rocketlauncher_dir)
    out: dict[str, set[str]] = {}
    for wheel in _main_menu_wheels(config.databases_dir / "Main Menu" / "Main Menu.xml"):
        found = system_settings_ini(rl, wheel)
        if found is None:
            continue
        try:
            body = found[0].read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for emu in _system_emulators(rl, wheel, body):
            if emu:
                out.setdefault(emu, set()).add(wheel.lower())
    return out


class _HyperSpinFilter:
    """HyperSpin's ROMs-only filter, per wheel (``[filters] roms_only=true``)."""

    def __init__(self, config: Config):
        self.hs_dir = Path(config.hyperspin_dir)
        self.wheels: dict[str, Optional[tuple]] = {}

    def _wheel(self, system: str):
        from .health import _hs_rom_index, _setting_folder

        if system not in self.wheels:
            data = _read_rl_ini(self.hs_dir / "Settings" / f"{system}.ini")
            if data.get("filters", {}).get("roms_only", "").strip().lower() != "true":
                self.wheels[system] = None
            else:
                exe = data.get("exe info", {})
                value = exe.get("rompath", "").strip().strip('"').strip()
                exts = [e.strip().lstrip(".").lower() for e in exe.get("romextension", "").split(",")
                        if e.strip()]
                recursive = exe.get("searchsubfolders", "").strip().lower() == "true"
                folder = _setting_folder(value, self.hs_dir, False) if value else None
                index = _hs_rom_index(folder, recursive) if folder is not None else None
                self.wheels[system] = (value, folder, exts, index)
        return self.wheels[system]

    def notes(self, system: str, game: str, raw: dict[str, str]) -> list[str]:
        from .health import _hs_found

        wheel = self._wheel(system)
        if wheel is None:
            return []
        value, folder, exts, index = wheel
        if folder is None and value:
            return []  # a drive path that can't be checked on this OS
        where = f"Settings\\{system}.ini"
        if index is None:
            return [f"HyperSpin ROMs only: rompath={value or '(empty)'} in {where} can't be read, "
                    "so HyperSpin shows no games on this wheel"]
        if not _hs_found(index, [raw.get(game, game), game], exts):
            return [f"HyperSpin ROMs only: HyperSpin hides this game, it isn't in rompath={value} "
                    f"({where})"]
        return []
