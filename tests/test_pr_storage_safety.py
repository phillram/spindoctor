"""Regressions found while checking the storage-safety PR."""
import json
from pathlib import Path

import pytest

from spindoctor import config, edit, lightgun, rocketlauncher


def cabinet(tmp_path):
    hs = tmp_path / "hs"
    db = hs / "Databases" / "PC" / "PC.xml"
    db.parent.mkdir(parents=True)
    db.write_text('<menu><game name="Foo: Bar"/><game name="Foo Bar"/></menu>')
    return config.Config(hyperspin_dir=str(hs), roms_dir=str(tmp_path / "roms"))


@pytest.mark.parametrize("kind", ["media", "rl-pclauncher"])
def test_clone_refuses_sanitized_filename_collision(tmp_path, kind):
    cfg = cabinet(tmp_path)
    db = Path(cfg.databases_dir) / "PC" / "PC.xml"
    db.write_text('<menu><game name="Foo: Bar"/></menu>')
    if kind == "media":
        path = cfg.media_dir / "PC" / "Images" / "Wheel" / "Foo Bar.png"
    else:
        cfg.rocketlauncher_dir = str(tmp_path / "rl")
        path = tmp_path / "rl" / "Modules" / "PCLauncher" / "PC" / "Foo Bar.ini"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"[Foo: Bar]\r\nApplication=game.exe\r\n")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="same file"):
        edit.plan_rename(cfg, "PC", "Foo: Bar", "Foo Bar", clone=True)
    assert path.read_bytes() == before


@pytest.mark.parametrize("directory", [False, True])
def test_legacy_clone_undo_never_deletes_original(tmp_path, directory):
    cfg = cabinet(tmp_path)
    path = tmp_path / "original"
    if directory:
        path.mkdir()
        (path / "data").write_bytes(b"original")
    else:
        path.write_bytes(b"original")
    manifest = tmp_path / "rename.json"
    manifest.write_text(json.dumps({
        "system": "PC", "old_name": "Foo: Bar", "new_name": "Foo Bar", "clone": True,
        "moves": [{"src": str(path), "dest": str(path), "kind": "media"}],
    }))
    edit.undo_rename(manifest, cfg)
    assert (path / "data" if directory else path).read_bytes() == b"original"


def test_config_read_failure_propagates_without_using_defaults(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text('{"roms_dir":"important"}')
    monkeypatch.setattr(config, "CONFIG_FILE", path)

    def denied(*args, **kwargs):
        raise PermissionError("sharing violation")

    monkeypatch.setattr("builtins.open", denied)
    with pytest.raises(PermissionError, match="sharing violation"):
        config.load_config()
    assert path.read_bytes() == b'{"roms_dir":"important"}'


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize("prefix", ["", "; comment{eol}Other=1{eol}"])
def test_lightgun_key_replacement_preserves_lines(eol, prefix):
    prefix = prefix.format(eol=eol)
    before = f"[Settings]{eol}{prefix}Pre_Launch_App=old{eol}[Next]{eol}Keep=1{eol}"
    expected = before.replace("Pre_Launch_App=old", "Pre_Launch_App=new")
    assert lightgun._upsert_ini_key(before, "Settings", "Pre_Launch_App", "new") == expected


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_damaged_utf16_is_readable_but_not_losslessly_editable(tmp_path, encoding):
    path = tmp_path / "Emulators.ini"
    content = ("\ufeff[ROMS]\r\nDefault_Emulator=MAME\r\n").encode(encoding) + b"x"
    path.write_bytes(content)
    assert rocketlauncher._read_rl_ini(path)["roms"]["default_emulator"] == "MAME"
    with pytest.raises(UnicodeDecodeError):
        rocketlauncher._read_windows_text_with_encoding(path)
    assert path.read_bytes() == content


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize("body", ["[Settings]{eol}", "[Settings]{eol}[Next]{eol}Keep=1{eol}"])
def test_lightgun_insert_into_empty_section_preserves_line_endings(eol, body):
    before = body.format(eol=eol)
    expected = before.replace(f"[Settings]{eol}", f"[Settings]{eol}Pre_Launch_App=new{eol}")
    assert lightgun._upsert_ini_key(before, "Settings", "Pre_Launch_App", "new") == expected
