"""Keep the test suite out of the developer's own ``~/.spindoctor``.

Most modules derive a per-user path from ``~/.spindoctor`` *at import
time* — ``config.CONFIG_DIR`` / ``CONFIG_FILE``, ``media_scan.MANIFEST_DIR``,
``scraper.SCRAPER_LOG_PATH`` and ``METADATA_CACHE_DIR``,
``themes.THEMES_DIR``, ``migrate.MIGRATIONS_DIR``,
``ledblinky.LISTXML_CACHE_DIR``, ``matcher.CACHE_DIR`` — so a test only stays
out of the real folder if it monkeypatches every one of those constants that
its code path touches. Many tests patch the ones they assert on and miss the
rest: running the suite rewrote ``~/.spindoctor/config.json``, appended to
``scraper.log`` and left ``media_imports/import-*.json`` manifests behind on
the machine running it.

Re-homing the whole process before the first ``spindoctor`` import re-points
every one of those constants at once, so no test can reach the real folder
even when it forgets to patch. Per-test patching still works as before: this
only moves where an unpatched path lands.
"""
import atexit
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

import pytest

if "spindoctor.config" in sys.modules:  # pragma: no cover - import-order guard
    raise RuntimeError(
        "spindoctor was imported before tests/conftest.py could re-home it; "
        "per-user paths would point at the real ~/.spindoctor"
    )

FAKE_HOME = Path(tempfile.mkdtemp(prefix="spindoctor-test-home-"))

os.environ["HOME"] = str(FAKE_HOME)
# Path.home() on Windows reads USERPROFILE first, then HOMEDRIVE + HOMEPATH.
os.environ["USERPROFILE"] = str(FAKE_HOME)
_drive, _tail = os.path.splitdrive(str(FAKE_HOME))
os.environ["HOMEDRIVE"] = _drive
os.environ["HOMEPATH"] = _tail or os.sep


@atexit.register
def _remove_fake_home():
    shutil.rmtree(FAKE_HOME, ignore_errors=True)


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_real_getaddrinfo = socket.getaddrinfo


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Fail any test that resolves a non-loopback host.

    Production code catches network errors and falls back, so an unmocked
    request does not fail on its own: it waits on DNS (seconds per call) and
    passes or fails depending on the network the suite runs on. The lookup
    still raises like an offline machine would, and the test is failed at
    teardown so the missing mock gets added.
    """
    attempts = []

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host is None or str(host) in _LOOPBACK_HOSTS:
            return _real_getaddrinfo(host, *args, **kwargs)
        attempts.append(host)
        raise socket.gaierror(f"real network access blocked in tests: {host!r}")

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    yield
    if attempts:
        pytest.fail(f"test attempted real network access: {sorted(set(map(str, attempts)))}")


@pytest.fixture
def config_home_factory(monkeypatch):
    """Opt in to config isolation at a caller-selected path, without mkdir.

    Specialized adapters can choose an existing tmp_path, a nonexistent
    subdirectory, or return CONFIG_FILE instead. Module-specific constants
    (manifest paths, imported CONFIG_DIR aliases) remain explicit adapters.
    Import lazily so the process-wide home guard above always runs first.
    """
    from spindoctor import config

    def configure(home):
        monkeypatch.setattr(config, "CONFIG_DIR", home)
        monkeypatch.setattr(config, "CONFIG_FILE", home / "config.json")
        config.reset_override_cache()
        return home

    try:
        yield configure
    finally:
        config.reset_override_cache()


@pytest.fixture
def config_home(tmp_path, config_home_factory):
    """Return an isolated, initially nonexistent config directory."""
    return config_home_factory(tmp_path / "spindoctor_home")


@pytest.fixture
def isolated_config(config_home):
    """Legacy no-return-value adapter for tests that only need isolation."""


@pytest.fixture
def home(tmp_path, config_home_factory):
    """Config home used by the game-launch test command fixtures."""
    return config_home_factory(tmp_path / "home")
