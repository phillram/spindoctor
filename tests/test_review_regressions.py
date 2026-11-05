"""Regression coverage for the whole-project correctness and simplicity review."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from spindoctor import backup, cache, cleanup, config, database, migrate, organize
from spindoctor import audit, curate, edit, favorites, fileinfo, media_scan, medialink
from spindoctor import misplaced, recent, rocketlauncher, scraper, themes


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


def test_restore_uses_selected_backup_not_original_location(tmp_path):
    src = tmp_path / "live"
    touch(src / "game.zip")
    cfg = config.Config(roms_dir=str(src))
    original = backup.apply_backup(backup.plan_backup(cfg, tmp_path / "backups", ["roms"]), cfg)
    relocated = tmp_path / "relocated"
    shutil.copytree(original, relocated)
    touch(original / "Games" / "game.zip", b"stale")
    plan = backup.plan_restore(relocated)
    assert Path(plan.items[0].src) == relocated / "Games"
    shutil.rmtree(src)
    backup.apply_restore(plan)
    assert (src / "game.zip").read_bytes() == b"original"


@pytest.mark.parametrize("operation", ["backup", "migration"])
def test_planning_rejects_destination_inside_source(tmp_path, operation):
    src = tmp_path / "live"
    touch(src / "game.zip")
    cfg = config.Config(roms_dir=str(src))
    if operation == "backup":
        plan = backup.plan_backup(cfg, src / "backups", ["roms"])
    else:
        plan = migrate.plan_migration(cfg, src / "new", ["roms"])
    assert plan.empty
    assert plan.skipped
    assert not (src / "new").exists()
    assert not (src / "backups").exists()


def test_settings_backup_excludes_runtime_lock(tmp_path):
    touch(backup.CONFIG_DIR / "gui.lock", b"locked")
    touch(backup.CONFIG_DIR / "config.json", b"{}")
    cfg = config.Config()
    root = backup.apply_backup(backup.plan_backup(cfg, tmp_path / "backups", ["settings"]), cfg)
    assert not (root / "Settings" / "gui.lock").exists()
    assert (root / "Settings" / "config.json").exists()


def test_settings_restore_does_not_delete_live_lock(tmp_path, monkeypatch):
    source = tmp_path / "saved"
    touch(source / "config.json", b'{"new":true}')
    touch(source / "gui.lock", b"obsolete lock")
    live_lock = touch(backup.CONFIG_DIR / "gui.lock", b"active lock")
    touch(backup.CONFIG_DIR / "config.json", b"{}")
    real_rmtree = shutil.rmtree

    def guarded_rmtree(path, *args, **kwargs):
        assert Path(path) != backup.CONFIG_DIR
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", guarded_rmtree)
    plan = backup.RestorePlan(str(tmp_path), [
        backup.RestoreItem("settings", str(source), str(backup.CONFIG_DIR)),
    ])
    assert backup.apply_restore(plan, overwrite=True) == 1
    assert live_lock.read_bytes() == b"active lock"
    assert json.loads((backup.CONFIG_DIR / "config.json").read_text()) == {"new": True}


def test_migration_verification_detects_missing_copy(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    touch(source / "missing.zip")
    target.mkdir()
    assert migrate._verify_tree(source, target)


@pytest.mark.parametrize("kind", ["migration", "organize", "misplaced", "curate", "import"])
def test_undo_keeps_conflicting_files_and_recovery_record(tmp_path, kind):
    original = touch(tmp_path / "original.zip", b"new user data")
    moved = touch(tmp_path / "moved.zip", b"archived data")
    entry = {"src": str(original), "dest": str(moved)}
    payload = {"moves": [entry]}
    if kind == "migration":
        entry["component"] = "roms"
        undo = migrate.undo_migration
    elif kind == "organize":
        undo = organize.undo_restructure
    elif kind == "misplaced":
        undo = misplaced.undo_moves
    elif kind == "curate":
        undo = curate.undo_curation
    else:
        entry["action"] = "move"
        payload = {"imports": [entry]}
        undo = media_scan.undo_import
    manifest = touch(tmp_path / "manifest.json", json.dumps(payload).encode())
    result = undo(manifest)
    assert result["errors"]
    assert original.read_bytes() == b"new user data"
    assert moved.read_bytes() == b"archived data"
    assert manifest.exists()
    original.unlink()
    result = undo(manifest)
    assert not result["errors"]
    assert original.read_bytes() == b"archived data"
    assert not manifest.exists()


def test_organize_does_not_move_its_own_manifest(tmp_path):
    folder = tmp_path / "Sony Playstation 3"
    touch(folder / "Game.iso")
    manifest = organize.apply_restructure(organize.plan_restructure(folder.name, tmp_path))
    plan = organize.plan_restructure(folder.name, tmp_path)
    assert plan.empty
    assert manifest.exists()


def test_organize_counts_discs_not_bin_cue_files(tmp_path):
    folder = tmp_path / "Sega Saturn"
    for ext in (".bin", ".cue"):
        touch(folder / f"Game (Disc 1){ext}")
    assert organize.plan_restructure(folder.name, tmp_path).empty
    for ext in (".bin", ".cue"):
        touch(folder / f"Game (Disc 2){ext}")
    plan = organize.plan_restructure(folder.name, tmp_path)
    assert len(plan.moves) == 4
    assert plan.creates[0].content.splitlines() == ["Game (Disc 1).cue", "Game (Disc 2).cue"]


@pytest.mark.parametrize("exception", [OSError, KeyboardInterrupt])
def test_organize_interruption_keeps_partial_undo(tmp_path, monkeypatch, exception):
    folder = tmp_path / "Sony Playstation 3"
    touch(folder / "A.iso")
    touch(folder / "B.iso")
    plan = organize.plan_restructure(folder.name, tmp_path)
    real_move = shutil.move
    calls = []

    def interrupted(src, dest, *args, **kwargs):
        if calls:
            raise exception("interrupted")
        calls.append(src)
        return real_move(src, dest, *args, **kwargs)

    monkeypatch.setattr(shutil, "move", interrupted)
    with pytest.raises(exception):
        organize.apply_restructure(plan)
    manifests = list(folder.glob("_spindoctor-restructure-*.json"))
    assert len(manifests) == 1
    assert len(json.loads(manifests[0].read_text())["moves"]) == 1


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


def test_two_migrations_keep_distinct_manifests(tmp_path, monkeypatch):
    freeze_time(monkeypatch, migrate)
    plan = migrate.MigrationPlan(str(tmp_path))
    first = migrate.apply_migration(plan)
    second = migrate.apply_migration(plan)
    assert first != second
    assert first.exists() and second.exists()


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


def test_fade_discovery_and_safe_media_names(tmp_path):
    name = "Metal Gear: VR"
    stem = "Metal Gear VR"
    media = tmp_path / "Media"
    touch(media / "MAME" / "Images" / "Artwork4" / f"{stem}.png")
    assert audit.check_media(name, "MAME", media).fade
    assert fileinfo.find_media_file(name, "MAME", "fade", media).exists
    assert medialink.remove_target(media, "MAME", name) == 1


@pytest.mark.parametrize("builder", ["favorites", "recent"])
def test_wheel_rebuild_preserves_theme_contents_and_system_media(tmp_path, builder):
    hs = tmp_path / "hs"
    source = "SNES"
    target = "Favorites" if builder == "favorites" else "Recently Played"
    touch(hs / "Databases" / source / f"{source}.xml", b'<menu><game name="Tetris"/></menu>')
    media = hs / "Media"
    touch(media / source / "Themes" / "Tetris" / "Theme.xml")
    touch(media / source / "Themes" / "Tetris" / "bg.png")
    protected = [
        touch(media / target / "Themes" / "default.zip", b"custom theme"),
        touch(media / target / "Sound" / "Wheel Click.mp3", b"custom click"),
        touch(media / target / "Images" / "Letters" / "A.png", b"letter"),
    ]
    stale = touch(media / target / "Images" / "Wheel" / "Removed.png")
    cfg = config.Config(hyperspin_dir=str(hs))
    entry = favorites.FavoriteEntry(source, "Tetris", "Tetris", "")
    for _ in range(2):
        if builder == "favorites":
            favorites.rebuild(favorites.FavoriteStore([entry], target), cfg, skip_launchers=True)
        else:
            recent._build_synthetic_wheel(cfg, target, [entry], skip_launchers=True)
    assert (media / target / "Themes" / "Tetris" / "Theme.xml").exists()
    assert (media / target / "Themes" / "Tetris" / "bg.png").exists()
    assert [p.read_bytes() for p in protected] == [b"custom theme", b"custom click", b"letter"]
    assert not stale.exists()


@pytest.mark.parametrize("name", ["", " ", "..", "../MAME", "MAME/child", "C:\\MAME"])
def test_clear_wheel_rejects_invalid_target(tmp_path, name):
    cfg = config.Config(hyperspin_dir=str(tmp_path))
    with pytest.raises(ValueError):
        recent.clear_wheel_artifacts(cfg, name, dry_run=True)


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


def test_theme_pack_roundtrip_respects_scope(tmp_path):
    hs = tmp_path / "hs"
    paths = {}
    for system in ("MAME", "NES"):
        paths[system] = touch(hs / "Media" / system / "Images" / "Special A" / "same.png",
                              system.encode())
    cfg = config.Config(hyperspin_dir=str(hs))
    pack = tmp_path / "pack"
    themes.create_pack(cfg, pack)
    for path in paths.values():
        path.write_bytes(b"changed")
    plans = themes.plan_apply(cfg, pack)
    themes.apply_plan(plans, manifest_dir=tmp_path / "undo")
    for system, path in paths.items():
        assert path.read_bytes() == system.encode()


def test_fuzzy_match_short_circuits_first_normalized_exact_match(monkeypatch):
    from spindoctor import romutils
    def fail(*args, **kwargs):
        pytest.fail("an exact match should not need fuzzy scoring")
    monkeypatch.setattr(romutils, "SequenceMatcher", fail)
    assert romutils.find_best_match("Mario", ["Mario (USA)", "Mario"]) == ("Mario (USA)", 1.0)


def test_import_matching_indexes_exact_names_and_reuses_repeated_stems(tmp_path, monkeypatch):
    hs = tmp_path / "hs"
    touch(hs / "Databases" / "NES" / "NES.xml", b'<menu><game name="Mario (USA)"/></menu>')
    source = tmp_path / "pack"
    touch(source / "Wheels" / "Mario.png")
    touch(source / "Snaps" / "Mario.png")
    def fail(*args, **kwargs):
        pytest.fail("normalized exact matches should use the precomputed index")
    monkeypatch.setattr(media_scan, "find_best_match", fail)
    report = media_scan.match_to_database(media_scan.scan_local_media(source), "NES",
                                          config.Config(hyperspin_dir=str(hs)))
    assert len(report.matched) == 2
    assert all(m.game_name == "Mario (USA)" for m in report.matched)


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


def test_undo_retry_does_not_replay_already_completed_moves(tmp_path):
    first_src, first_dest = tmp_path / "one.zip", touch(tmp_path / "moved-one.zip")
    second_src = touch(tmp_path / "two.zip", b"conflicting")
    second_dest = touch(tmp_path / "moved-two.zip")
    manifest = touch(tmp_path / "undo.json", json.dumps({"moves": [
        {"src": str(first_src), "dest": str(first_dest)},
        {"src": str(second_src), "dest": str(second_dest)},
    ]}).encode())
    summary = misplaced.undo_moves(manifest)
    assert summary["reverted"] == 1 and summary["errors"]
    assert len(json.loads(manifest.read_text())["moves"]) == 1
    second_src.unlink()
    assert misplaced.undo_moves(manifest) == {"reverted": 1, "errors": []}
    assert first_src.exists() and second_src.exists() and not manifest.exists()


def test_orphan_media_keeps_sanitized_names_and_system_assets(tmp_path):
    from spindoctor import orphan_media
    hs = tmp_path / "hs"
    touch(hs / "Databases" / "PC" / "PC.xml", b'<menu><game name="Game: Test"/></menu>')
    media = hs / "Media" / "PC"
    touch(media / "Images" / "Wheel" / "Game Test.png")
    touch(media / "Images" / "Artwork4" / "game test.png")
    touch(media / "Sound" / "Wheel Click.mp3")
    touch(media / "Themes" / "default.zip")
    stale = touch(media / "Themes" / "Removed.zip")
    report = orphan_media.find_orphan_media("PC", config.Config(hyperspin_dir=str(hs)))
    assert [o.path for o in report.orphans] == [stale]


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


def test_backup_apply_rejects_hand_built_nested_plan(tmp_path):
    src = tmp_path / "live"
    touch(src / "game.zip")
    root = src / "backup"
    plan = backup.BackupPlan(str(root), [
        backup.BackupItem("roms", str(src), str(root / "Games")),
    ])
    with pytest.raises(ValueError, match="inside its source"):
        backup.apply_backup(plan, config.Config())
    assert not root.exists()


def test_restore_rechecks_sources_before_removing_destination(tmp_path):
    live = touch(tmp_path / "live" / "valuable", b"keep")
    plan = backup.RestorePlan(str(tmp_path / "backup"), [
        backup.RestoreItem("roms", str(tmp_path / "missing"), str(live.parent)),
    ])
    with pytest.raises(FileNotFoundError):
        backup.apply_restore(plan, overwrite=True)
    assert live.read_bytes() == b"keep"


def test_old_backup_settings_locks_are_never_restored(tmp_path):
    saved = tmp_path / "backup"
    touch(saved / "config.json", b"{}")
    touch(saved / "gui.lock")
    live = tmp_path / "live"
    plan = backup.RestorePlan(str(saved), [
        backup.RestoreItem("settings", str(saved), str(live)),
    ])
    assert backup.apply_restore(plan) == 1
    assert (live / "config.json").exists()
    assert not (live / "gui.lock").exists()


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


def test_organize_partial_undo_never_deletes_recreated_playlist(tmp_path):
    original = touch(tmp_path / "original.iso", b"conflicting")
    moved = touch(tmp_path / "organized" / "disc.iso")
    playlist = touch(moved.parent / "game.m3u")
    payload = {
        "moves": [{"src": str(original), "dest": str(moved)}],
        "creates": [{"path": str(playlist), "content": "disc.iso\n"}],
    }
    manifest = touch(tmp_path / "manifest.json", json.dumps(payload).encode())
    assert organize.undo_restructure(manifest)["errors"]
    assert not playlist.exists()
    assert json.loads(manifest.read_text())["creates"] == []
    touch(playlist, b"new user playlist")
    original.unlink()
    assert not organize.undo_restructure(manifest)["errors"]
    assert playlist.read_bytes() == b"new user playlist"


def test_latest_manifest_uses_numeric_same_second_counter(tmp_path, monkeypatch):
    freeze_time(monkeypatch, migrate)
    plan = migrate.MigrationPlan(str(tmp_path))
    manifests = [migrate.apply_migration(plan) for _ in range(12)]
    assert migrate.list_manifests() == manifests
    assert migrate.find_latest_manifest() == manifests[-1]


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
