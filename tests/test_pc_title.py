"""Title-extraction heuristics for PC/Windows/Steam game files."""
from __future__ import annotations

from pathlib import Path

import pytest

from spindoctor.romutils import SHORTCUT_EXTS, derive_pc_title


@pytest.fixture
def pc_root(tmp_path):
    root = tmp_path / "PC Games"
    root.mkdir()
    return root


def _make(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


@pytest.mark.parametrize("relpath, strategy, expected", [
    pytest.param("Hades.lnk", "smart", "Hades", id="smart-stem-for-top-level-shortcut"),
    pytest.param("Cyberpunk 2077/bin/launcher.exe", "smart", "Cyberpunk 2077",
                 id="smart-top-level-folder-for-nested-exe"),
    pytest.param("Hades/Hades.exe", "smart", "Hades",
                 id="smart-immediate-parent-for-one-level-deep-exe"),
    pytest.param("Standalone.exe", "smart", "Standalone", id="smart-stem-for-top-level-exe"),
    # An odd layout: shortcut nested inside a folder.  Stems beat parents
    # for shortcut files because the file *is* the title.
    pytest.param("Steam/Hades.url", "smart", "Hades", id="smart-stem-for-nested-shortcut"),
    pytest.param("Cyberpunk 2077/bin/launcher.exe", "stem", "launcher",
                 id="stem-strategy-always-uses-filename"),
    pytest.param("Cyberpunk 2077/bin/launcher.exe", "parent_folder", "bin",
                 id="parent-folder-strategy"),
    pytest.param("Standalone.exe", "parent_folder", "Standalone",
                 id="parent-folder-falls-back-to-stem-at-root"),
])
def test_derive_pc_title(pc_root, relpath, strategy, expected):
    p = _make(pc_root / relpath)
    assert derive_pc_title(p, pc_root, strategy) == expected


def test_shortcut_extensions_constant():
    assert SHORTCUT_EXTS == {".lnk", ".url"}
