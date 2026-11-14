"""Tests for the `doctor` checks of HyperSpin's wheel art and letter art.

* **Wheel art:** a game with no ``Media\\<System>\\Images\\Wheel\\<name>.png``
  (or ``.swf``) shows as plain text, or, with ``[filters] wheels_only=true``
  in ``Settings\\<System>.ini``, isn't on the wheel at all.
* **Letter art:** jumping to the next letter shows
  ``Media\\<System>\\Images\\Letters\\<char>.png`` for the first character of
  each game's description.

Each test builds a small cabinet in a temp dir.
"""
from __future__ import annotations

from spindoctor import health
from spindoctor.config import Config

OK = health.Status.OK
WARN = health.Status.WARN
INFO = health.Status.INFO


def _write(path, text="", bom=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return path


def _game(name, desc=None, clone="", enabled=""):
    extra = f"<cloneof>{clone}</cloneof>" if clone else ""
    extra += f"<enabled>{enabled}</enabled>" if enabled else ""
    return f'<game name="{name}"><description>{desc or name}</description>{extra}</game>'


def _cabinet(tmp_path, wheels, hidden=(), filters=None, art=None, letters=None):
    """A HyperSpin folder.  *wheels* maps wheel name -> list of ``_game``
    strings; *filters* maps wheel name -> ``{key: value}`` for ``[filters]``;
    *art* maps wheel name -> wheel art file names; *letters* maps wheel name
    -> letter file names (``None`` for no Letters folder)."""
    hs = tmp_path / "HyperSpin"
    menu = "".join(f'<game name="{w}" enabled="False"/>' if w in hidden else f'<game name="{w}"/>'
                   for w in wheels)
    _write(hs / "Databases" / "Main Menu" / "Main Menu.xml", f"<menu>{menu}</menu>")
    for wheel, games in wheels.items():
        _write(hs / "Databases" / wheel / f"{wheel}.xml", f"<menu>{''.join(games)}</menu>")
        keys = {"parents_only": "false", "themes_only": "false", "wheels_only": "false", "roms_only": "false"}
        keys.update((filters or {}).get(wheel, {}))
        _write(hs / "Settings" / f"{wheel}.ini",
               "[exe info]\nrompath=\n\n[filters]\n" + "".join(f"{k}={v}\n" for k, v in keys.items()))
    for wheel in list(wheels) + ["Main Menu"]:
        for name in (art or {}).get(wheel, ()):
            _write(hs / "Media" / wheel / "Images" / "Wheel" / name, "art")
    for wheel, names in (letters or {}).items():
        if names is None:
            continue
        folder = hs / "Media" / wheel / "Images" / "Letters"
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            _write(folder / name, "letter")
    return Config(roms_dir=str(tmp_path / "Games"), hyperspin_dir=str(hs)), hs


def _node(chk, system):
    return next(c for c in chk.children if c.name == system)


def _names(chk):
    return [c.name for c in chk.children]


# Every wheel on the Main Menu has a logo unless a test says otherwise.
def _menu_art(*wheels):
    return [f"{w}.png" for w in wheels]


# ── Wheel art ───────────────────────────────────────────────────────────────

def test_wheels_only_hides_games_with_no_wheel_art(tmp_path):
    cfg, hs = _cabinet(
        tmp_path, {"MAME": [_game("pacman"), _game("galaga"), _game("newgame1"), _game("newgame2")]},
        filters={"MAME": {"wheels_only": "true"}},
        art={"MAME": ["pacman.png", "galaga.png"], "Main Menu": _menu_art("MAME")})
    chk = health.check_wheel_art(cfg)
    node = _node(chk, "MAME")
    assert node.status == INFO and chk.status == INFO
    assert node.detail == ('wheels_only=true hides 2 of 4 games from the wheel, as they have no '
                           'wheel art: "newgame1", "newgame2"')
    assert str(hs / "Settings" / "MAME.ini") in node.fix
    assert "set wheels_only=false under [filters]" in node.fix
    assert 'spindoctor fetch-media --system "MAME" --types wheel --apply' in node.fix
    assert str(hs / "Media" / "MAME" / "Images" / "Wheel") in node.fix
    assert chk.detail == "wheels_only=true hides 2 games on 1 wheel (no wheel art)"


def test_wheels_only_with_no_art_at_all_warns_the_wheel_is_empty(tmp_path):
    cfg, _hs = _cabinet(tmp_path, {"AAE": [_game("astdelux"), _game("armora")]},
                        filters={"AAE": {"wheels_only": "true"}}, art={"Main Menu": _menu_art("AAE")})
    chk = health.check_wheel_art(cfg)
    node = _node(chk, "AAE")
    assert node.status == WARN and chk.status == WARN
    assert node.detail == "wheels_only=true, but none of its 2 games has wheel art, so HyperSpin lists no games"


def test_games_without_art_on_other_wheels_show_as_plain_text(tmp_path):
    cfg, _hs = _cabinet(tmp_path, {"NES": [_game("Contra (USA)"), _game("Zelda (USA)")]},
                        art={"NES": ["Contra (USA).png"], "Main Menu": _menu_art("NES")})
    chk = health.check_wheel_art(cfg)
    node = _node(chk, "NES")
    assert node.status == INFO and chk.status == INFO
    assert node.detail == ('1 of 2 games has no wheel art, so HyperSpin shows its name as plain text: '
                           '"Zelda (USA)"')
    assert "wheels_only" not in node.fix
    assert chk.detail == "1 game on 1 wheel show as plain text (no wheel art)"


def test_parents_only_leaves_clones_out(tmp_path):
    games = [_game("sf2"), _game("sf2ce", clone="sf2"), _game("sf2hf", clone="sf2"), _game("ffight")]
    cfg, _hs = _cabinet(tmp_path, {"CPS": games},
                        filters={"CPS": {"wheels_only": "true", "parents_only": "true"}},
                        art={"CPS": ["sf2.png"], "Main Menu": _menu_art("CPS")})
    node = _node(health.check_wheel_art(cfg), "CPS")
    assert node.detail.startswith('wheels_only=true hides 1 of 2 parent games from the wheel, as it has')
    assert node.detail.endswith(': "ffight"')


def test_clones_count_without_parents_only(tmp_path):
    games = [_game("sf2"), _game("sf2ce", clone="sf2"), _game("self", clone="self")]
    cfg, _hs = _cabinet(tmp_path, {"CPS": games}, filters={"CPS": {"wheels_only": "true"}},
                        art={"CPS": ["sf2.png"], "Main Menu": _menu_art("CPS")})
    node = _node(health.check_wheel_art(cfg), "CPS")
    assert 'hides 2 of 3 games' in node.detail and '"sf2ce", "self"' in node.detail


def test_a_game_naming_itself_as_parent_is_not_a_clone(tmp_path):
    games = [_game("sf2", clone="SF2"), _game("sf2ce", clone="sf2")]
    cfg, _hs = _cabinet(tmp_path, {"CPS": games}, filters={"CPS": {"parents_only": "true"}},
                        art={"Main Menu": _menu_art("CPS")})
    node = _node(health.check_wheel_art(cfg), "CPS")
    assert node.detail.startswith("1 of 1 parent game has no wheel art")


def test_swf_art_and_any_case_count(tmp_path):
    cfg, _hs = _cabinet(tmp_path, {"SNES": [_game("Mario"), _game("Zelda"), _game("Metroid")]},
                        filters={"SNES": {"wheels_only": "true"}},
                        art={"SNES": ["MARIO.PNG", "zelda.swf", "Metroid.jpg"], "Main Menu": _menu_art("SNES")})
    node = _node(health.check_wheel_art(cfg), "SNES")
    assert 'hides 1 of 3 games' in node.detail and '"Metroid"' in node.detail


def test_art_is_looked_up_under_the_name_as_written(tmp_path):
    # HyperSpin looks up "Some Hack V2 .png"; art saved trimmed doesn't count.
    cfg, _hs = _cabinet(tmp_path, {"NES": [_game("Some Hack V2 "), _game("Contra")]},
                        art={"NES": ["Some Hack V2.png", "Contra.png"], "Main Menu": _menu_art("NES")})
    node = _node(health.check_wheel_art(cfg), "NES")
    assert node.detail.endswith(': "Some Hack V2 "')


def test_a_name_no_file_can_have_never_has_art(tmp_path):
    cfg, _hs = _cabinet(tmp_path, {"PC Games": [_game("What?"), _game("Doom")]},
                        art={"PC Games": ["Doom.png"], "Main Menu": _menu_art("PC Games")})
    node = _node(health.check_wheel_art(cfg), "PC Games")
    assert node.detail.endswith(': "What?"')


def test_disabled_games_are_not_counted(tmp_path):
    cfg, _hs = _cabinet(tmp_path, {"NES": [_game("Contra"), _game("Gone", enabled="No")]},
                        art={"NES": ["Contra.png"], "Main Menu": _menu_art("NES")})
    chk = health.check_wheel_art(cfg)
    assert chk.status == OK and chk.children == []


def test_names_are_listed_five_then_how_many_more(tmp_path):
    games = [_game(f"game{i}") for i in range(8)]
    cfg, _hs = _cabinet(tmp_path, {"MAME": games}, filters={"MAME": {"wheels_only": "true"}},
                        art={"MAME": ["game7.png"], "Main Menu": _menu_art("MAME")})
    node = _node(health.check_wheel_art(cfg), "MAME")
    assert node.detail.endswith('"game0", "game1", "game2", "game3", "game4" and 2 more')


def test_settings_ini_read_in_any_case_with_a_bom(tmp_path):
    cfg, hs = _cabinet(tmp_path, {"MAME": [_game("pacman"), _game("galaga")]},
                       art={"MAME": ["pacman.png"], "Main Menu": _menu_art("MAME")})
    _write(hs / "Settings" / "MAME.ini", "[Filters]\r\nParents_Only=False\r\nWheels_Only=TRUE\r\n", bom=True)
    node = _node(health.check_wheel_art(cfg), "MAME")
    assert node.detail.startswith("wheels_only=true hides 1 of 2 games")


def test_wheels_switched_off_on_the_main_menu_are_skipped(tmp_path):
    cfg, _hs = _cabinet(tmp_path, {"Gun Games": [_game("ptblank")], "NES": [_game("Contra")]},
                        hidden=("Gun Games",), art={"NES": ["Contra.png"], "Main Menu": _menu_art("NES")})
    chk = health.check_wheel_art(cfg)
    assert chk.status == OK and _names(chk) == []
    assert chk.detail == "every game on the Main Menu and its 1 wheel has wheel art"


def test_main_menu_systems_without_a_logo_show_as_text(tmp_path):
    cfg, hs = _cabinet(tmp_path, {"NES": [_game("Contra")], "SNES": [_game("Mario")]},
                       art={"NES": ["Contra.png"], "SNES": ["Mario.png"], "Main Menu": _menu_art("NES")})
    node = _node(health.check_wheel_art(cfg), "Main Menu")
    assert node.detail == '1 of 2 games has no wheel art, so HyperSpin shows its name as plain text: "SNES"'
    assert node.fix == f"Add wheel art to {hs / 'Media' / 'Main Menu' / 'Images' / 'Wheel'} as <name>.png"


def test_summary_counts_hidden_and_plain_text_separately(tmp_path):
    cfg, _hs = _cabinet(
        tmp_path,
        {"A": [_game("a1"), _game("a2"), _game("a3")], "B": [_game("b1"), _game("b2")],
         "C": [_game("c1"), _game("c2")]},
        filters={"A": {"wheels_only": "true"}, "B": {"wheels_only": "true"}},
        art={"A": ["a1.png"], "B": ["b1.png"], "C": ["c1.png"], "Main Menu": _menu_art("A", "B", "C")})
    chk = health.check_wheel_art(cfg)
    assert _names(chk) == ["A", "B", "C"]
    assert chk.detail == ("wheels_only=true hides 3 games on 2 wheels (no wheel art); "
                          "1 game on 1 wheel show as plain text (no wheel art)")


def test_no_hyperspin_dir_is_info(tmp_path):
    chk = health.check_wheel_art(Config(hyperspin_dir=str(tmp_path / "nope")))
    assert chk.status == INFO and "skipping" in chk.detail


# ── Letter art ──────────────────────────────────────────────────────────────

def test_a_wheel_with_no_letters_folder_warns(tmp_path):
    cfg, hs = _cabinet(tmp_path, {"Wii": [_game("Zelda"), _game("Mario"), _game("Kirby")]})
    chk = health.check_letter_art(cfg)
    node = _node(chk, "Wii")
    assert node.status == WARN and chk.status == WARN
    assert node.detail == ('no Letters folder, so HyperSpin has no letter to show when you jump to the '
                           'next letter (3 first characters: "k", "m", "z")')
    assert str(hs / "Media" / "Wii" / "Images" / "Letters") in node.fix
    assert chk.detail == "1 wheel has no letter art at all"


def test_an_empty_letters_folder_warns(tmp_path):
    cfg, _hs = _cabinet(tmp_path, {"PV-1000": [_game("Pooyan")]}, letters={"PV-1000": ["readme.txt"]})
    node = _node(health.check_letter_art(cfg), "PV-1000")
    assert node.status == WARN and node.detail.startswith("no .png letters in its Letters folder")


def test_missing_first_characters_are_info(tmp_path):
    games = [_game("1080 Snowboarding"), _game("Mario Kart 64"), _game("$100,000 Pyramid"), _game("Zelda")]
    cfg, hs = _cabinet(tmp_path, {"N64": games}, letters={"N64": ["M.png", "z.png"]})
    chk = health.check_letter_art(cfg)
    node = _node(chk, "N64")
    assert node.status == INFO and chk.status == INFO
    assert node.detail == 'no letter art for 2 of 4 first characters: "$", "1"'
    assert node.fix == f'Add "$.png", "1.png" to {hs / "Media" / "N64" / "Images" / "Letters"}'
    assert chk.detail == "1 wheel misses letters for some first characters"


def test_all_letters_present_is_ok(tmp_path):
    cfg, _hs = _cabinet(tmp_path, {"NES": [_game("Contra"), _game("castlevania")]},
                        letters={"NES": ["c.png"]})
    chk = health.check_letter_art(cfg)
    assert chk.status == OK and chk.children == []
    assert chk.detail == "every first character on 1 wheel has letter art"


def test_letters_come_from_the_description_not_the_name(tmp_path):
    cfg, _hs = _cabinet(tmp_path, {"MAME": [_game("sf2", "Street Fighter II")]}, letters={"MAME": ["s.png"]})
    assert health.check_letter_art(cfg).children == []


def test_a_dot_needs_dot_png_and_a_quote_is_skipped(tmp_path):
    games = [_game(".38 Ambush Alley"), _game("300", '"300"'), _game("Area 51")]
    cfg, _hs = _cabinet(tmp_path, {"Gun Games": games}, letters={"Gun Games": ["a.png", "3.png"]})
    node = _node(health.check_letter_art(cfg), "Gun Games")
    assert node.detail == 'no letter art for 1 of 2 first characters: "."'
    _write(cfg.media_dir / "Gun Games" / "Images" / "Letters" / "..png", "letter")
    assert health.check_letter_art(cfg).children == []


def test_games_hidden_by_the_filters_need_no_letter(tmp_path):
    games = [_game("pacman", "Pac-Man"), _game("newgame", "Zzap"), _game("pacmanf", "Bonus", clone="pacman")]
    cfg, _hs = _cabinet(tmp_path, {"MAME": games},
                        filters={"MAME": {"wheels_only": "true", "parents_only": "true"}},
                        art={"MAME": ["pacman.png", "pacmanf.png"]}, letters={"MAME": ["p.png"]})
    assert health.check_letter_art(cfg).children == []


def test_ranked_wheels_main_menu_and_hidden_wheels_are_skipped(tmp_path):
    wheels = {"Recently Played": [_game("Zelda")], "Most Played": [_game("Mario")],
              "Favorites": [_game("Metroid")], "KODI": [_game("Kodi")]}
    cfg, _hs = _cabinet(tmp_path, wheels, hidden=("KODI",))
    chk = health.check_letter_art(cfg)
    assert _names(chk) == ["Favorites"]


def test_doctor_runs_both_checks(tmp_path, monkeypatch):
    cfg, _hs = _cabinet(tmp_path, {"NES": [_game("Contra")]}, art={"NES": ["Contra.png"]})
    called = []
    for fn in ("check_wheel_art", "check_letter_art"):
        real = getattr(health, fn)
        monkeypatch.setattr(health, fn, lambda c, real=real, fn=fn: called.append(fn) or real(c))
    report = health.run_health_checks(cfg)
    assert called == ["check_wheel_art", "check_letter_art"]
    names = [c.name for c in report.checks]
    assert names.index("Wheel art") == names.index("Spaces in game names") + 1
    assert names.index("Letter art") == names.index("Wheel art") + 1
