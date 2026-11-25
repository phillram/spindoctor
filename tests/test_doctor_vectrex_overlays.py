"""Tests for the `doctor` Vectrex overlays check (``health.check_vectrex_overlays``).

RocketLauncher's MESS module starts a Vectrex game with ``-view "<romName>"``
when ``<emulator folder>\\artwork\\Vectrex\\<romName>.png`` exists, else with
``-view standard``.  MESS reads the views from ``artwork\\vectrex\\vectrex.lay``
(it hasn't read ``.art`` files since 0.107) and takes the first view whose
name starts with the one asked for, ignoring case, else the file's first
view.  Each test builds a small HyperSpin + RocketLauncher + MESS cabinet in a
temp dir, laid out like a real one: the emulator in ``Global Emulators.ini``
with ``Emu_Path=..\\Emulators\\MESS 0.160\\mess64.exe`` and
``Module=..\\MESS\\MESS.ahk``, and the overlays as a layout converter writes
them: ``<game>.png`` beside ``vectrex.lay``, one view per game.
"""
from __future__ import annotations

from xml.sax.saxutils import quoteattr

from spindoctor import health
from spindoctor.config import Config

OK = health.Status.OK
WARN = health.Status.WARN
INFO = health.Status.INFO

PNG = b"\x89PNG\r\n\x1a\n"  # the module only asks whether the file is there
ART = "backdrop:\n\tfile\t\t= {}.png\n\tlayer\t\t= overlay\n\tposition\t= 0.0,0.0,1.0,1.0\n"


def _write(path, data=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    # RocketLauncher's INIs and MAME's .art / .lay files are CRLF files.
    path.write_bytes(data if isinstance(data, bytes) else data.replace("\n", "\r\n").encode("utf-8"))
    return path


def _layout(views, images=None, version="2"):
    """A ``vectrex.lay`` with one view per name in *views*, in that order,
    each drawing an overlay element of the image *images*[name] (default
    ``<name>.png``)."""
    images = images or {}
    elements = "".join(
        f'\t<element name="overlay{i:02d}">\n\t\t<image file={quoteattr(images.get(v, v + ".png"))} />\n'
        "\t</element>\n" for i, v in enumerate(views, 1))
    bounds = '<bounds x="0" y="0" width="3" height="4" />'
    body = "".join(
        f"\t<view name={quoteattr(v)}>\n\t\t<screen index=\"0\">{bounds}</screen>\n"
        f'\t\t<overlay element="overlay{i:02d}">{bounds}</overlay>\n\t</view>\n'
        for i, v in enumerate(views, 1))
    return f'<?xml version="1.0"?>\n<mamelayout version="{version}">\n{elements}{body}</mamelayout>\n'


def _cabinet(tmp_path, wheels=("GCE Vectrex",), emulator="MESS 0.160", hidden=()):
    """A cabinet whose *wheels* start with *emulator* (``MESS 0.160``, through
    the MESS module, or ``ParaJVE``).  Returns the config, the RocketLauncher
    folder and the MESS folder."""
    hs = tmp_path / "Arcade"
    rl = hs / "RocketLauncher"
    mess = hs / "Emulators" / "MESS 0.160"
    menu = "".join(f'<game name="{w}" enabled="False"/>' if w in hidden else f'<game name="{w}"/>'
                   for w in ("Atari 2600",) + tuple(wheels))
    _write(hs / "Databases" / "Main Menu" / "Main Menu.xml", f"<menu>{menu}</menu>")
    _write(rl / "Settings" / "Global Emulators.ini",
           "[MESS 0.160]\nEmu_Path=..\\Emulators\\MESS 0.160\\mess64.exe\nRom_Extension=7z|zip|vec|bin\n"
           "Module=..\\MESS\\MESS.ahk\n\n"
           "[ParaJVE]\nEmu_Path=..\\Emulators\\ParaJVE\\ParaJVE.exe\nRom_Extension=vec|bin\n")
    for wheel in ("Atari 2600",) + tuple(wheels):
        _write(rl / "Settings" / wheel / "Emulators.ini",
               f"[ROMS]\nDefault_Emulator={emulator}\nRom_Path=..\\Games\\{wheel}\n")
    _write(rl / "Modules" / "MESS" / "MESS.ahk", 'MEmu = MESS\n')
    _write(rl / "Modules" / "MESS" / "MESS.ini", "[Settings]\nFullscreen=true\n")
    _write(mess / "mess64.exe", b"MZ")
    cfg = Config(hyperspin_dir=str(hs), rocketlauncher_dir=str(rl))
    return cfg, rl, mess


def _overlays(mess, games, views=None, images=None, folder=("artwork", "Vectrex")):
    """``<game>.png`` for each of *games* in ``artwork\\Vectrex``, and a
    ``vectrex.lay`` with *views* (default: one per game, in that order;
    ``views=False`` writes no layout)."""
    vec = mess.joinpath(*folder)
    vec.mkdir(parents=True, exist_ok=True)
    for game in games:
        _write(vec / f"{game}.png", PNG)
    if views is not False:
        _write(vec / "vectrex.lay", _layout(list(games) if views is None else views, images))
    return vec


def _old_art(folder, games):
    """The pre-0.107 ``<game>.art`` + ``<game>.png`` pairs in *folder*."""
    for game in games:
        _write(folder / f"{game}.art", ART.format(game))
        _write(folder / f"{game}.png", PNG)


def _wheel(cfg, name="GCE Vectrex"):
    result = health.check_vectrex_overlays(cfg)
    return next(c for c in result.children if c.name == name)


def _row(node, name):
    rows = [c for c in node.children if c.name == name]
    return rows[0] if rows else None


GAMES = ["Berzerk (World)", "Polar Rescue (USA)", "Polar Rescue (USA) (Beta)", "Spike (USA, Europe)"]


# ─── what's fine ─────────────────────────────────────────────────────────────


def test_ok_when_each_overlay_has_its_own_view(tmp_path):
    cfg, _rl, mess = _cabinet(tmp_path)
    vec = _overlays(mess, GAMES)
    result = health.check_vectrex_overlays(cfg)
    assert result.status == OK
    assert result.detail == "1 Vectrex wheel on MESS: no overlay problem found"
    node = _wheel(cfg)
    assert node.status == OK
    assert node.children == []
    assert node.detail == f"4 overlays in {vec}, each with its own view in vectrex.lay"


def test_leftover_art_files_are_named_unused(tmp_path):
    # The converted layout covers every .art, including a dump's copy saved
    # under its CRC ("Pole Position (USA) (A00ED3D6)" is "Pole Position (USA)").
    cfg, _rl, mess = _cabinet(tmp_path)
    _old_art(mess / "artwork", ["Berzerk (World)", "Pole Position (USA) (A00ED3D6)",
                                "Pole Position (USA) (C10F37D8)"])
    vec = _overlays(mess, ["Berzerk (World)", "Pole Position (USA)"])
    node = _wheel(cfg)
    assert node.status == OK
    assert node.detail == (f"2 overlays in {vec}, each with its own view in vectrex.lay; "
                           "3 old .art files are unused (MESS reads only vectrex.lay)")


def test_no_overlays_at_all_is_info(tmp_path):
    cfg, _rl, mess = _cabinet(tmp_path)
    (mess / "artwork").mkdir()
    result = health.check_vectrex_overlays(cfg)
    assert result.status == INFO
    node = _wheel(cfg)
    assert node.status == INFO
    assert node.detail == (f"no overlays in {mess / 'artwork' / 'Vectrex'}: "
                           "every game shows plain white vectors")


# ─── WARN cases ──────────────────────────────────────────────────────────────


def test_old_art_overlays_without_a_layout_warn(tmp_path):
    # The old format: .art + .png pairs loose in artwork\, which MESS ignores.
    cfg, _rl, mess = _cabinet(tmp_path)
    _old_art(mess / "artwork", GAMES)
    result = health.check_vectrex_overlays(cfg)
    assert result.status == WARN
    assert result.detail == ("1 of 1 Vectrex wheel on MESS starts some games without their overlay, "
                             "or with another game's")
    node = _wheel(cfg)
    assert node.status == WARN
    assert node.detail == f"MESS folder {mess}"
    assert [c.name for c in node.children] == ["Old .art overlays"]
    row = node.children[0]
    assert row.status == WARN
    assert row.detail == ("4 .art overlays with no view in a vectrex.lay (there is none) (Berzerk (World), "
                          "Polar Rescue (USA), Polar Rescue (USA) (Beta) and 1 more): MAME and MESS "
                          "stopped reading .art files in 0.107, so these games run without an overlay")
    vec = mess / "artwork" / "Vectrex"
    assert row.fix == (f"Give each game a view in {vec / 'vectrex.lay'}, named exactly as its ROM, that "
                       f"draws the .art file's PNG saved as {vec / '<game>.png'}")


def test_art_overlay_with_no_view_in_the_layout_warns(tmp_path):
    # .art files count in artwork\Vectrex too; the ones the layout covers don't.
    cfg, _rl, mess = _cabinet(tmp_path)
    vec = _overlays(mess, ["Berzerk (World)"])
    _old_art(mess / "artwork", ["Berzerk (World)"])
    _write(vec / "Star Castle (USA).art", ART.format("Star Castle (USA)"))
    row = _row(_wheel(cfg), "Old .art overlays")
    assert row.status == WARN
    assert row.detail.startswith("1 .art overlay with no view in vectrex.lay (Star Castle (USA)): ")
    assert row.detail.endswith("so this game runs without an overlay")


def test_png_with_no_view_of_its_name_gets_another_games_overlay(tmp_path):
    # A name no view starts with gets the first view; "Berzerk" gets the
    # first view whose name starts with it.
    cfg, _rl, mess = _cabinet(tmp_path)
    vec = _overlays(mess, ["Armor..Attack (World)", "Berzerk (World)", "Berzerk", "Spike (USA, Europe)"],
                    views=["Armor..Attack (World)", "Berzerk (World)"])
    node = _wheel(cfg)
    assert node.status == WARN
    row = _row(node, "Overlay PNGs")
    assert row.status == WARN
    assert row.detail == ("2 overlay PNGs with no view of the same name in vectrex.lay: the module asks MESS "
                          "for that view, and MESS shows another one (Berzerk gets Berzerk (World)'s, "
                          "Spike (USA, Europe) gets Armor..Attack (World)'s)")
    assert row.fix == (f'Add a <view name="<game>"> drawing <game>.png to {vec / "vectrex.lay"} for each, '
                       "named exactly as the PNG")


def test_pngs_without_a_layout_warn(tmp_path):
    cfg, _rl, mess = _cabinet(tmp_path)
    vec = _overlays(mess, GAMES[:2], views=False)
    row = _row(_wheel(cfg), "vectrex.lay")
    assert row.status == WARN
    assert row.detail == (f"not in {vec}: the module asks MESS for the view of each of the 2 games with an "
                          "overlay PNG there, but MESS has only its own plain views")


def test_view_after_a_longer_name_it_starts_warns(tmp_path):
    # Sorted by file name, "Polar Rescue (USA) (Beta).png" comes first, and
    # MESS then gives "Polar Rescue (USA)" the Beta's view.
    cfg, _rl, mess = _cabinet(tmp_path)
    vec = _overlays(mess, GAMES, views=["Berzerk (World)", "polar rescue (usa) (beta)",
                                        "Polar Rescue (USA)", "Spike (USA, Europe)", "Spike (USA, Europe)"])
    node = _wheel(cfg)
    row = _row(node, "View order")
    assert row.status == WARN
    assert row.detail == ("2 games get an earlier view whose name starts with theirs (Polar Rescue (USA) gets "
                          "polar rescue (usa) (beta)'s, Spike (USA, Europe) (twice)): MESS takes the first "
                          "view whose name starts with the one asked for")
    assert row.fix.startswith(f"In {vec / 'vectrex.lay'}, put each game's view above every longer name")
    assert _row(node, "Overlay PNGs") is None


def test_view_drawing_a_missing_image_or_element_warns(tmp_path):
    cfg, _rl, mess = _cabinet(tmp_path)
    vec = _overlays(mess, GAMES[:3], images={"Berzerk (World)": "berzerk.png"})
    lay = vec / "vectrex.lay"
    _write(lay, lay.read_text(encoding="utf-8").replace('overlay element="overlay03"', 'overlay element="nope"'))
    row = _row(_wheel(cfg), "Overlay images")
    assert row.status == WARN
    assert row.detail == (f"2 games' view draws an image that isn't in {vec}, or an element vectrex.lay "
                          "doesn't define (Berzerk (World), Polar Rescue (USA) (Beta)), so they show no overlay")


def test_layout_mess_cannot_read_warns(tmp_path):
    cfg, _rl, mess = _cabinet(tmp_path)
    vec = _overlays(mess, ["Spy Hunter"], views=False)
    lay = _write(vec / "vectrex.lay", '<mamelayout version="2"><view name="Cops & Robbers"></view></mamelayout>')
    node = _wheel(cfg)
    assert [c.name for c in node.children] == ["vectrex.lay"]
    row = node.children[0]
    assert row.status == WARN
    assert row.detail.startswith(f"{lay} isn't valid XML (")
    assert row.detail.endswith("), so MESS ignores it and no game shows its overlay")
    assert "&amp;" in row.fix

    _write(lay, _layout(["Spy Hunter"], version="1"))
    row = _wheel(cfg).children[0]
    assert row.detail == (f'{lay} isn\'t a <mamelayout version="2"> layout, so MESS ignores it and no game '
                          "shows its overlay")


# ─── INFO notes ──────────────────────────────────────────────────────────────


def test_views_without_a_png_are_info(tmp_path):
    cfg, _rl, mess = _cabinet(tmp_path)
    _overlays(mess, ["Berzerk (World)"], views=["Berzerk (World)", "Star Castle (USA)"])
    node = _wheel(cfg)
    assert node.status == INFO
    row = _row(node, "Views without a PNG")
    assert row.status == INFO
    assert row.detail.startswith("1 view in vectrex.lay with no PNG of the same name (Star Castle (USA)): "
                                 "the module starts a game with -view standard")


def test_use_overlays_false_in_the_module_ini_is_info(tmp_path):
    cfg, rl, mess = _cabinet(tmp_path)
    _overlays(mess, GAMES)
    ini = _write(rl / "Modules" / "MESS" / "MESS.ini",
                 "[Settings]\nFullscreen=true\n\n[gce vectrex]\nUse_Overlays=False\n")
    row = _row(_wheel(cfg), "Use_Overlays")
    assert row.status == INFO
    assert row.detail == (f"Use_Overlays=false under [GCE Vectrex] in {ini}: the module starts MESS with "
                          "-nouse_overlays, so no game shows its overlay")


# ─── which wheels and folders ────────────────────────────────────────────────


def test_info_without_rocketlauncher_or_hyperspin_dir(tmp_path):
    cfg, _rl, _m = _cabinet(tmp_path)
    cfg.rocketlauncher_dir = ""
    assert health.check_vectrex_overlays(cfg).status == INFO
    cfg, _rl, _m = _cabinet(tmp_path / "b")
    cfg.hyperspin_dir = str(tmp_path / "missing")
    assert health.check_vectrex_overlays(cfg).status == INFO


def test_wheel_on_another_emulator_is_left_alone(tmp_path):
    cfg, _rl, mess = _cabinet(tmp_path, emulator="ParaJVE")
    _old_art(mess / "artwork", GAMES)
    result = health.check_vectrex_overlays(cfg)
    assert result.status == INFO
    assert result.detail == "no visible Vectrex wheel starts with RocketLauncher's MESS module"
    assert result.children == []


def test_hidden_wheel_is_left_alone(tmp_path):
    cfg, _rl, mess = _cabinet(tmp_path, hidden=("GCE Vectrex",))
    _old_art(mess / "artwork", GAMES)
    result = health.check_vectrex_overlays(cfg)
    assert result.status == INFO
    assert result.children == []


def test_folder_and_file_names_in_any_case(tmp_path):
    cfg, _rl, mess = _cabinet(tmp_path, wheels=("GCE VECTREX",))
    vec = mess / "ARTWORK" / "VECTREX"
    _write(vec / "berzerk (world).PNG", PNG)
    _write(vec / "VECTREX.LAY", _layout(["Berzerk (World)"], {"Berzerk (World)": "BERZERK (WORLD).png"}))
    _old_art(mess / "ARTWORK", ["Berzerk (World)"])
    node = _wheel(cfg, "GCE VECTREX")
    assert node.status == OK, node.children
    assert node.detail.startswith(f"1 overlay in {vec}, each with its own view")


def test_wheels_sharing_a_mess_folder_read_it_once(tmp_path, monkeypatch):
    cfg, _rl, mess = _cabinet(tmp_path, wheels=("GCE Vectrex", "Vectrex Homebrew"))
    _overlays(mess, GAMES)
    reads = []
    real = health._layout_views
    monkeypatch.setattr(health, "_layout_views", lambda lay: reads.append(lay) or real(lay))
    result = health.check_vectrex_overlays(cfg)
    assert [c.name for c in result.children] == ["GCE Vectrex", "Vectrex Homebrew"]
    assert result.detail == "2 Vectrex wheels on MESS: no overlay problem found"
    assert len(reads) == 1


def test_missing_emulator_folder_is_info(tmp_path):
    cfg, rl, _mess = _cabinet(tmp_path)
    _write(rl / "Settings" / "Global Emulators.ini",
           "[MESS 0.160]\nEmu_Path=..\\Emulators\\Gone\\mess64.exe\nRom_Extension=vec\nModule=..\\MESS\\MESS.ahk\n")
    node = _wheel(cfg)
    assert node.status == INFO
    assert node.detail.startswith("emulator folder not found: ")


def test_registered_in_doctor(tmp_path):
    cfg, _rl, _m = _cabinet(tmp_path)
    names = [c.name for c in health.run_health_checks(cfg).checks]
    assert "Vectrex overlays" in names
    assert names.index("Vectrex overlays") == names.index("Daphne keys") + 1
