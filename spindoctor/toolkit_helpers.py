"""The helpers `install-tools` can write, each one picked on its own.

A helper is a ``.bat`` file that runs one SpinDoctor command through the
install that wrote it.  `install-tools --tool <name>` writes the ones picked,
for HyperSpin's Tools menu or, with ``--add-to-system``, as entries on a
maintenance wheel such as Toolkit; `uninstall-tools --tool <name>` removes
them; the GUI shows the same list as a checklist and `doctor` checks the
files.  Nothing here touches the disk.
"""
from __future__ import annotations

import re
from typing import Callable, Iterable, NamedTuple, Optional, Sequence

from ._runtime import tool_command_text


class Helper(NamedTuple):
    """One helper: its name is the ``.bat`` stem, the wheel entry and the
    PCLauncher section, so it must stay the same from release to release."""

    name: str
    summary: str
    body: Callable[[], str]

    @property
    def key(self) -> str:
        """What ``--tool`` takes: the name in lower case, hyphens for spaces."""
        return _normalise(self.name)


def _normalise(value: str) -> str:
    return re.sub(r"[\s_-]+", "-", value.strip().lower())


# The .bat bodies are built when they are written, not at import, so that
# ``sys.executable`` names the frozen GUI or CLI the user actually ran.

def _refresh_one(tool: str, args: str, comment: str) -> Callable[[], str]:
    def body() -> str:
        return (
            "@echo off\r\n"
            f"REM {comment}\r\n"
            f'start "" /B /WAIT {tool_command_text(tool)} {args}\r\n'
            "if errorlevel 1 pause\r\n"
            "exit\r\n"
        )
    return body


def _refresh_all() -> str:
    fav = tool_command_text("spindoctor-fav")
    recent = tool_command_text("spindoctor-recent")
    stats = tool_command_text("spindoctor-stats")
    return (
        "@echo off\r\n"
        "REM Refresh all three wheels. Pause on ANY step's failure so a\r\n"
        "REM silent fail-and-close doesn't hide which wheel didn't rebuild.\r\n"
        f'start "" /B /WAIT {fav} rebuild --apply\r\n'
        "if errorlevel 1 (echo. & echo Favorites step failed. & pause & exit /b 1)\r\n"
        f'start "" /B /WAIT {recent} rebuild --apply\r\n'
        "if errorlevel 1 (echo. & echo Recently Played step failed. & pause & exit /b 1)\r\n"
        f'start "" /B /WAIT {stats} build-wheel --apply\r\n'
        "if errorlevel 1 (echo. & echo Most Played step failed. & pause & exit /b 1)\r\n"
    )


def _toolkit(command: str, comment: str) -> Callable[[], str]:
    """A helper that starts ``spindoctor toolkit <command>`` and returns at once.

    Not waited for: RocketLauncher ends and HyperSpin comes back while the
    command's own window takes the front.
    """
    def body() -> str:
        return (
            "@echo off\r\n"
            f"REM {comment}\r\n"
            f'start "" {tool_command_text("spindoctor")} toolkit {command}\r\n'
            "exit\r\n"
        )
    return body


#: Every helper, in the order lists show them.
HELPERS: tuple = (
    Helper("Refresh Favorites", "rebuild the Favorites wheel",
           _refresh_one("spindoctor-fav", "rebuild --apply",
                        "Regenerates the cross-system HyperSpin Favorites wheel.")),
    Helper("Refresh Recently Played", "rebuild the Recently Played wheel from RocketLauncher's statistics",
           _refresh_one("spindoctor-recent", "rebuild --apply",
                        "Regenerates the Recently Played wheel from RocketLauncher stats.")),
    Helper("Refresh Most Played", "rebuild the Most Played wheel from RocketLauncher's play time",
           _refresh_one("spindoctor-stats", "build-wheel --apply",
                        "Regenerates the Most Played wheel from RocketLauncher playtime.")),
    Helper("Refresh All", "rebuild all three wheels, stopping at the first that fails", _refresh_all),
    Helper("Shut Down Cabinet", "count down 5 seconds (Esc cancels), close HyperSpin, then shut Windows down",
           _toolkit("shutdown", "Shut Down Cabinet: a 5-second countdown (Esc cancels), "
                                "then HyperSpin closes and Windows shuts down.")),
)

#: Names older versions wrote and this one never does, with the helper that
#: replaced each ("Refresh Both" became "Refresh All" in v2.4.27).  Removed
#: on sight by install-tools and uninstall-tools.
RENAMED: dict = {"Refresh Both": "Refresh All"}
LEGACY_NAMES: tuple = tuple(RENAMED)

#: Every name install-tools has ever written: its .bat/.ini stems, wheel
#: entries and PCLauncher module INI sections.
ALL_NAMES: frozenset = frozenset(h.name for h in HELPERS) | frozenset(LEGACY_NAMES)


def find(value: str) -> Optional[Helper]:
    """The helper *value* names, by key or name, ignoring case; or None."""
    want = _normalise(value)
    return next((h for h in HELPERS if h.key == want), None)


def pick(values: Iterable[str]) -> "list[Helper]":
    """``--tool`` values (repeated and/or comma-separated) as helpers.

    Each helper once, in list order.  Raises ``ValueError`` naming every
    value that is not a helper.
    """
    wanted: set = set()
    unknown: list = []
    for value in values:
        for part in str(value).split(","):
            if not part.strip():
                continue
            helper = find(part)
            if helper is None:
                unknown.append(part.strip())
            else:
                wanted.add(helper.name)
    if unknown:
        raise ValueError(", ".join(unknown))
    return [h for h in HELPERS if h.name in wanted]


def tool_option(helpers: Sequence[Helper]) -> str:
    """The ``--tool`` option that picks *helpers*, for messages and fixes."""
    return "--tool " + ",".join(h.key for h in helpers)
