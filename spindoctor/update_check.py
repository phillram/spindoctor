"""GitHub release-tag check for the GUI launcher.

Fetches the latest release tag from the public GitHub Releases API and
compares it against the embedded ``__version__``. The GUI uses this for
a non-blocking "an update is available" hint on launch — failures are
intentionally silent so an offline cabinet, a GitHub outage, or a
firewall doesn't stop the user from getting on with their work.

Kept separate from the GUI module so:

* It can be unit-tested without spinning up Tk.
* Other surfaces (a future ``spindoctor self-check`` CLI command, the
  build smoke test, …) can reuse the same comparison logic.
* The GUI's import-light-on-startup property is preserved — the heavier
  ``urllib.request`` import only happens when the check actually runs.

No third-party HTTP libraries — :mod:`urllib.request` from the stdlib
keeps the frozen exe size flat.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional


# Public GitHub Releases endpoint. Anonymous calls are rate-limited to
# 60/hour per IP — fine for one check on GUI launch (and a manual
# Help → Check for updates click), nowhere near the limit.
_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/phillram/spindoctor/releases/latest"
)

# Short timeout — we don't want the GUI to feel sluggish if GitHub is
# slow. The thread that drives this is daemonic anyway, so the worst
# case is "no notification this run".
_TIMEOUT_SECONDS = 5

# Opt-out env var for users who want a hermetic launch. Documented in
# README's troubleshooting section once the feature lands.
_DISABLE_ENV = "SPINDOCTOR_NO_UPDATE_CHECK"


@dataclass(frozen=True)
class UpdateCheckResult:
    """Outcome of a release-tag check.

    ``newer_available`` is the load-bearing field — everything else is
    metadata for the caller's status message.
    """
    newer_available: bool
    current: str
    latest: str
    release_url: str


class UpdateCheckDisabled(RuntimeError):
    """Raised when the env-var opt-out is set."""


def _parse_version(s: str) -> Optional[tuple[int, ...]]:
    """Return ``(major, minor, patch, …)`` for a SemVer-ish string.

    Accepts a leading ``v`` (which GitHub release tags use) and any
    trailing pre-release/build qualifier, which we drop on the floor —
    a "newer" pre-release shouldn't fire a notification at a stable
    user. Returns None when the string isn't parseable so callers can
    distinguish "couldn't compare" from "actual version".
    """
    m = re.match(r"v?(\d+(?:\.\d+)*)", s.strip())
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    """True iff *latest* sorts after *current* by SemVer-ish tuple."""
    lat = _parse_version(latest)
    cur = _parse_version(current)
    if lat is None or cur is None:
        return False
    # Pad to equal length so (1, 4) compares cleanly against (1, 4, 0).
    n = max(len(lat), len(cur))
    return lat + (0,) * (n - len(lat)) > cur + (0,) * (n - len(cur))


def fetch_latest_release(
    *, url: str = _LATEST_RELEASE_URL, timeout: float = _TIMEOUT_SECONDS,
) -> tuple[str, str]:
    """Fetch the latest release tag and HTML URL from GitHub.

    Returns ``(tag, html_url)``. Raises :class:`urllib.error.URLError`
    or :class:`json.JSONDecodeError` on transport / parsing failures —
    callers are expected to swallow them quietly when running on the
    background launch thread.
    """
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            # GitHub asks for a user agent. Identify ourselves rather
            # than spoofing a browser — easier to debug on their end if
            # we ever rate-limit ourselves.
            "User-Agent": "spindoctor-gui-update-check",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed URL
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    return payload["tag_name"], payload.get("html_url", "")


def check_for_update(current_version: str) -> Optional[UpdateCheckResult]:
    """Return an :class:`UpdateCheckResult` or ``None`` when no info available.

    The "no info" case covers offline launches, GitHub outages, and
    unparseable tags — they're all "we don't know, leave the user
    alone" rather than "definitely up to date".

    Raises :class:`UpdateCheckDisabled` when ``SPINDOCTOR_NO_UPDATE_CHECK``
    is set so callers can distinguish "user opted out" from "couldn't
    reach GitHub" in their status message if they want to.
    """
    if os.environ.get(_DISABLE_ENV):
        raise UpdateCheckDisabled(
            f"{_DISABLE_ENV} is set; skipping release-tag lookup."
        )
    try:
        tag, html_url = fetch_latest_release()
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, KeyError, OSError, TimeoutError):
        return None
    if _parse_version(tag) is None:
        return None
    return UpdateCheckResult(
        newer_available=is_newer(tag, current_version),
        current=current_version,
        latest=tag,
        release_url=html_url,
    )
