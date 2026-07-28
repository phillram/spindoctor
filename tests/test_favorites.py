"""Favorites store + cross-system rebuild."""
from __future__ import annotations

import pytest

import spindoctor.config as config_mod
from spindoctor.config import Config, save_config
from spindoctor.favorites import (
    FavoriteStore, _resolve_target_names, FavoriteEntry,
    add, clear_native_favorites, load_store, rebuild, remove, save_store,
    sync_native, _read_text_robust, _find_favorites_txt, _parse_favorites_txt,
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
    assert 'ApplicationParameters=-s "Super Nintendo"' in ini_text
    assert "-p HyperSpin" in ini_text
    assert "[Settings]" in ini_text


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
    n, warns, notes = sync_native(store, cfg)
    assert n == 1
    assert warns == []
    assert store.find("Super Nintendo", "Tetris") is not None
    # The found ini file should be mentioned in notes
    assert any("Super Nintendo" in note for note in notes)


def test_sync_native_reports_no_favorites_found(isolated_config, tmp_path, monkeypatch):
    """When no _Favorites.ini files exist, notes explain where we looked."""
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    store = FavoriteStore()
    n, warns, notes = sync_native(store, cfg)
    assert n == 0
    # Notes should describe what was checked and give actionable guidance
    combined = " ".join(notes)
    assert "databases_dir" in combined or "_Favorites.ini" in combined


def test_sync_native_reads_utf8_bom_favorites(isolated_config, tmp_path, monkeypatch):
    """HyperSpin sometimes writes _Favorites.ini with a UTF-8 BOM — must still parse."""
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    ini_path = hs / "Databases" / "Super Nintendo" / "Super Nintendo_Favorites.ini"
    # Write with BOM (utf-8-sig)
    ini_path.write_text("Tetris\n", encoding="utf-8-sig")

    store = FavoriteStore()
    n, warns, notes = sync_native(store, cfg)
    assert n == 1
    assert store.find("Super Nintendo", "Tetris") is not None


def test_read_text_robust_handles_utf16(tmp_path):
    """_read_text_robust can decode UTF-16 encoded ini files."""
    path = tmp_path / "test.ini"
    path.write_text("Tetris\nMario\n", encoding="utf-16")
    result = _read_text_robust(path)
    assert "Tetris" in result
    assert "Mario" in result


def test_read_text_robust_handles_plain_utf8(tmp_path):
    path = tmp_path / "test.ini"
    path.write_text("Zelda\n", encoding="utf-8")
    assert "Zelda" in _read_text_robust(path)


# ─── favorites.txt support ────────────────────────────────────────────────────

def test_parse_favorites_txt_basic():
    text = "galaxian\ngalaga\ngt99\n# comment\n\n;another comment\npacman\n"
    result = _parse_favorites_txt(text)
    assert result == ["galaxian", "galaga", "gt99", "pacman"]


def test_parse_favorites_txt_empty():
    assert _parse_favorites_txt("") == []
    assert _parse_favorites_txt("\n\n  \n") == []


# ─── clear_native_favorites regex only strips favorite="1" ───────────────────

def test_clear_native_favorites_only_strips_value_one(isolated_config, tmp_path, monkeypatch):
    """clear_native_favorites must only remove favorite=\"1\" attributes.
    Attributes with other values (favorite=\"0\", favorite=\"false\") must
    be left untouched — stripping them would corrupt third-party markup."""

    hs = tmp_path / "hs"
    xml_dir = hs / "Databases" / "Arcade"
    xml_dir.mkdir(parents=True)
    xml_file = xml_dir / "Arcade.xml"
    xml_file.write_text(
        '<menu>'
        '<game name="Pac-Man" favorite="1"><description>Pac-Man</description></game>'
        '<game name="Galaga" favorite="0"><description>Galaga</description></game>'
        '<game name="Donkey Kong"><description>Donkey Kong</description></game>'
        '</menu>',
        encoding="utf-8",
    )

    roms = tmp_path / "roms"
    (roms / "Arcade").mkdir(parents=True)
    cfg = Config()
    cfg.roms_dir = str(roms)
    cfg.hyperspin_dir = str(hs)
    save_config(cfg)

    summary = clear_native_favorites(cfg, dry_run=False)
    content = xml_file.read_text(encoding="utf-8")

    # favorite="1" must be stripped
    assert 'favorite="1"' not in content
    # favorite="0" must be preserved
    assert 'favorite="0"' in content
    # tally should count only the "1" that was actually cleared
    assert summary.xml_games_cleared == 1


# ─── favorites.rebuild() write-before-delete ordering ────────────────────────

def test_rebuild_writes_media_before_deleting_orphans(isolated_config, tmp_path, monkeypatch):
    """Media files for current entries must be written before orphan cleanup.
    If an error mid-write would delete an orphan, the entry that needed that
    file would be left blank.  Verify the write pass runs first so existing
    valid entries are never accidentally erased."""
    monkeypatch.setattr(
        "spindoctor.favorites.FAVORITES_FILE",
        isolated_config / "favorites.json",
    )

    roms, hs, rl = _build_layout(tmp_path)
    cfg = _cfg(roms, hs, rl)

    # One favorite — builds the wheel once
    store = FavoriteStore(target_system="Favorites")
    add(store, "Super Nintendo", "Tetris")
    save_store(store, isolated_config / "favorites.json")

    # First rebuild creates the wheel media
    rebuild(store, cfg, media_mode=LinkMode.COPY)
    wheel_dir = hs / "Media" / "Favorites" / "Images" / "Wheel"
    assert any(wheel_dir.iterdir()), "first rebuild should create wheel media"

    # Second rebuild with the same store should NOT delete the just-written file
    rebuild(store, cfg, media_mode=LinkMode.COPY)
    assert any(wheel_dir.iterdir()), "second rebuild must not delete current entries' media"


def test_find_favorites_txt_case_insensitive(tmp_path):
    """_find_favorites_txt finds the file regardless of capitalisation."""
    sys_dir = tmp_path / "MAME"
    sys_dir.mkdir()
    # Write as "Favorites.txt" (capital F)
    (sys_dir / "Favorites.txt").write_text("pacman\n", encoding="utf-8")
    found = _find_favorites_txt(sys_dir)
    assert found is not None
    assert found.name == "Favorites.txt"


def test_find_favorites_txt_missing(tmp_path):
    sys_dir = tmp_path / "MAME"
    sys_dir.mkdir()
    assert _find_favorites_txt(sys_dir) is None


def test_sync_native_reads_favorites_txt(isolated_config, tmp_path, monkeypatch):
    """Favorites listed in favorites.txt are picked up by sync_native."""
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    # Write a favorites.txt matching the format the user reported
    (hs / "Databases" / "Super Nintendo" / "favorites.txt").write_text(
        "Tetris\n",
        encoding="utf-8",
    )
    store = FavoriteStore()
    n, warns, notes = sync_native(store, cfg)
    assert n == 1
    assert store.find("Super Nintendo", "Tetris") is not None
    assert warns == []
    # Notes should mention favorites.txt was found
    assert any("favorites.txt" in note for note in notes)


def test_sync_native_reads_favorites_txt_capital_f(isolated_config, tmp_path, monkeypatch):
    """favorites.txt is found even when capitalised as Favorites.txt."""
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    (hs / "Databases" / "Super Nintendo" / "Favorites.txt").write_text(
        "Tetris\n",
        encoding="utf-8",
    )
    store = FavoriteStore()
    n, warns, notes = sync_native(store, cfg)
    assert n == 1
    assert store.find("Super Nintendo", "Tetris") is not None


def test_sync_native_favorites_txt_warns_when_empty(isolated_config, tmp_path, monkeypatch):
    """An empty favorites.txt produces a warning rather than silent failure."""
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    (hs / "Databases" / "Super Nintendo" / "favorites.txt").write_text(
        "", encoding="utf-8",
    )
    store = FavoriteStore()
    n, warns, notes = sync_native(store, cfg)
    assert n == 0
    assert any("favorites.txt" in w and "0 parseable" in w for w in warns)


def test_sync_native_merges_both_ini_and_txt(isolated_config, tmp_path, monkeypatch):
    """A system can have both _Favorites.ini and favorites.txt; both are read."""
    roms, hs, rl = _build_layout(tmp_path)
    # Add extra games to the database XML so all ROM names resolve
    for sys_name in ("Super Nintendo",):
        (hs / "Databases" / sys_name / f"{sys_name}.xml").write_text(
            "<menu>"
            "<game name=\"Tetris\"><description>Tetris</description></game>"
            "<game name=\"Mario\"><description>Mario</description></game>"
            "</menu>",
            encoding="utf-8",
        )
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    (hs / "Databases" / "Super Nintendo" / "Super Nintendo_Favorites.ini").write_text(
        "Tetris\n", encoding="utf-8",
    )
    (hs / "Databases" / "Super Nintendo" / "favorites.txt").write_text(
        "Mario\n", encoding="utf-8",
    )
    store = FavoriteStore()
    n, warns, notes = sync_native(store, cfg)
    assert n == 2
    assert store.find("Super Nintendo", "Tetris") is not None
    assert store.find("Super Nintendo", "Mario") is not None


def test_sync_native_favorites_txt_real_format(isolated_config, tmp_path, monkeypatch):
    """Parse the exact multi-entry format from the user's MAME/favorites.txt."""
    roms, hs, rl = _build_layout(tmp_path)
    # Build a database with a subset of the real game names
    (hs / "Databases" / "Super Nintendo" / "Super Nintendo.xml").write_text(
        "<menu>"
        "<game name=\"galaxian\"><description>Galaxian</description></game>"
        "<game name=\"galaga\"><description>Galaga</description></game>"
        "<game name=\"pacman\"><description>Pac-Man</description></game>"
        "</menu>",
        encoding="utf-8",
    )
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    # Simulate the user's real file content
    (hs / "Databases" / "Super Nintendo" / "favorites.txt").write_text(
        "galaxian\ngalaga\ngt99\npacman\n",
        encoding="utf-8",
    )
    store = FavoriteStore()
    n, warns, notes = sync_native(store, cfg)
    # gt99 has no DB entry so display_name falls back to rom_name — still added
    assert n == 4
    assert store.find("Super Nintendo", "galaxian") is not None
    assert store.find("Super Nintendo", "gt99") is not None  # no DB entry but still added


# ── Emulators.ini + PCLauncher INI format ─────────────────────────────────────

def test_rebuild_writes_emulators_ini_in_system_folder(isolated_config, tmp_path, monkeypatch):
    """generate_synthetic_system_ini must write Settings/<system>/Emulators.ini.

    RocketLauncher installations that use the folder-based settings layout
    look for emulator routing in Settings/<system>/Emulators.ini, NOT in the
    top-level Settings/<system>.ini file.  Without this file RL throws
    "No default_emulator found in Settings/Favorites/Emulators.ini".
    """
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)
    (rl / "Settings").mkdir(parents=True, exist_ok=True)

    store = FavoriteStore()
    add(store, "Super Nintendo", "Tetris")
    rebuild(store, cfg, media_mode=LinkMode.COPY)

    emulators_ini = rl / "Settings" / "Favorites" / "Emulators.ini"
    assert emulators_ini.exists(), "Settings/Favorites/Emulators.ini was not written"
    body = emulators_ini.read_text(encoding="utf-8")
    # Section must be [ROMS] — folder-layout Emulators.ini files use [ROMS],
    # NOT [Settings].  RocketLauncher's AHK reads Default_Emulator from [ROMS]
    # in this file format.  Using [Settings] caused RL to write a blank
    # [ROMS]\nDefault_Emulator= entry, which then triggered "No Default_Emulator
    # found in Settings/Favorites/Emulators.ini" on every launch.
    assert "[ROMS]" in body
    assert "Default_Emulator=PCLauncher" in body
    # Rom_Extension=ini is required so RL looks for .ini files in the
    # PCLauncher dir, not the global default zip|rar|7z|… list.
    assert "Rom_Extension=ini" in body
    # Rom_Path must point at the PCLauncher module dir so RL knows where
    # to find the per-game INIs.
    pcl_dir = str(rl / "Modules" / "PCLauncher" / "Favorites")
    assert pcl_dir in body
    # The folder-layout Emulators.ini must include a [PCLauncher] section
    # with Rom_Extension=ini.  RL v1.2 reads Rom_Extension from the emulator
    # section ([PCLauncher]) first; when that section is absent from the system
    # file RL falls back to Global Emulators.ini's [PCLauncher] which may not
    # carry Rom_Extension=ini, causing RL to use its default extension list
    # (zip|rar|7z|…) and failing with "Cannot find Rom <name> with any
    # provided Rom_Extension: zip|rar|7z|…".
    assert "[PCLauncher]" in body
    assert body.count("Rom_Extension=ini") >= 2  # once in [ROMS], once in [PCLauncher]


def test_rebuild_flat_settings_ini_pclauncher_section_has_rom_extension(
    isolated_config, tmp_path, monkeypatch
):
    """The flat Settings/<system>.ini [PCLauncher] section must include Rom_Extension=ini.

    RocketLauncher reads Rom_Extension from [PCLauncher] when that section
    exists, ignoring the value in [Settings].  If [PCLauncher] has no
    Rom_Extension key, RL falls back to the global extension list
    (zip|rar|7z|...) and produces:

        Cannot find Rom <name> in any Rom_Paths provided:
            "...\\Modules\\PCLauncher\\Favorites"
        with any provided Rom_Extension: "zip|rar|7z|lha|lzh|gzip|tar|"

    even though [Settings] correctly sets Rom_Extension=ini.
    """
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)
    (rl / "Settings").mkdir(parents=True, exist_ok=True)

    store = FavoriteStore()
    add(store, "Super Nintendo", "Tetris")
    rebuild(store, cfg, media_mode=LinkMode.COPY)

    flat_ini = rl / "Settings" / "Favorites.ini"
    assert flat_ini.exists(), "Settings/Favorites.ini was not written"
    body = flat_ini.read_text(encoding="utf-8")

    assert "[PCLauncher]" in body, "[PCLauncher] section is missing"
    # Find the [PCLauncher] section and verify Rom_Extension=ini appears in it.
    # A simple substring check is sufficient because no other section would
    # contain that exact key-value pair.
    pclauncher_block = body.split("[PCLauncher]", 1)[1]
    assert "Rom_Extension=ini" in pclauncher_block, (
        "[PCLauncher] section is missing Rom_Extension=ini — RL will fall "
        "back to the global zip|rar|7z|... list and games will not launch."
    )


def test_rebuild_pclauncher_ini_uses_settings_format(isolated_config, tmp_path, monkeypatch):
    """Per-game PCLauncher INIs must use [Settings] format, not [exe info].

    [exe info] requires a fadetitle / monitored process; [Settings] just
    launches the exe and returns.  When RocketLauncher.exe is invoked with
    -p HyperSpin it handles the HyperSpin fade itself, so PCLauncher doesn't
    need to monitor anything — making [exe info] wrong for this use case.
    """
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    store = FavoriteStore()
    add(store, "Super Nintendo", "Tetris")
    rebuild(store, cfg, media_mode=LinkMode.COPY)

    ini_path = rl / "Modules" / "PCLauncher" / "Favorites" / "Tetris.ini"
    assert ini_path.exists()
    body = ini_path.read_text(encoding="utf-8")

    # Must use [Settings] section
    assert "[Settings]" in body
    # Must NOT use [exe info] (which requires FadeTitle)
    assert "[exe info]" not in body
    # Must point at RocketLauncher.exe with -p HyperSpin
    assert "RocketLauncher.exe" in body
    assert "-p HyperSpin" in body
    assert '-s "Super Nintendo"' in body
    assert '-r "Tetris"' in body


def test_rebuild_dry_run_shows_system_ini_path(isolated_config, tmp_path, monkeypatch):
    """Dry-run must show the system INI path that *would* be written.

    Previously showed 'skipped (rocketlauncher_dir not set or invalid)'
    even when rocketlauncher_dir was correctly configured, because the
    dry-run path returned early before the INI-write code.
    """
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    store = FavoriteStore()
    add(store, "Super Nintendo", "Tetris")

    from spindoctor.favorites import rebuild as fav_rebuild
    summary = fav_rebuild(store, cfg, media_mode=LinkMode.COPY, dry_run=True)

    # system_ini_path must be set (not None) so the CLI doesn't show
    # the misleading "skipped" message.
    assert summary.system_ini_path is not None
    assert "Favorites" in str(summary.system_ini_path)
    # Nothing must have been written to disk in dry-run mode.
    assert not (rl / "Settings" / "Favorites.ini").exists()


def test_rebuild_writes_hyperspin_settings_ini_when_missing(isolated_config, tmp_path, monkeypatch):
    """rebuild must write <hyperspin_dir>/Settings/Favorites.ini when absent.

    HyperSpin requires this file to open a sub-wheel.  Without it the wheel
    reports "Cannot find Favorites.ini" when the user selects it in the main
    menu.  The critical key is ``hyperlaunch=true`` in ``[exe info]``.
    """
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    store = FavoriteStore()
    add(store, "Super Nintendo", "Tetris")
    rebuild(store, cfg, media_mode=LinkMode.COPY)

    hs_ini = hs / "Settings" / "Favorites.ini"
    assert hs_ini.exists(), (
        "Settings/Favorites.ini was not written — HyperSpin will show "
        "'Cannot find Favorites.ini' when the wheel is selected."
    )
    body = hs_ini.read_text(encoding="utf-8")
    assert "[exe info]" in body
    assert "hyperlaunch=true" in body


def test_rebuild_preserves_existing_hyperspin_settings_ini(isolated_config, tmp_path, monkeypatch):
    """rebuild must NOT overwrite Settings/<system>.ini when it already exists.

    User customisations (wheel layout, filter settings, etc.) must survive
    repeated rebuilds.
    """
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    # Pre-create a customised settings file.
    settings_dir = hs / "Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    custom_content = "[exe info]\nhyperlaunch=true\ncustom_option=preserved\n"
    (settings_dir / "Favorites.ini").write_text(custom_content, encoding="utf-8")

    store = FavoriteStore()
    add(store, "Super Nintendo", "Tetris")
    rebuild(store, cfg, media_mode=LinkMode.COPY)

    body = (settings_dir / "Favorites.ini").read_text(encoding="utf-8")
    assert "custom_option=preserved" in body, (
        "rebuild clobbered the user's Settings/Favorites.ini — "
        "it must only write the file when it is absent."
    )


# ── PCLauncher system-level INI ───────────────────────────────────────────────

def test_rebuild_writes_pclauncher_system_ini(isolated_config, tmp_path, monkeypatch):
    """rebuild must write Modules/PCLauncher/Favorites.ini with [game] sections.

    PCLauncher.ahk reads game configuration from the *system-level* INI file
    at Modules/PCLauncher/<SystemName>.ini, looking for [<game_name>] sections
    with Application=, Parameters=, WorkingFolder= keys.  Without this file
    PCLauncher throws "You have not set up <game> in RocketLauncherUI yet"
    even though per-game placeholder files exist in the subdirectory.

    The per-game files in Modules/PCLauncher/Favorites/<game>.ini are only
    used by RocketLauncher for ROM discovery; PCLauncher.ahk never reads their
    content.
    """
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    store = FavoriteStore()
    add(store, "Super Nintendo", "Tetris")
    add(store, "Sony Playstation", "Tetris")
    rebuild(store, cfg, media_mode=LinkMode.COPY)

    sys_ini = rl / "Modules" / "PCLauncher" / "Favorites.ini"
    assert sys_ini.exists(), (
        "Modules/PCLauncher/Favorites.ini was not written — "
        "PCLauncher.ahk will throw 'not set up in RocketLauncherUI' for every game."
    )
    body = sys_ini.read_text(encoding="utf-8")

    # Both games must have their own [game_name] section
    assert "[Tetris (Super Nintendo)]" in body
    assert "[Tetris (Sony Playstation)]" in body

    # Each section must have the correct PCLauncher keys (not ApplicationPath=)
    assert "Application=" in body
    assert "ApplicationPath=" not in body  # wrong key — PCLauncher ignores it

    # Must launch RocketLauncher recursively with the source system.
    # -p HyperSpin must NOT be present: RL#1 already owns the HyperSpin IPC
    # pipe; a second -p HyperSpin causes RL#2's startup to stall (double-fade)
    # and produces "error waiting for window ahk_pid XXXX" when RL#2 tries to
    # detect the emulator window.  Without it RL#2 runs standalone and exits
    # cleanly when the game ends, letting PCLauncher return to RL#1 normally.
    assert "RocketLauncher.exe" in body
    assert '-s "Super Nintendo"' in body
    assert '-s "Sony Playstation"' in body
    assert "-p HyperSpin" not in body

    # WorkingFolder must be set so RL runs from its own directory
    assert "WorkingFolder=" in body


def test_rebuild_pclauncher_system_ini_cross_system(isolated_config, tmp_path, monkeypatch):
    """Each game section must reference its own source system, not a shared one.

    btoads2play is a MAME game; its Parameters must say -s "MAME".
    A Super Nintendo game must say -s "Super Nintendo".  The system-level INI
    must not conflate games from different source systems.
    """
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    store = FavoriteStore()
    add(store, "Super Nintendo", "Tetris")
    add(store, "Sony Playstation", "Tetris")
    rebuild(store, cfg, media_mode=LinkMode.COPY)

    body = (rl / "Modules" / "PCLauncher" / "Favorites.ini").read_text(encoding="utf-8")

    # Verify each section has the correct source system in its Parameters line
    snes_block = body.split("[Tetris (Super Nintendo)]")[1].split("[")[0]
    psx_block  = body.split("[Tetris (Sony Playstation)]")[1].split("[")[0]

    assert '-s "Super Nintendo"' in snes_block
    assert '-s "Super Nintendo"' not in psx_block
    assert '-s "Sony Playstation"' in psx_block
    assert '-s "Sony Playstation"' not in snes_block


# ─── sync_native: XML favorite="1", pre-skip, progress + verbose ──────────────

def test_sync_native_picks_up_xml_favorite_attribute(isolated_config, tmp_path, monkeypatch):
    """A <game favorite="1"/> attribute in a system XML is synced."""
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    # Mark the SNES Tetris as a favorite via the HyperSpin XML attribute form.
    snes_xml = hs / "Databases" / "Super Nintendo" / "Super Nintendo.xml"
    snes_xml.write_text(
        "<menu>"
        "<game name=\"Tetris\" favorite=\"1\">"
        "<description>Tetris</description>"
        "</game></menu>",
        encoding="utf-8",
    )
    store = FavoriteStore()
    n, warns, notes = sync_native(store, cfg)
    assert warns == []
    assert store.find("Super Nintendo", "Tetris") is not None
    assert n == 1


def test_sync_native_skips_xml_parse_when_no_favorites(isolated_config, tmp_path, monkeypatch):
    """Consoles with no favorites must not trigger a full XML parse."""
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    # No favorites of any kind exist in _build_layout's XMLs.
    parsed: list[str] = []
    import spindoctor.favorites as fav_mod
    real_load = fav_mod.load_database

    def _spy(system_name, databases_dir):
        parsed.append(system_name)
        return real_load(system_name, databases_dir)

    monkeypatch.setattr(fav_mod, "load_database", _spy)
    store = FavoriteStore()
    n, warns, notes = sync_native(store, cfg)
    assert n == 0
    # The fast text pre-scan should have skipped every database parse.
    assert parsed == []


def test_sync_native_progress_and_verbose_callbacks(isolated_config, tmp_path, monkeypatch):
    """progress_cb fires once per console; verbose detail flows to log_cb."""
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)
    (hs / "Databases" / "Super Nintendo" / "Super Nintendo_Favorites.ini").write_text(
        "Tetris\n", encoding="utf-8",
    )

    seen: list[tuple[int, int, str]] = []
    logs: list[str] = []
    store = FavoriteStore()
    n, warns, notes = sync_native(
        store, cfg,
        progress_cb=lambda i, total, s: seen.append((i, total, s)),
        log_cb=logs.append,
        verbose=True,
    )
    assert n == 1
    # Two source systems → two progress ticks, each numbered against the total.
    assert [s for _, _, s in seen] == ["Sony Playstation", "Super Nintendo"]
    assert all(total == 2 for _, total, _ in seen)
    # Verbose detail mentions the console that contributed a favorite.
    assert any("Super Nintendo" in line and "+1" in line for line in logs)


def test_sync_native_log_cb_silent_without_verbose(isolated_config, tmp_path, monkeypatch):
    """log_cb is only invoked when verbose=True."""
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)
    logs: list[str] = []
    sync_native(FavoriteStore(), cfg, log_cb=logs.append, verbose=False)
    assert logs == []


def test_rebuild_caches_source_db_loads(isolated_config, tmp_path, monkeypatch):
    """Many favorites from one system parse that source DB only once."""
    roms, hs, rl = _build_layout(tmp_path)
    monkeypatch.setattr("spindoctor.favorites.FAVORITES_FILE",
                        isolated_config / "favorites.json")
    cfg = _cfg(roms, hs, rl)

    # Two SNES games so the rebuild loop visits "Super Nintendo" twice.
    snes_xml = hs / "Databases" / "Super Nintendo" / "Super Nintendo.xml"
    snes_xml.write_text(
        "<menu>"
        "<game name=\"Tetris\"><description>Tetris</description></game>"
        "<game name=\"Mario\"><description>Mario</description></game>"
        "</menu>",
        encoding="utf-8",
    )

    loads: list[str] = []
    import spindoctor.favorites as fav_mod
    real_load = fav_mod.load_database

    def _spy(system_name, databases_dir):
        loads.append(system_name)
        return real_load(system_name, databases_dir)

    monkeypatch.setattr(fav_mod, "load_database", _spy)
    store = FavoriteStore()
    add(store, "Super Nintendo", "Tetris")
    add(store, "Super Nintendo", "Mario")
    rebuild(store, cfg, media_mode=LinkMode.COPY)

    assert loads.count("Super Nintendo") == 1


def test_standalone_rebuild_media_mode_defaults_to_auto():
    """Boot-time refreshes must hardlink by default (match the CLI + docs).

    The standalone parser previously defaulted to `copy`, so `.bat`/startup
    refreshes duplicated media where the full CLI hardlinked.
    """
    from spindoctor.favorites import _build_parser
    args = _build_parser().parse_args(["rebuild"])
    assert args.media_mode == "auto"


def test_generate_pclauncher_ini_sanitizes_filename(tmp_path):
    """A game name with a Windows-forbidden char must not crash the INI write:
    the filename is sanitized (the launch params keep the raw source name)."""
    from spindoctor.favorites import _generate_pclauncher_ini

    rl = tmp_path / "RocketLauncher"
    ini = _generate_pclauncher_ini(
        rl, "Favorites", "Submachine: Legacy", "PC Games", "Submachine Legacy",
    )
    assert ini.name == "Submachine Legacy.ini"  # colon stripped from filename
    assert ini.exists()
    assert "Submachine Legacy" in ini.read_text(encoding="utf-8")
