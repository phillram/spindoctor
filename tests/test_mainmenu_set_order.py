"""`mainmenu set-order FILE`: put the whole Main Menu in a list's order.

Re-ordering a big menu by hand meant one ``mainmenu reorder`` per wheel, or
index moves typed into ``mainmenu edit``.  ``set-order`` takes the order
from a text file, one system per line, and keeps hidden wheels hidden.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor.cli import cli
from spindoctor.mainmenu import load_main_menu, read_order_file, set_order


NATIVE_MENU = (
    "<menu>\n"
    '  <game name="MAME"/>\n'
    '  <game name="Sega Genesis"/>\n'
    '  <game name="Nintendo Game &amp; Watch"/>\n'
    '  <game name="Nintendo 3DS" enabled="False"/>\n'
    '  <game name="Atari 2600"/>\n'
    "</menu>\n"
)

NEW_ORDER = ["MAME", "Atari 2600", "Nintendo Game & Watch", "Nintendo 3DS", "Sega Genesis"]


def _config(tmp_path):
    cfg = config_mod.Config()
    cfg.hyperspin_dir = str(tmp_path)
    cfg.backup_before_modify = False
    return cfg


def _seed(tmp_path, text=NATIVE_MENU):
    path = tmp_path / "Databases" / "Main Menu" / "Main Menu.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


# ─── set_order ───────────────────────────────────────────────────────────────

def test_set_order_puts_the_menu_in_list_order(tmp_path):
    _seed(tmp_path)
    menu = load_main_menu(_config(tmp_path))
    assert set_order(menu, NEW_ORDER) == []
    assert menu.systems() == NEW_ORDER


def test_set_order_keeps_hidden_and_spelling(tmp_path):
    _seed(tmp_path)
    menu = load_main_menu(_config(tmp_path))
    set_order(menu, ["mame", "ATARI 2600", "nintendo game & watch", "nintendo 3ds", "sega genesis"])
    assert menu.systems() == NEW_ORDER, "the menu keeps its own spelling"
    assert menu.get("Nintendo 3DS").visible is False


def test_set_order_refuses_unknown_and_repeated_names(tmp_path):
    _seed(tmp_path)
    menu = load_main_menu(_config(tmp_path))
    before = menu.systems()
    with pytest.raises(ValueError) as exc:
        set_order(menu, NEW_ORDER + ["Sega Saturn", "MAME"])
    assert "not on the Main Menu: Sega Saturn" in str(exc.value)
    assert "listed twice: MAME" in str(exc.value)
    assert menu.systems() == before, "nothing moves when the list is wrong"


def test_set_order_names_the_systems_it_leaves_out(tmp_path):
    _seed(tmp_path)
    menu = load_main_menu(_config(tmp_path))
    with pytest.raises(ValueError) as exc:
        set_order(menu, ["Atari 2600", "MAME"])
    message = str(exc.value)
    assert "Sega Genesis" in message and "Nintendo 3DS" in message
    assert "--rest end" in message


def test_set_order_rest_at_end_keeps_their_order(tmp_path):
    _seed(tmp_path)
    menu = load_main_menu(_config(tmp_path))
    at_end = set_order(menu, ["Atari 2600", "MAME"], rest_at_end=True)
    assert at_end == ["Sega Genesis", "Nintendo Game & Watch", "Nintendo 3DS"]
    assert menu.systems() == ["Atari 2600", "MAME"] + at_end


# ─── read_order_file ─────────────────────────────────────────────────────────

def test_read_order_file_skips_blanks_comments_and_bom(tmp_path):
    p = tmp_path / "order.txt"
    p.write_bytes(
        b"\xef\xbb\xbf# arcade first\r\nMAME\r\n\r\n  Atari 2600  \r\n# consoles\r\nSega Genesis\r\n"
    )
    assert read_order_file(p) == ["MAME", "Atari 2600", "Sega Genesis"]


def test_read_order_file_reads_utf16(tmp_path):
    # Windows PowerShell 5.1's Out-File and > write UTF-16 LE with a BOM.
    p = tmp_path / "order.txt"
    p.write_bytes("\ufeffMAME\r\nNintendo Game & Watch\r\n".encode("utf-16-le"))
    assert read_order_file(p) == ["MAME", "Nintendo Game & Watch"]


# ─── CLI ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home / ".spindoctor")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / ".spindoctor" / "config.json")
    config_mod.reset_override_cache()
    hs = tmp_path / "hyperspin"
    roms = tmp_path / "roms"
    roms.mkdir()
    menu = _seed(hs)
    cfg = config_mod.Config(roms_dir=str(roms), hyperspin_dir=str(hs))
    cfg.backup_before_modify = False
    config_mod.save_config(cfg)
    yield {"menu": menu, "tmp": tmp_path}
    config_mod.reset_override_cache()


def _order_file(cabinet, names):
    p = cabinet["tmp"] / "order.txt"
    p.write_text("\n".join(names) + "\n", encoding="utf-8")
    return str(p)


def test_cli_set_order_dry_run_writes_nothing(cabinet):
    before = cabinet["menu"].read_bytes()
    result = CliRunner().invoke(
        cli, ["mainmenu", "set-order", _order_file(cabinet, NEW_ORDER)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert cabinet["menu"].read_bytes() == before


def test_cli_set_order_apply_reorders_lines_only(cabinet):
    pytest.importorskip("lxml")
    result = CliRunner().invoke(
        cli, ["mainmenu", "set-order", _order_file(cabinet, NEW_ORDER), "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert cabinet["menu"].read_bytes() == (
        "<menu>\n"
        '  <game name="MAME"/>\n'
        '  <game name="Atari 2600"/>\n'
        '  <game name="Nintendo Game &amp; Watch"/>\n'
        '  <game name="Nintendo 3DS" enabled="False"/>\n'
        '  <game name="Sega Genesis"/>\n'
        "</menu>\n"
    ).encode("utf-8")


def test_cli_set_order_stops_on_a_wrong_list(cabinet):
    before = cabinet["menu"].read_bytes()
    result = CliRunner().invoke(
        cli, ["mainmenu", "set-order", _order_file(cabinet, ["MAME", "Sega Saturn"]), "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 1
    assert "not on the Main Menu: Sega Saturn" in result.output
    assert cabinet["menu"].read_bytes() == before


def test_cli_set_order_rest_end(cabinet):
    result = CliRunner().invoke(
        cli,
        ["mainmenu", "set-order", _order_file(cabinet, ["Atari 2600"]), "--rest", "end", "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    menu = load_main_menu(config_mod.load_config())
    assert menu.systems()[0] == "Atari 2600"
    assert menu.get("Nintendo 3DS").visible is False


def test_cli_set_order_empty_file(cabinet):
    result = CliRunner().invoke(
        cli, ["mainmenu", "set-order", _order_file(cabinet, ["# nothing here"]), "--apply"],
        catch_exceptions=False,
    )
    assert result.exit_code == 1
    assert "no system names" in result.output
