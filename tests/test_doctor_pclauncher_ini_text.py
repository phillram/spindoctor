"""Tests for the `doctor` PCLauncher INI text check (``health.check_pclauncher_ini_text``).

PCLauncher waits for a game's window by ``FadeTitle``.  RocketLauncher's
AutoHotkey is an ANSI build and matches the INI's raw bytes, so a Japanese
window title is stored as its Shift-JIS bytes.  When an editor re-saves the INI
as UTF-8, each byte it can't read becomes U+FFFD (``EF BF BD``) and the window
is never found.  Each test builds a small cabinet in a temp dir: a Main Menu,
and ``RocketLauncher\\Modules\\PCLauncher`` with a per-system module INI
(``[<game>]`` sections) and/or per-game INIs in ``<System>\\``.
"""
from __future__ import annotations

from spindoctor import health
from spindoctor.config import Config

OK = health.Status.OK
WARN = health.Status.WARN
INFO = health.Status.INFO

# "ＢＡＴＴＬＥ　ＧＥＡＲ　４" in Shift-JIS, as RocketLauncher needs it ...
SJIS_TITLE = "ＢＡＴＴＬＥ　ＧＥＡＲ　４".encode("cp932")
# ... and the same line after a UTF-8 editor replaced every byte it couldn't read.
DAMAGED_TITLE = SJIS_TITLE.decode("utf-8", errors="replace").encode("utf-8")


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        # RocketLauncher's INIs are CRLF files.
        data = data.replace("\n", "\r\n").encode("cp1252")
    path.write_bytes(data)
    return path


def _section(game, title_bytes, app="E:\\Games\\Game\\game.exe"):
    return (f"[{game}]\r\nApplication={app}\r\nFadeTitle=".encode("cp1252")
            + title_bytes + b" ahk_class " + title_bytes
            + b"\r\nExitMethod=WinClose Application\r\n")


def _cabinet(tmp_path, wheels=("Taito Type X",), main_menu=True, games=None):
    """*games* maps a wheel to the games its database lists (no database when left out)."""
    hs = tmp_path / "Arcade"
    rl = hs / "RocketLauncher"
    if main_menu:
        menu = "".join(f'<game name="{w}"/>' for w in wheels)
        _write(hs / "Databases" / "Main Menu" / "Main Menu.xml", f"<menu>{menu}</menu>")
    for wheel, names in (games or {}).items():
        xml = "".join(f'<game name="{g}"><description>{g}</description></game>' for g in names)
        _write(hs / "Databases" / wheel / f"{wheel}.xml", f"<menu>{xml}</menu>")
    pcl = rl / "Modules" / "PCLauncher"
    pcl.mkdir(parents=True)
    _write(pcl / "PCLauncher.ahk", 'MEmu := "PCLauncher"\n')
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl))
    return cfg, pcl


def test_damaged_fadetitle_in_system_module_ini_warns(tmp_path):
    cfg, pcl = _cabinet(tmp_path)
    _write(pcl / "Taito Type X.ini",
           _section("Arcana Heart 3", b"Arcana Heart 3") + _section("Battle Gear 4 Tuned", DAMAGED_TITLE))
    result = health.check_pclauncher_ini_text(cfg)
    assert result.status == WARN
    [node] = result.children
    assert node.name == "Taito Type X"
    assert node.status == WARN
    assert "Taito Type X.ini [Battle Gear 4 Tuned] FadeTitle" in node.detail
    assert "Arcana Heart 3" not in node.detail
    assert "ANSI code page" in node.fix


def test_intact_shift_jis_title_is_ok(tmp_path):
    cfg, pcl = _cabinet(tmp_path)
    _write(pcl / "Taito Type X.ini", _section("Battle Gear 4 Tuned", SJIS_TITLE))
    result = health.check_pclauncher_ini_text(cfg)
    assert result.status == OK
    assert result.children == []
    assert "1 INI(s) OK" in result.detail


def test_cp1252_accents_are_ok(tmp_path):
    cfg, pcl = _cabinet(tmp_path, wheels=("PC Games",))
    _write(pcl / "PC Games.ini", _section("Pokémon Café", "Pokémon Café Mix".encode("cp1252")))
    assert health.check_pclauncher_ini_text(cfg).status == OK


def test_real_utf8_text_is_ok(tmp_path):
    cfg, pcl = _cabinet(tmp_path, wheels=("PC Games",))
    _write(pcl / "PC Games.ini", _section("Café", "Café".encode("utf-8")))
    assert health.check_pclauncher_ini_text(cfg).status == OK


def test_damaged_per_game_ini_warns(tmp_path):
    cfg, pcl = _cabinet(tmp_path, wheels=("PC Games",))
    _write(pcl / "PC Games" / "Fighter IV.ini", _section("Fighter IV", DAMAGED_TITLE))
    _write(pcl / "PC Games" / "Other Game.ini", _section("Other Game", b"Other Game"))
    result = health.check_pclauncher_ini_text(cfg)
    assert result.status == WARN
    [node] = result.children
    assert node.name == "PC Games"
    assert "PC Games\\Fighter IV.ini [Fighter IV] FadeTitle" in node.detail
    assert "Other Game" not in node.detail


def test_module_wide_ini_is_checked(tmp_path):
    cfg, pcl = _cabinet(tmp_path)
    _write(pcl / "PCLauncher.ini", b"[Settings]\r\nFadeTitle=" + DAMAGED_TITLE + b"\r\n")
    result = health.check_pclauncher_ini_text(cfg)
    assert result.status == WARN
    assert result.children[0].name == "PCLauncher.ini"
    assert "[Settings] FadeTitle" in result.children[0].detail


def test_ini_of_a_wheel_not_on_the_main_menu_is_ignored(tmp_path):
    cfg, pcl = _cabinet(tmp_path)
    _write(pcl / "Taito Type X BACKUP.ini", _section("Battle Gear 4 Tuned", DAMAGED_TITLE))
    _write(pcl / "Removed Wheel" / "Game.ini", _section("Game", DAMAGED_TITLE))
    result = health.check_pclauncher_ini_text(cfg)
    assert result.status == INFO
    assert result.children == []


def test_sections_of_games_not_on_the_wheel_are_ignored(tmp_path):
    cfg, pcl = _cabinet(tmp_path, wheels=("PC Games",), games={"PC Games": ["Kept Game"]})
    _write(pcl / "PC Games.ini",
           _section("Leftover Game", DAMAGED_TITLE) + _section("kept game", DAMAGED_TITLE)
           + b"[Settings]\r\nFadeTitle=" + DAMAGED_TITLE + b"\r\n")
    node = health.check_pclauncher_ini_text(cfg).children[0]
    assert node.detail.startswith("2 value(s) lost characters")
    assert "[kept game] FadeTitle" in node.detail
    assert "[Settings] FadeTitle" in node.detail
    assert "Leftover Game" not in node.detail


def test_per_game_inis_of_games_not_on_the_wheel_are_ignored(tmp_path):
    cfg, pcl = _cabinet(tmp_path, wheels=("PC Games",), games={"PC Games": ["Kept: Game"]})
    _write(pcl / "PC Games" / "Leftover.ini", _section("Leftover", DAMAGED_TITLE))
    # PCLauncher INIs are named the Windows-safe way: "Kept: Game" -> "Kept Game.ini".
    _write(pcl / "PC Games" / "Kept Game.ini", _section("Kept: Game", DAMAGED_TITLE))
    node = health.check_pclauncher_ini_text(cfg).children[0]
    assert "PC Games\\Kept Game.ini" in node.detail
    assert "Leftover" not in node.detail


def test_damaged_section_name_is_shown_even_with_a_database(tmp_path):
    cfg, pcl = _cabinet(tmp_path, games={"Taito Type X": ["Game"]})
    _write(pcl / "Taito Type X.ini", b"[" + DAMAGED_TITLE + b"]\r\nApplication=x.exe\r\n")
    assert health.check_pclauncher_ini_text(cfg).status == WARN


def test_without_main_menu_every_ini_is_checked(tmp_path):
    cfg, pcl = _cabinet(tmp_path, main_menu=False)
    _write(pcl / "Taito Type X.ini", _section("Battle Gear 4 Tuned", DAMAGED_TITLE))
    _write(pcl / "PC Games" / "Game.ini", _section("Game", DAMAGED_TITLE))
    result = health.check_pclauncher_ini_text(cfg)
    assert result.status == WARN
    assert sorted(c.name for c in result.children) == ["PC Games", "Taito Type X.ini"]


def test_wheel_names_match_case_insensitively(tmp_path):
    cfg, pcl = _cabinet(tmp_path, wheels=("Taito Type X",))
    _write(pcl / "TAITO TYPE X.INI", _section("Battle Gear 4 Tuned", DAMAGED_TITLE))
    result = health.check_pclauncher_ini_text(cfg)
    assert result.status == WARN
    assert "[Battle Gear 4 Tuned] FadeTitle" in result.children[0].detail


def test_utf16_ini(tmp_path):
    cfg, pcl = _cabinet(tmp_path, wheels=("A", "B"))
    _write(pcl / "A.ini", "\ufeff[Game]\r\nFadeTitle=Game \ufffd\ufffd\r\n".encode("utf-16-le"))
    _write(pcl / "B.ini", "\ufeff[Game]\r\nFadeTitle=ゲーム\r\n".encode("utf-16-le"))
    result = health.check_pclauncher_ini_text(cfg)
    assert [c.name for c in result.children] == ["A"]
    assert "A.ini [Game] FadeTitle" in result.children[0].detail


def test_utf8_bom_and_comment_lines(tmp_path):
    cfg, pcl = _cabinet(tmp_path)
    _write(pcl / "Taito Type X.ini",
           b"\xef\xbb\xbf; old title: " + DAMAGED_TITLE + b"\r\n" + _section("Game", b"Game"))
    assert health.check_pclauncher_ini_text(cfg).status == OK


def test_damaged_section_name_and_many_values(tmp_path):
    cfg, pcl = _cabinet(tmp_path)
    body = b"[" + DAMAGED_TITLE + b"]\r\nApplication=x.exe\r\n"
    body += b"".join(_section(f"Game {i}", DAMAGED_TITLE) for i in range(4))
    _write(pcl / "Taito Type X.ini", body)
    node = health.check_pclauncher_ini_text(cfg).children[0]
    assert node.detail.startswith("5 value(s) lost characters")
    assert "(+2 more)" in node.detail


def test_not_configured_and_no_folder(tmp_path):
    assert health.check_pclauncher_ini_text(Config()).status == INFO
    cfg = Config(hyperspin_dir=str(tmp_path), rocketlauncher_dir=str(tmp_path / "RocketLauncher"))
    result = health.check_pclauncher_ini_text(cfg)
    assert result.status == INFO
    assert "no PCLauncher module folder" in result.detail


def test_registered_in_doctor(tmp_path):
    cfg, _pcl = _cabinet(tmp_path)
    names = [c.name for c in health.run_health_checks(cfg).checks]
    assert names.index("PCLauncher INI text") == names.index("Casual Games") + 1
