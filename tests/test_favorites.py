"""Favorites store + cross-system rebuild."""
from __future__ import annotations

import pytest

import spindoctor.config as config_mod
from spindoctor.config import Config, save_config
from spindoctor.favorites import (
    FavoriteStore, _resolve_target_names, FavoriteEntry,
    add, load_store, rebuild, remove, save_store, sync_native,
)
from spindoctor.medialink import LinkMode


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    home = tmp_path / "spindoctor_home"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    config_mod.reset_override_cache()
    yield home
    config_mod.reset_override_cache()


def _build_layout(tmp_path):
    """Real-ish HyperSpin tree with two source systems and media."""
    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"

    for sys_name in ("Super Nintendo", "Sony Playstation"):
        (roms / sys_name).mkdir(parents=True)
        (hs / "Databases" / sys_name).mkdir(parents=True)
        (hs / "Databases" / sys_name / f"{sys_name}.xml").write_text(
            "<menu>"
            "<game name=\"Tetris\">"
            "<description>Tetris</description>"
            "<manufacturer>Nintendo</manufacturer>"
            "<year>1989</year><genre>Puzzle</genre>"
            "</game></menu>",
            encoding="utf-8",
        )
        (hs / "Media" / sys_name / "Images" / "Wheel").mkdir(parents=True)
        (hs / "Media" / sys_name / "Images" / "Wheel" / "Tetris.png").write_bytes(b"wheel")

    return roms, hs, rl


def _cfg(roms, hs, rl):
    cfg = Config()
    cfg.roms_dir = str(roms)
    cfg.hyperspin_dir = str(hs)
    cfg.rocketlauncher_dir = str(rl)
    save_config(cfg)
    return cfg


def test_add_and_remove_round_trip(isolated_config, tmp_path, monkeypatch):
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        tmp_path / "favorites.json")
    store = FavoriteStore()
    assert add(store, "snes", "Mario", "Super Mario World") is True
    assert add(store, "snes", "Mario") is False  # duplicate
    save_store(store, tmp_path / "favorites.json")

    reloaded = load_store(tmp_path / "favorites.json")
    assert len(reloaded.entries) == 1
    assert reloaded.entries[0].display_name == "Super Mario World"
    assert remove(reloaded, "snes", "Mario") is True
    assert remove(reloaded, "snes", "Mario") is False


def test_resolve_target_names_disambiguates_collisions():
    entries = [
        FavoriteEntry("Super Nintendo", "Tetris", "Tetris", ""),
        FavoriteEntry("Sony Playstation", "Tetris", "Tetris", ""),
        FavoriteEntry("Super Nintendo", "Mario", "Mario", ""),
    ]
    names = _resolve_target_names(entries)
    values = list(names.values())
    assert "Tetris (Super Nintendo)" in values
    assert "Tetris (Sony Playstation)" in values
    assert "Mario" in values  # unique → no suffix
    assert len(set(values)) == 3


def test_rebuild_writes_database_and_media(isolated_config, tmp_path, monkeypatch):
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    store = FavoriteStore()
    add(store, "Super Nintendo", "Tetris")
    add(store, "Sony Playstation", "Tetris")

    summary = rebuild(store, cfg, media_mode=LinkMode.COPY)
    assert summary.entries == 2
    assert summary.db_path.exists()

    # Both Tetris entries should be disambiguated in the wheel
    db_text = summary.db_path.read_text(encoding="utf-8")
    assert "Tetris (Super Nintendo)" in db_text
    assert "Tetris (Sony Playstation)" in db_text

    # Media files mirrored under disambiguated names
    fav_wheels = list((hs / "Media" / "Favorites" / "Images" / "Wheel").iterdir())
    names = {f.stem for f in fav_wheels}
    assert "Tetris (Super Nintendo)" in names
    assert "Tetris (Sony Playstation)" in names

    # PCLauncher INI generated for each entry
    inis = list((rl / "Modules" / "PCLauncher" / "Favorites").iterdir())
    assert len(inis) == 2
    ini_text = (rl / "Modules" / "PCLauncher" / "Favorites" / "Tetris (Super Nintendo).ini").read_text()
    assert 'parameters=-s "Super Nintendo"' in ini_text


def test_rebuild_prunes_removed_favorite(isolated_config, tmp_path, monkeypatch):
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    store = FavoriteStore()
    add(store, "Super Nintendo", "Tetris")
    rebuild(store, cfg, media_mode=LinkMode.COPY)
    # Now drop the favorite and rebuild
    remove(store, "Super Nintendo", "Tetris")
    summary = rebuild(store, cfg, media_mode=LinkMode.COPY)

    assert summary.entries == 0
    assert summary.pruned == 1
    # Mirrored media for the removed game is gone
    fav_wheels = list((hs / "Media" / "Favorites" / "Images" / "Wheel").glob("*"))
    assert fav_wheels == []


def test_rebuild_orders_games_alphabetically(isolated_config, tmp_path, monkeypatch):
    roms, hs, rl = _build_layout(tmp_path)
    # Add a second game per system so we have something to sort.
    for sys_name in ("Super Nintendo", "Sony Playstation"):
        (hs / "Databases" / sys_name / f"{sys_name}.xml").write_text(
            "<menu>"
            "<game name=\"Tetris\"><description>Tetris</description></game>"
            "<game name=\"Aladdin\"><description>Aladdin</description></game>"
            "<game name=\"Mario\"><description>Mario</description></game>"
            "</menu>",
            encoding="utf-8",
        )
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    # Add deliberately out of order
    store = FavoriteStore()
    add(store, "Super Nintendo", "Tetris")
    add(store, "Super Nintendo", "Aladdin")
    add(store, "Sony Playstation", "Mario")

    summary = rebuild(store, cfg, media_mode=LinkMode.COPY)
    db_text = summary.db_path.read_text(encoding="utf-8")

    # XML preserves dict order, which now matches alphabetical display name
    pos_aladdin = db_text.index("name=\"Aladdin\"")
    pos_mario = db_text.index("name=\"Mario\"")
    pos_tetris = db_text.index("name=\"Tetris\"")
    assert pos_aladdin < pos_mario < pos_tetris


def test_rebuild_reorders_existing_wheel(isolated_config, tmp_path, monkeypatch):
    """A second rebuild after adding an earlier-alphabet game should reorder."""
    roms, hs, rl = _build_layout(tmp_path)
    for sys_name in ("Super Nintendo",):
        (hs / "Databases" / sys_name / f"{sys_name}.xml").write_text(
            "<menu>"
            "<game name=\"Tetris\"><description>Tetris</description></game>"
            "<game name=\"Aladdin\"><description>Aladdin</description></game>"
            "</menu>",
            encoding="utf-8",
        )
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    store = FavoriteStore()
    add(store, "Super Nintendo", "Tetris")
    rebuild(store, cfg, media_mode=LinkMode.COPY)

    # Now add Aladdin (alphabetically earlier) and rebuild
    add(store, "Super Nintendo", "Aladdin")
    summary = rebuild(store, cfg, media_mode=LinkMode.COPY)
    db_text = summary.db_path.read_text(encoding="utf-8")
    assert db_text.index("name=\"Aladdin\"") < db_text.index("name=\"Tetris\"")


def test_sorted_entries_uses_display_name_case_insensitive():
    from spindoctor.favorites import _sorted_entries
    entries = [
        FavoriteEntry("snes", "zelda", "Zelda", ""),
        FavoriteEntry("snes", "aladdin", "aladdin", ""),
        FavoriteEntry("snes", "mario", "Mario", ""),
    ]
    ordered = [e.display_name for e in _sorted_entries(entries)]
    assert ordered == ["aladdin", "Mario", "Zelda"]


def test_sync_native_picks_up_per_system_favorites(isolated_config, tmp_path, monkeypatch):
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    # HyperSpin's per-system favorites list — one ROM per system
    (hs / "Databases" / "Super Nintendo" / "Super Nintendo_Favorites.ini").write_text(
        "Tetris\n", encoding="utf-8",
    )
    store = FavoriteStore()
    n = sync_native(store, cfg)
    assert n == 1
    assert store.find("Super Nintendo", "Tetris") is not None
