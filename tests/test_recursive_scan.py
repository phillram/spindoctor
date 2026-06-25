"""scan_roms() honours system_overrides recursive_scan + title_strategy."""
from __future__ import annotations

import pytest

import spindoctor.config as config_mod
from spindoctor.audit import scan_roms
from spindoctor.config import Config, save_config


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "spindoctor_home")
    monkeypatch.setattr(
        config_mod, "CONFIG_FILE", tmp_path / "spindoctor_home" / "config.json"
    )
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


@pytest.fixture
def pc_layout(tmp_path):
    """ROM layout mixing nested .exe installs and flat .lnk shortcuts."""
    roms = tmp_path / "roms"
    sys_dir = roms / "PC Games"
    sys_dir.mkdir(parents=True)
    (sys_dir / "Cyberpunk 2077").mkdir()
    (sys_dir / "Cyberpunk 2077" / "bin").mkdir()
    (sys_dir / "Cyberpunk 2077" / "bin" / "launcher.exe").touch()
    (sys_dir / "Hades.lnk").touch()
    (sys_dir / "Steam" / "Portal 2.url").parent.mkdir()
    (sys_dir / "Steam" / "Portal 2.url").touch()
    # Junk file with extension we don't claim — stays out of the result.
    (sys_dir / "ignore.txt").touch()
    return roms


def _save_overrides(overrides):
    cfg = Config()
    cfg.system_overrides = overrides
    save_config(cfg)


def test_flat_scan_is_default(isolated_config, pc_layout):
    # No overrides → default flat scan only sees the top-level .lnk
    # because .exe/.url aren't in the default extension set.  A genesis
    # rom is the simplest way to verify flat behaviour is preserved.
    roms = scan_roms("PC Games", pc_layout)
    assert roms == {}  # no override → no recognised extensions in this dir


def test_recursive_scan_finds_nested_files(isolated_config, pc_layout):
    _save_overrides({
        "PC Games": {
            "rom_extensions": [".exe", ".lnk", ".url"],
            "recursive_scan": True,
            "title_strategy": "smart",
        }
    })
    roms = scan_roms("PC Games", pc_layout)
    assert set(roms.keys()) == {"Cyberpunk 2077", "Hades", "Portal 2"}


def test_recursive_scan_strategy_stem(isolated_config, pc_layout):
    _save_overrides({
        "PC Games": {
            "rom_extensions": [".exe", ".lnk", ".url"],
            "recursive_scan": True,
            "title_strategy": "stem",
        }
    })
    roms = scan_roms("PC Games", pc_layout)
    # Stem-only mode keeps the literal filenames (sans extension).
    assert "launcher" in roms
    assert "Hades" in roms
    assert "Portal 2" in roms


def test_recursive_scan_dedupes_by_title(isolated_config, tmp_path):
    """Two files mapping to the same title — first wins."""
    roms_dir = tmp_path / "roms"
    sys_dir = roms_dir / "PC Games"
    sys_dir.mkdir(parents=True)
    # Same install: a launcher.exe + a desktop shortcut both for "Hades"
    (sys_dir / "Hades").mkdir()
    (sys_dir / "Hades" / "Hades.exe").touch()
    (sys_dir / "Hades.lnk").touch()

    _save_overrides({
        "PC Games": {
            "rom_extensions": [".exe", ".lnk"],
            "recursive_scan": True,
            "title_strategy": "smart",
        }
    })
    roms = scan_roms("PC Games", roms_dir)
    assert list(roms.keys()) == ["Hades"]


def test_recursive_scan_missing_dir(isolated_config, tmp_path):
    _save_overrides({
        "Nope": {"rom_extensions": [".exe"], "recursive_scan": True}
    })
    assert scan_roms("Nope", tmp_path / "roms") == {}


def test_recursive_scan_junk_file_deprioritised_when_main_exe_present(
    isolated_config, tmp_path
):
    """A game folder with both a real .exe and a setup.exe picks the real one."""
    roms_dir = tmp_path / "roms"
    sys_dir = roms_dir / "PC Games"
    game_dir = sys_dir / "Peglin"
    game_dir.mkdir(parents=True)
    (game_dir / "Peglin.exe").touch()
    (game_dir / "setup.exe").touch()
    (game_dir / "vcredist_x64.exe").touch()

    _save_overrides({
        "PC Games": {
            "rom_extensions": [".exe"],
            "recursive_scan": True,
            "title_strategy": "smart",
        }
    })
    roms = scan_roms("PC Games", roms_dir)
    assert "Peglin" in roms
    assert roms["Peglin"].path.name == "Peglin.exe", (
        "real exe should be picked over setup/junk executables"
    )


def test_recursive_scan_root_level_web_url_is_skipped(isolated_config, tmp_path):
    """A root-level .url file whose URL= line is http(s):// is dropped."""
    roms_dir = tmp_path / "roms"
    sys_dir = roms_dir / "PC Games"
    sys_dir.mkdir(parents=True)
    url_file = sys_dir / "GAMESTORRENT.CO.url"
    url_file.write_text(
        "[InternetShortcut]\r\nURL=https://gamestorrent.co/\r\n",
        encoding="utf-8",
    )
    (sys_dir / "Peglin.lnk").touch()  # valid shortcut as control

    _save_overrides({
        "PC Games": {
            "rom_extensions": [".exe", ".lnk", ".url"],
            "recursive_scan": True,
            "title_strategy": "smart",
        }
    })
    roms = scan_roms("PC Games", roms_dir)
    names = set(roms.keys())
    assert "GAMESTORRENT.CO" not in names, "web-URL shortcut must be filtered out"
    assert "Peglin" in names, "valid .lnk must still be included"


def test_recursive_scan_root_level_launch_prefix_lnk_is_skipped(
    isolated_config, tmp_path
):
    """A root-level .lnk whose stem starts with 'Launch ' is dropped."""
    roms_dir = tmp_path / "roms"
    sys_dir = roms_dir / "PC Games"
    sys_dir.mkdir(parents=True)
    (sys_dir / "Launch Ape Out.lnk").touch()
    (sys_dir / "Ape Out.lnk").touch()  # the real shortcut (no "Launch " prefix)

    _save_overrides({
        "PC Games": {
            "rom_extensions": [".lnk"],
            "recursive_scan": True,
            "title_strategy": "smart",
        }
    })
    roms = scan_roms("PC Games", roms_dir)
    assert "Launch Ape Out" not in roms, "'Launch …' shortcut must be filtered out"
    assert "Ape Out" in roms, "non-prefixed shortcut must be kept"
