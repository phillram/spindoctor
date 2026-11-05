"""Regression coverage for the whole-project correctness and simplicity review."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from spindoctor import backup, cache, cleanup, config, database, migrate
from spindoctor import edit
from spindoctor import rocketlauncher, scraper


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config, "CONFIG_DIR", home)
    monkeypatch.setattr(config, "CONFIG_FILE", home / "config.json")
    monkeypatch.setattr(backup, "CONFIG_DIR", home)
    monkeypatch.setattr(cleanup, "CONFIG_DIR", home)
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", home / "migrations")
    config.reset_override_cache()
    yield
    config.reset_override_cache()


def touch(path, data=b"original"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def freeze_time(monkeypatch, *modules):
    class Frozen:
        @classmethod
        def now(cls):
            return datetime(2026, 11, 4, 12, 0, 0)
    for module in modules:
        monkeypatch.setattr(module, "datetime", Frozen)


def test_two_database_saves_keep_original_backup(tmp_path, monkeypatch):
    freeze_time(monkeypatch, database)
    path = touch(tmp_path / "MAME.xml", b'<menu><game name="A"/></menu>')
    original = path.read_bytes()
    db = database.HyperspinDatabase("MAME", path)
    db.upsert_game(database.GameEntry("B"))
    db.save()
    db.upsert_game(database.GameEntry("C"))
    db.save()
    backups = sorted(tmp_path.glob("*.bak"))
    assert len(backups) == 2
    assert backups[0].read_bytes() == original


def test_atomic_write_handles_short_os_writes(tmp_path, monkeypatch):
    import os
    real_write = os.write
    monkeypatch.setattr(os, "write", lambda fd, data: real_write(fd, data[:3]))
    path = tmp_path / "data.xml"
    database._atomic_write_bytes(path, b"complete document")
    assert path.read_bytes() == b"complete document"


@pytest.mark.parametrize("value", [[], None, 12, {"game": []}])
def test_shared_cache_rejects_wrong_json_shape(tmp_path, value):
    touch(tmp_path / "MAME.json", json.dumps(value).encode())
    assert cache.load(tmp_path, "MAME") == {}
    assert cache.list_all(tmp_path) == {}


def test_metadata_cache_does_not_collide(tmp_path):
    c = scraper.MetadataCache(root=tmp_path)
    names = ["忍者", "将棋", "A" * 170 + "1", "A" * 170 + "2", "a:b", "a?b"]
    for name in names:
        c.put("screenscraper", "MAME", name, [scraper.GameMetadata(name=name)])
    for name in names:
        assert c.get("screenscraper", "MAME", name)[0].name == name


@pytest.mark.parametrize("value", [[], None, {"results": [{}]}, {"cached_at": []}])
def test_metadata_cache_treats_wrong_schema_as_miss(tmp_path, value):
    c = scraper.MetadataCache(root=tmp_path)
    path = c._path("screenscraper", "MAME", "A")
    touch(path, json.dumps(value).encode())
    assert c.get("screenscraper", "MAME", "A") is None


def test_rename_matches_literal_rom_stem(tmp_path):
    name = "Tetris [T+Fre]"
    hs = tmp_path / "hs"
    touch(hs / "Databases" / "SNES" / "SNES.xml",
          f'<menu><game name="{name}"/></menu>'.encode())
    roms = tmp_path / "roms"
    touch(roms / "SNES" / f"{name}.zip")
    touch(roms / "SNES" / f"{name}.Extra.zip")
    cfg = config.Config(hyperspin_dir=str(hs), roms_dir=str(roms))
    plan = edit.plan_rename(cfg, "SNES", name, "New name")
    rom_changes = [c for c in plan.file_changes if c.kind == "rom"]
    assert len(rom_changes) == 1
    assert rom_changes[0].src.name == f"{name}.zip"


@pytest.mark.parametrize("encoding", ["cp1252", "utf-16", "utf-8-sig"])
def test_ini_rom_path_update_preserves_encoding(tmp_path, encoding):
    path = touch(tmp_path / "Emulators.ini",
                 "[ROMS]\r\nRom_Path=old\r\n; Émulateurs\r\n".encode(encoding))
    assert rocketlauncher._update_rom_path_in_ini(path, "new")
    assert path.read_bytes().decode(encoding) == "[ROMS]\r\nRom_Path=new\r\n; Émulateurs\r\n"


def test_cached_direct_match_is_reconsidered_at_higher_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "get_game_override", lambda *args: {})
    class Client(scraper._FetchWithSearchMixin):
        source_name = "test"
        _cache = scraper.MetadataCache(root=tmp_path)
        searches = 0

        def fetch(self, *args):
            return scraper.GameMetadata(name="near", source_id="1", match_score=.81)

        def search(self, *args):
            self.searches += 1
            return [scraper.GameMetadata(name="best", source_id="2", match_score=.99)]

    client = Client()
    assert client.fetch_with_search("game", "system", .8)[0].name == "near"
    assert client.fetch_with_search("game", "system", .95)[0].name == "best"
    assert client.searches == 1


def test_legacy_metadata_cache_requires_original_identity(tmp_path):
    from dataclasses import asdict
    c = scraper.MetadataCache(root=tmp_path)
    legacy = tmp_path / "screenscraper" / "MAME" / "_.json"
    payload = {
        "cached_at": datetime.now().isoformat(), "source": "screenscraper", "system": "MAME",
        "rom_stem": "忍者", "results": [asdict(scraper.GameMetadata(name="Ninja"))],
    }
    touch(legacy, json.dumps(payload).encode())
    assert c.get("screenscraper", "MAME", "忍者")[0].name == "Ninja"
    assert c.get("screenscraper", "MAME", "将棋") is None


@pytest.mark.parametrize("encoding", ["cp1252", "utf-16", "utf-16-be", "utf-8-sig"])
def test_pclauncher_edits_preserve_non_ascii_text(tmp_path, encoding):
    text = "[Game]\r\nApplication=old\r\nWorkingFolder=old\r\n; Émulateurs\r\n"
    if encoding == "utf-16-be":
        text = "\ufeff" + text
    path = touch(tmp_path / "PC.ini", text.encode(encoding))
    rocketlauncher.rewrite_pclauncher_application(path, "Game", Path("new/game.exe"))
    saved = path.read_bytes().decode(encoding)
    assert "; Émulateurs\r\n" in saved
    assert saved.startswith("\ufeff[Game]" if encoding == "utf-16-be" else "[Game]")
    assert saved.count("[Game]") == 1
    assert "Application=new" in saved


def test_config_invalid_encoding_is_recovered_without_losing_original():
    original = b'{"roms_dir":"\xff"}'
    config.CONFIG_FILE.write_bytes(original)
    assert isinstance(config.load_config(), config.Config)
    assert config.CONFIG_FILE.read_bytes() == original
    assert list(config.CONFIG_DIR.glob("*.corrupt-*.json"))


def test_empty_valid_cache_remains_visible_in_listing(tmp_path):
    cache.save(tmp_path, "Empty", {})
    assert cache.list_all(tmp_path) == {"Empty": {}}
    assert cache.list_all(tmp_path, "Empty") == {"Empty": {}}


def test_atomic_cleanup_does_not_hide_original_failure(tmp_path, monkeypatch):
    from spindoctor import _utils
    target = touch(tmp_path / "document", b"original")
    def replace(*args):
        raise OSError("original replace failure")
    def unlink(*args):
        raise PermissionError("cleanup failure")
    monkeypatch.setattr(_utils.os, "replace", replace)
    monkeypatch.setattr(_utils.os, "unlink", unlink)
    with pytest.raises(OSError, match="original replace failure"):
        _utils.atomic_write_bytes(target, b"replacement")
    assert target.read_bytes() == b"original"


@pytest.mark.parametrize("clone", [False, True])
def test_rename_and_clone_preserve_custom_xml_attributes(tmp_path, clone):
    hs = tmp_path / "hs"
    touch(hs / "Databases" / "PC" / "PC.xml",
          b'<menu><game name="Old" exe="true" custom="value"><description>Game</description></game></menu>')
    cfg = config.Config(hyperspin_dir=str(hs), roms_dir=str(tmp_path / "roms"))
    plan = edit.plan_rename(cfg, "PC", "Old", "New", clone=clone)
    edit.apply_rename(plan, cfg, manifest_dir=tmp_path / "manifests")
    db = database.load_database("PC", cfg.databases_dir)
    assert db.get("New").extra_attrs == {"exe": "true", "custom": "value"}
    assert (db.get("Old") is not None) == clone


@pytest.mark.parametrize("clone", [False, True])
def test_rename_and_clone_use_safe_media_destinations(tmp_path, clone):
    hs = tmp_path / "hs"
    touch(hs / "Databases" / "PC" / "PC.xml", b'<menu><game name="Old"/></menu>')
    wheel = touch(hs / "Media" / "PC" / "Images" / "Wheel" / "Old.png")
    theme = touch(hs / "Media" / "PC" / "Themes" / "Old" / "Theme.xml")
    cfg = config.Config(hyperspin_dir=str(hs), roms_dir=str(tmp_path / "roms"))
    plan = edit.plan_rename(cfg, "PC", "Old", "New: Name", clone=clone)
    edit.apply_rename(plan, cfg, manifest_dir=tmp_path / "manifests")
    assert (wheel.parent / "New Name.png").exists()
    assert (theme.parent.parent / "New Name" / "Theme.xml").exists()
    assert database.load_database("PC", cfg.databases_dir).get("New: Name")


def test_rom_rename_preserves_windows_case_insensitivity(tmp_path, monkeypatch):
    hs = tmp_path / "hs"
    touch(hs / "Databases" / "Arcade" / "Arcade.xml", b'<menu><game name="Pacman"/></menu>')
    rom = touch(tmp_path / "roms" / "Arcade" / "pacman.zip")
    cfg = config.Config(hyperspin_dir=str(hs), roms_dir=str(tmp_path / "roms"))
    monkeypatch.setattr(edit.os.path, "normcase", lambda name: name.casefold())
    plan = edit.plan_rename(cfg, "Arcade", "Pacman", "New")
    assert [change.src for change in plan.file_changes if change.kind == "rom"] == [rom]


def test_undefined_ansi_bytes_are_lossless_for_edits_but_printable_in_diagnostics(tmp_path):
    original = b"[Game]\r\nApplication=old\r\n; unknown byte \x81\r\n"
    path = touch(tmp_path / "game.ini", original)
    assert "\ufffd" in rocketlauncher._read_windows_text(path)
    rocketlauncher._read_windows_text(path).encode("utf-8")
    rocketlauncher.rewrite_pclauncher_application(path, "Game", Path("new/game.exe"))
    assert b"; unknown byte \x81\r\n" in path.read_bytes()
