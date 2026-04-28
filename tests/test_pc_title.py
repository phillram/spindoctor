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


def test_smart_uses_stem_for_top_level_shortcut(pc_root):
    p = _make(pc_root / "Hades.lnk")
    assert derive_pc_title(p, pc_root, "smart") == "Hades"


def test_smart_uses_top_level_folder_for_nested_exe(pc_root):
    p = _make(pc_root / "Cyberpunk 2077" / "bin" / "launcher.exe")
    assert derive_pc_title(p, pc_root, "smart") == "Cyberpunk 2077"


def test_smart_uses_immediate_parent_for_one_level_deep_exe(pc_root):
    p = _make(pc_root / "Hades" / "Hades.exe")
    assert derive_pc_title(p, pc_root, "smart") == "Hades"


def test_smart_uses_stem_for_top_level_exe(pc_root):
    p = _make(pc_root / "Standalone.exe")
    assert derive_pc_title(p, pc_root, "smart") == "Standalone"


def test_smart_uses_stem_for_nested_shortcut(pc_root):
    # An odd layout: shortcut nested inside a folder.  Stems beat parents
    # for shortcut files because the file *is* the title.
    p = _make(pc_root / "Steam" / "Hades.url")
    assert derive_pc_title(p, pc_root, "smart") == "Hades"


def test_stem_strategy_always_uses_filename(pc_root):
    p = _make(pc_root / "Cyberpunk 2077" / "bin" / "launcher.exe")
    assert derive_pc_title(p, pc_root, "stem") == "launcher"


def test_parent_folder_strategy(pc_root):
    p = _make(pc_root / "Cyberpunk 2077" / "bin" / "launcher.exe")
    assert derive_pc_title(p, pc_root, "parent_folder") == "bin"


def test_parent_folder_strategy_falls_back_to_stem_at_root(pc_root):
    p = _make(pc_root / "Standalone.exe")
    assert derive_pc_title(p, pc_root, "parent_folder") == "Standalone"


def test_shortcut_extensions_constant():
    assert SHORTCUT_EXTS == {".lnk", ".url"}
