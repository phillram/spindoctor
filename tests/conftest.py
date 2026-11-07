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


@pytest.fixture
def home(tmp_path, monkeypatch):
    """``~/.spindoctor`` inside the test's folder, so the run pointer
    (``tests/active.json``) and ``config.json`` never leave it."""
    import spindoctor.config as config_mod

    h = tmp_path / "home"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", h)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", h / "config.json")
    config_mod.reset_override_cache()
    yield h
    config_mod.reset_override_cache()
