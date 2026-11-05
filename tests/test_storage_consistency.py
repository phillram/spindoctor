"""Regression coverage for legacy text edits and shared backup discovery."""
from pathlib import Path

import pytest
from click.testing import CliRunner

from spindoctor import ledblinky as lb, ledblinky_library as library
from spindoctor._text import read_editable_text, write_windows_text
from spindoctor.backup import find_sidecars
from spindoctor.config import Config
from spindoctor.ledblinky_profiles import ProfileBuilder
from spindoctor.preview import _resolve_paths


ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "utf-16", "utf-16-be")


def _encode(text, encoding):
    data = text.encode(encoding, errors="surrogateescape")
    return b"\xfe\xff" + data if encoding == "utf-16-be" else data


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_settings_edit_preserves_encoding_bom_newlines_and_comments(tmp_path, encoding):
    path = tmp_path / "Settings.ini"
    text = "; café\r\n[GameOptions]\r\nGamePlayLWAFile=Random.lwa\r\n\r\n[Other]\r\nx=1"
    path.write_bytes(_encode(text, encoding))
    lb.patch_ledblinky_settings(Config(ledblinky_dir=str(tmp_path)), dry_run=False, backup=False)
    assert path.read_bytes() == _encode(text.replace("=Random.lwa", "="), encoding)


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_color_rename_preserves_palette_comments_and_unrelated_sections(tmp_path, encoding):
    palette = "; café\r\n[Colors]\r\n; palette note\r\nRed = 48,0,0\r\n\r\n[Extra]\r\nx=keep\r\n"
    colors = "; café\r\n[game]\r\nP1_BUTTON1=Red\r\n\r\n; do not touch\r\n"
    xml = '<root><!-- café --><control color="Red"/></root>\r\n'
    for name, text in ((lb.COLOR_RGB_NAME, palette), (lb.COLORS_INI_NAME, colors),
                       (lb.CONTROLS_XML_NAME, xml)):
        (tmp_path / name).write_bytes(_encode(text, encoding))
    lb.apply_color_rename(Config(ledblinky_dir=str(tmp_path)), "Red", "Ruby",
                          dry_run=False, backup=False)
    assert (tmp_path / lb.COLOR_RGB_NAME).read_bytes() == _encode(palette.replace("Red =", "Ruby ="), encoding)
    assert (tmp_path / lb.COLORS_INI_NAME).read_bytes() == _encode(colors.replace("=Red", "=Ruby"), encoding)
    assert (tmp_path / lb.CONTROLS_XML_NAME).read_bytes() == _encode(xml.replace('"Red"', '"Ruby"'), encoding)


def test_edit_preserves_undefined_ansi_bytes(tmp_path):
    path = tmp_path / "Settings.ini"
    before = b"; caf\xe9 \x81\r\n[GameOptions]\r\nGamePlayLWAFile=Random.lwa\r\n"
    path.write_bytes(before)
    lb.patch_ledblinky_settings(Config(ledblinky_dir=str(tmp_path)), dry_run=False, backup=False)
    assert path.read_bytes() == before.replace(b"=Random.lwa", b"=")


def test_atomic_edit_failure_leaves_live_bytes_and_no_temp_files(tmp_path, monkeypatch):
    import spindoctor._utils as utils

    path = tmp_path / "Settings.ini"
    path.write_bytes(b"original")

    def fail_replace(*args):
        raise OSError("locked")

    monkeypatch.setattr(utils.os, "replace", fail_replace)
    with pytest.raises(OSError, match="locked"):
        write_windows_text(path, "changed")
    assert path.read_bytes() == b"original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Settings.ini"]


@pytest.mark.parametrize("operation", ("remove", "replace"))
def test_library_keeps_section_boundary_comment_banners(operation):
    text = "[a]\r\nx=1\r\n\r\n; Next category\r\n# keep this too\r\n\r\n[b]\r\ny=2\r\n"
    raw = library.RawIni(text)
    assert raw.render() == text
    result = raw.render(**({"remove": ["a"]} if operation == "remove"
                           else {"replace": {"a": "[a]\r\nx=3\r\n"}}))
    assert "\r\n; Next category\r\n# keep this too\r\n\r\n[b]\r\ny=2\r\n" in result
    assert result.count("Next category") == 1
    assert "Next category" not in raw.entries()["a"]


@pytest.mark.parametrize("encoding", ("utf-16", "utf-16-be"))
def test_library_roundtrips_utf16_live_files(tmp_path, encoding):
    path = tmp_path / "Controls.ini"
    text = "; café\r\n[a]\r\nx=1\r\n"
    path.write_bytes(_encode(text, encoding))
    raw = library.RawIni.load(path)
    library.write_raw(path, raw.render())
    assert path.read_bytes() == _encode(text, encoding)


def test_profile_rewrite_keeps_comments_and_existing_line_endings(tmp_path):
    path = tmp_path / "Controls.ini"
    path.write_bytes(b"; caf\xe9\r\n[a]\r\n; custom note\r\nx=1\r\n\r\n; Next category\r\n[b]\r\ny=2\r\n")
    builder = object.__new__(ProfileBuilder)
    text = builder._rewrite_ini(path, {"a": {"x": "3"}})
    write_windows_text(path, text)
    assert b"; caf\xe9\r\n[a]\r\n; custom note\r\nx=3\r\n" in path.read_bytes()
    assert b"; Next category\r\n[b]\r\ny=2\r\n" in path.read_bytes()


def test_hook_patch_preserves_crlf_and_missing_final_newline():
    text = "; café\r\n[Main]\r\nStart_Hyperspin_Process=LEDBlinky.exe\r\nuntouched=1"
    result, changed = lb._comment_out_hooks(text)
    assert changed == 1
    assert result == text.replace("Start_Hyperspin_Process=LEDBlinky.exe",
                                 ";Start_Hyperspin_Process=LEDBlinky.exe  " + lb.LEDBLINKY_DISABLE_TAG)
    assert lb._comment_out_hooks(result) == (result, 0)


def test_stub_xml_preserves_comments_processing_instructions_and_encoding(tmp_path):
    path = tmp_path / lb.CONTROLS_XML_NAME
    text = '<?xml version="1.0" encoding="UTF-16"?>\r\n<EmulatorList><!-- café --><?custom keep?></EmulatorList>'
    path.write_bytes(text.encode("utf-16"))
    assert lb._ensure_controls_xml_entries(path, path, ["Search"]) == (True, ["Search"])
    result = read_editable_text(path)
    assert "<!-- café -->" in result
    assert "<?custom keep?>" in result
    assert path.read_bytes().startswith(b"\xff\xfe")


@pytest.mark.parametrize("name, stem", (("Game: Deluxe?", "Game Deluxe"), ("CON", "CON_")))
def test_preview_uses_shared_windows_safe_media_stem(tmp_path, name, stem):
    for directory, extension in (("Images/Wheel", ".png"), ("Images/Artwork1", ".jpg"),
                                 ("Video", ".mp4")):
        parent = tmp_path / directory
        parent.mkdir(parents=True)
        (parent / (stem + extension)).write_bytes(b"media")
    theme = tmp_path / "Themes" / stem
    theme.mkdir(parents=True)
    paths = _resolve_paths(tmp_path, name)
    assert paths["wheel"].name == stem + ".png"
    assert paths["artwork"].name == stem + ".jpg"
    assert paths["video"].name == stem + ".mp4"
    assert paths["theme"] == theme


def test_preview_does_not_select_directories_as_image_files_or_empty_theme(tmp_path):
    (tmp_path / "Images/Wheel/game.png").mkdir(parents=True)
    (tmp_path / "Themes").mkdir()
    assert _resolve_paths(tmp_path, "game")["wheel"] is None
    assert all(p is None for p in _resolve_paths(tmp_path, "../:*?").values())


def test_sidecar_cli_discovers_both_names_and_configured_backup_tree(tmp_path, monkeypatch):
    import spindoctor.cli as cli_module
    import json

    led = tmp_path / "led"
    led.mkdir()
    target = led / "Controls.ini"
    target.write_bytes(b"live")
    backup_root = tmp_path / "backups"
    central = backup_root / "LEDBlinky"
    central.mkdir(parents=True)
    newest = central / "controls.ini.20260101_120000_10.bak"
    newest.write_bytes(b"new")
    older = led / "Controls.20260101_120000_2.bak"
    older.write_bytes(b"old")
    (led / "Controls.20270101_120000.bak").mkdir()
    config = Config(ledblinky_dir=str(led), backup_dir=str(backup_root))
    monkeypatch.setattr(cli_module, "_cfg", lambda: config)
    assert find_sidecars(target, config) == [newest, older]
    result = CliRunner().invoke(cli_module.cli, ["backup", "sidecar", "list", str(target), "--json"])
    assert result.exit_code == 0, result.output
    assert [Path(entry["path"]) for entry in json.loads(result.output)] == [newest, older]
    result = CliRunner().invoke(cli_module.cli, ["backup", "sidecar", "restore", str(target),
                                                "--from", str(newest), "--apply"])
    assert result.exit_code == 0, result.output
    assert target.read_bytes() == b"new"


def test_sidecars_follow_rocketlauncher_nested_backup_layout(tmp_path):
    rl = tmp_path / "rl"
    target = rl / "Settings" / "MAME" / "Emulators.ini"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"live")
    central = tmp_path / "backups" / "RocketLauncher"
    (central / "Settings" / "MAME").mkdir(parents=True)
    (central / "Settings" / "NES").mkdir(parents=True)
    own = central / "Settings" / "MAME" / "Emulators.ini.20260101_120000.bak"
    own.write_bytes(b"own")
    (central / "Settings" / "NES" / "Emulators.ini.20260102_120000.bak").write_bytes(b"other")
    config = Config(rocketlauncher_dir=str(rl), backup_dir=str(tmp_path / "backups"))
    assert find_sidecars(target, config) == [own]


def test_community_discovery_uses_numeric_oldest_and_checks_content(tmp_path):
    for counter, content in ((10, "P1NumButtons=10"), (2, "P1NumButtons=2"), (1, "unrelated")):
        (tmp_path / f"controls.ini.20260101_120000_{counter}.bak").write_bytes(content.encode())
    assert library.find_community_controls(tmp_path).name.endswith("_2.bak")
