"""Tests for the `doctor` check of game themes' video boxes against their videos' shape.

HyperSpin 1.5 lays a theme out on a 1024x768 canvas and stretches it to the
screen; with ``forceaspect="both"`` the video fills its ``<video>`` box.  A box
that isn't the videos' shape on screen plays every clip too wide or too tall.
A wheel's main theme (``Themes/Default.zip``) is judged by the videos of the
games that use it, and a game's own theme (``Themes/<game>.zip``) by its video.

Also :func:`spindoctor.introvideo.video_frame_size`, which reads the size from
an MP4 track header or an FLV's ``onMetaData``.

Each test builds a small cabinet in a temp dir, with header-only video files.
"""
from __future__ import annotations

import struct
import zipfile

from spindoctor import health
from spindoctor.config import Config
from spindoctor.introvideo import video_frame_size

OK = health.Status.OK
WARN = health.Status.WARN
INFO = health.Status.INFO

FULL_SCREEN = {"w": "1024", "h": "768", "x": "512", "y": "384"}
# On a 1920x1080 screen one canvas unit is 1.875 px across and 1.406 down.
BOX_4X3 = {"w": "480", "h": "480"}   # 900 x 675 px
BOX_3X4 = {"w": "270", "h": "480"}   # 506 x 675 px


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def _tkhd(width: int, height: int, version: int = 0) -> bytes:
    if version == 1:   # 64-bit times: 88 bytes before the size
        head = b"\x01\x00\x00\x00" + b"\x00" * 32
    else:              # 76 bytes before the size
        head = b"\x00\x00\x00\x00" + b"\x00" * 20
    return _box(b"tkhd", head + b"\x00" * 16 + b"\x00" * 36 + struct.pack(">II", width << 16, height << 16))


def _mp4(width: int, height: int, version: int = 0, audio_first: bool = False, mdat_first: bool = True) -> bytes:
    tracks = _box(b"trak", _tkhd(width, height, version))
    if audio_first:
        tracks = _box(b"trak", _tkhd(0, 0)) + tracks
    moov = _box(b"moov", _box(b"mvhd", b"\x00" * 100) + tracks)
    mdat = _box(b"mdat", b"\x00" * 64)
    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00")
    return ftyp + (mdat + moov if mdat_first else moov + mdat)


def _flv(width: float, height: float) -> bytes:
    meta = (b"\x02\x00\x0aonMetaData\x08\x00\x00\x00\x03"
            b"\x00\x08duration\x00" + struct.pack(">d", 30.0)
            + b"\x00\x05width\x00" + struct.pack(">d", width)
            + b"\x00\x06height\x00" + struct.pack(">d", height) + b"\x00\x00\x09")
    return b"FLV\x01\x05\x00\x00\x00\x09\x00\x00\x00\x00\x12" + struct.pack(">I", len(meta))[1:] + b"\x00" * 7 + meta


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


def _theme_zip(path, attrs, forceaspect="both", name="Theme.xml"):
    attrs = dict(attrs)
    attrs.setdefault("forceaspect", forceaspect)
    video = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(name, f'<Theme>\r\n    <video {video} type="none"/>\r\n</Theme>\r\n')
    return path


def _cabinet(tmp_path, wheels, hidden=(), resolution=(1920, 1080)):
    """A HyperSpin folder.  *wheels* maps wheel name -> dict with ``box``
    (the main theme's ``<video>`` attributes, or None for no theme),
    ``forceaspect``, ``videos`` (file name -> bytes), ``own`` (game name ->
    ``<video>`` attributes of its own ``Themes/<game>.zip``), ``art`` (games
    with wheel art), and the database: ``games`` (names), ``db`` (its XML
    games, or None for no database), else one game per video."""
    hs = tmp_path / "HyperSpin"
    menu = "".join(f'<game name="{w}" enabled="False"/>' if w in hidden else f'<game name="{w}"/>'
                   for w in wheels)
    _write(hs / "Databases" / "Main Menu" / "Main Menu.xml", f"<menu>{menu}</menu>")
    _write(hs / "Settings" / "Settings.ini",
           "[Main]\nMenu_Mode=hyperspin\n\n"
           + (f"[Resolution]\nFullScreen=true\nWidth={resolution[0]}\nHeight={resolution[1]}\n"
              if resolution else ""))
    for wheel, spec in wheels.items():
        if "db" in spec:
            db = spec["db"]
        else:
            names = spec.get("games") or sorted({v.rsplit(".", 1)[0] for v in spec.get("videos", {})}) or ["g1"]
            db = "".join(f'<game name="{g}"><description>{g}</description></game>' for g in names)
        if db is not None:
            _write(hs / "Databases" / wheel / f"{wheel}.xml", f"<menu>{db}</menu>")
        _write(hs / "Settings" / f"{wheel}.ini", spec.get("ini", "[filters]\nwheels_only=false\n"))
        if spec.get("box") is not None:
            _theme_zip(hs / "Media" / wheel / "Themes" / spec.get("zip_name", "Default.zip"),
                       spec["box"], spec.get("forceaspect", "both"))
        for game, attrs in spec.get("own", {}).items():
            _theme_zip(hs / "Media" / wheel / "Themes" / f"{game}.zip", attrs)
        for name, data in spec.get("videos", {}).items():
            _write(hs / "Media" / wheel / "Video" / name, data)
        for game in spec.get("art", ()):
            _write(hs / "Media" / wheel / "Images" / "Wheel" / f"{game}.png", b"")
    return Config(roms_dir=str(tmp_path / "Games"), hyperspin_dir=str(hs)), hs


def _node(chk, system):
    return next(c for c in chk.children if c.name == system)


# ── video_frame_size ────────────────────────────────────────────────────────

def test_frame_size_from_an_mp4_track_header(tmp_path):
    assert video_frame_size(_write(tmp_path / "a.mp4", _mp4(256, 384))) == (256, 384)
    assert video_frame_size(_write(tmp_path / "b.mp4", _mp4(640, 480, version=1))) == (640, 480)
    assert video_frame_size(_write(tmp_path / "c.mov", _mp4(240, 288, mdat_first=False))) == (240, 288)


def test_frame_size_skips_a_track_with_no_size(tmp_path):
    assert video_frame_size(_write(tmp_path / "a.m4v", _mp4(320, 240, audio_first=True))) == (320, 240)


def test_frame_size_from_flv_metadata(tmp_path):
    assert video_frame_size(_write(tmp_path / "a.flv", _flv(320.0, 240.0))) == (320, 240)


def test_frame_size_unknown(tmp_path):
    assert video_frame_size(_write(tmp_path / "a.avi", _mp4(320, 240))) is None
    assert video_frame_size(_write(tmp_path / "b.mp4", b"not a video at all")) is None
    assert video_frame_size(_write(tmp_path / "c.flv", b"FLV\x01" + b"\x00" * 60)) is None
    assert video_frame_size(_write(tmp_path / "d.mp4", _mp4(0, 0))) is None
    assert video_frame_size(tmp_path / "missing.mp4") is None


# ── Theme video shape ───────────────────────────────────────────────────────

def test_full_screen_box_with_tall_handheld_videos_warns(tmp_path):
    cfg, hs = _cabinet(tmp_path, {"Nintendo DSi": {
        "box": FULL_SCREEN, "videos": {f"g{i}.mp4": _mp4(256, 384) for i in range(3)}}})
    chk = health.check_theme_video_shape(cfg)
    node = _node(chk, "Nintendo DSi")
    assert chk.status == WARN and node.status == WARN
    assert node.detail == ("its videos play 2.7x too wide: the theme's video box is 16:9 on the "
                           "1920x1080 screen, its videos are 2:3 (the usual shape of 3 read)")
    assert str(hs / "Media" / "Nintendo DSi" / "Themes" / "Default.zip") in node.fix
    assert 'w x 1.875 : h x 1.406 = video width : height (now w="1024" h="768")' in node.fix
    assert chk.detail == "1 of 1 wheel theme checked stretches the videos out of shape"


def test_box_in_the_videos_shape_on_screen_is_ok(tmp_path):
    # 313.6 x 501.8 canvas units = 588 x 705.7 px on a 1920x1080 screen: 5:6, as 240x288 clips.
    cfg, _hs = _cabinet(tmp_path, {"Nintendo 3DS": {
        "box": {"w": "313.6", "h": "501.8", "x": "280", "y": "420.1"},
        "videos": {"a.mp4": _mp4(240, 288), "b.mp4": _mp4(240, 288)}}})
    chk = health.check_theme_video_shape(cfg)
    assert chk.status == OK and not chk.children
    assert chk.detail == "the video box of 1 wheel theme matches the videos' shape"


def test_4x3_videos_full_screen_depend_on_the_screen(tmp_path):
    wheels = {"Atari 2600": {"box": FULL_SCREEN, "videos": {"a.mp4": _mp4(640, 480)}}}
    cfg, _hs = _cabinet(tmp_path / "wide", wheels)
    node = _node(health.check_theme_video_shape(cfg), "Atari 2600")
    assert node.status == WARN and node.detail.startswith("its videos play 1.3x too wide:")
    cfg, _hs = _cabinet(tmp_path / "square", wheels, resolution=(1024, 768))
    chk = health.check_theme_video_shape(cfg)
    assert chk.status == OK and not chk.children


def test_wide_videos_in_a_tall_box_are_too_tall(tmp_path):
    cfg, _hs = _cabinet(tmp_path, {"Nintendo Virtual Boy": {
        "box": {"w": "404", "h": "411"}, "videos": {"a.mp4": _mp4(384, 224)}}})
    node = _node(health.check_theme_video_shape(cfg), "Nintendo Virtual Boy")
    assert node.status == WARN and node.detail.startswith("its videos play 1.3x too tall:")


def test_small_differences_pass(tmp_path):
    # 203.5 x 518.9 units = 0.52:1 on screen for 2:3 clips: 1.27x narrow, under the limit.
    cfg, _hs = _cabinet(tmp_path, {"Nintendo DS": {
        "box": {"w": "203.5", "h": "518.9"}, "videos": {"a.mp4": _mp4(256, 384)}}})
    assert health.check_theme_video_shape(cfg).status == OK


def test_the_usual_shape_wins(tmp_path):
    videos = {f"g{i}.mp4": _mp4(256, 384) for i in range(5)}
    videos["odd.mp4"] = _mp4(720, 480)
    videos["odd.flv"] = _flv(720, 480)
    cfg, _hs = _cabinet(tmp_path, {"Nintendo DSi": {"box": FULL_SCREEN, "videos": videos}})
    node = _node(health.check_theme_video_shape(cfg), "Nintendo DSi")
    # One video per game (the .mp4 before the .flv), so 6 games' videos.
    assert "its videos are 2:3 (the usual shape of 6 read)" in node.detail
    assert ('Not all its videos are that shape (1 of the 6 read is 3:2: "odd"), and one box '
            "can't fit them all: give those games their own copy of the theme") in node.fix


def test_flv_videos_are_read(tmp_path):
    cfg, _hs = _cabinet(tmp_path, {"Old Wheel": {"box": FULL_SCREEN, "videos": {"a.flv": _flv(320, 240)}}})
    node = _node(health.check_theme_video_shape(cfg), "Old Wheel")
    assert "its videos are 4:3" in node.detail


def test_video_folder_redirect_is_followed(tmp_path):
    shared = tmp_path / "Shared Video"
    _write(shared / "a.mp4", _mp4(256, 384))
    cfg, _hs = _cabinet(tmp_path, {"Nintendo DSi": {
        "box": FULL_SCREEN, "games": ["a"], "ini": f"[video defaults]\npath={shared}\n"}})
    assert _node(health.check_theme_video_shape(cfg), "Nintendo DSi").status == WARN


def test_skipped_wheels(tmp_path):
    tall = {"a.mp4": _mp4(256, 384)}
    cfg, _hs = _cabinet(tmp_path, {
        "No Theme": {"videos": tall},
        "Other Aspect": {"box": FULL_SCREEN, "forceaspect": "none", "videos": tall},
        "No Videos": {"box": FULL_SCREEN},
        "Unreadable": {"box": FULL_SCREEN, "videos": {"a.mp4": b"junk"}},
        "Bad Box": {"box": {"w": "wide", "h": "768"}, "videos": tall},
        "Hidden": {"box": FULL_SCREEN, "videos": tall},
        # g1's own theme, but g1 has no video (a.mp4 is no game's).
        "Game Theme Only": {"box": FULL_SCREEN, "zip_name": "g1.zip", "games": ["g1"], "videos": tall},
    }, hidden=("Hidden",))
    chk = health.check_theme_video_shape(cfg)
    assert chk.status == OK and not chk.children
    assert chk.detail == 'no wheel or game theme with forceaspect="both" and readable videos to check'


def test_theme_names_and_attributes_in_any_case(tmp_path):
    cfg, hs = _cabinet(tmp_path, {"Nintendo DSi": {"videos": {"a.mp4": _mp4(256, 384)}}})
    zf = hs / "Media" / "Nintendo DSi" / "Themes" / "default.ZIP"
    _theme_zip(zf, {"W": "1024", "H": "768"}, forceaspect="Both", name="theme.XML")
    node = _node(health.check_theme_video_shape(cfg), "Nintendo DSi")
    assert node.status == WARN and str(zf) in node.fix


def test_no_resolution_or_no_hyperspin_is_info(tmp_path):
    cfg, _hs = _cabinet(tmp_path / "a", {"X": {"box": FULL_SCREEN, "videos": {"a.mp4": _mp4(256, 384)}}},
                        resolution=None)
    chk = health.check_theme_video_shape(cfg)
    assert chk.status == INFO and "no [Resolution] Width / Height" in chk.detail
    chk = health.check_theme_video_shape(Config(roms_dir=str(tmp_path / "G"), hyperspin_dir=str(tmp_path / "none")))
    assert chk.status == INFO and "skipping" in chk.detail


# ── which games use which theme ─────────────────────────────────────────────

def test_main_theme_no_game_uses_is_skipped(tmp_path):
    # Every game has its own theme in its video's shape, so nobody sees the full-screen main theme.
    cfg, _hs = _cabinet(tmp_path, {"Nintendo 3DS": {
        "box": FULL_SCREEN,
        "own": {"a": {"w": "313.6", "h": "501.8"}, "b": {"w": "313.6", "h": "501.8"}},
        "videos": {"a.mp4": _mp4(240, 288), "b.mp4": _mp4(240, 288)}}})
    chk = health.check_theme_video_shape(cfg)
    assert chk.status == OK and not chk.children
    assert chk.detail == ("the video box of 2 game themes match the videos' shape; "
                          "1 wheel theme that no game uses (each has its own) was skipped")


def test_main_theme_is_judged_by_the_games_that_use_it(tmp_path):
    # Two 4:3 games on the 4:3 main theme; five tall games with tall themes of their own.
    tall = {f"t{i}": BOX_3X4 for i in range(5)}
    videos = {f"t{i}.mp4": _mp4(480, 640) for i in range(5)}
    videos.update({"a.mp4": _mp4(640, 480), "b.flv": _flv(640, 480)})
    cfg, _hs = _cabinet(tmp_path, {"CAVE": {"box": BOX_4X3, "own": tall, "videos": videos}})
    chk = health.check_theme_video_shape(cfg)
    assert chk.status == OK and not chk.children
    assert chk.detail == "the video box of 1 wheel theme and 5 game themes match the videos' shape"
    node = health._theme_shape_node(cfg, "CAVE", (1920, 1080), ["a.mp4", "b.flv"])
    assert node.status == OK and "its videos are 4:3 (the usual shape of 2 read)" in node.detail
    # By all its videos (the usual shape 3:4), the same main theme would look 1.8x too wide.
    assert health._theme_shape_node(cfg, "CAVE", (1920, 1080)).status == WARN


def test_a_game_theme_that_stretches_its_video_warns(tmp_path):
    cfg, hs = _cabinet(tmp_path, {"Sega Naomi": {
        "own": {"wide": FULL_SCREEN, "right": BOX_4X3, "tall": BOX_4X3,
                "other aspect": dict(FULL_SCREEN, forceaspect="none"), "no video": FULL_SCREEN},
        "games": ["wide", "right", "tall", "other aspect", "no video"],
        "videos": {"wide.mp4": _mp4(640, 480), "right.mp4": _mp4(640, 480), "tall.mp4": _mp4(480, 640),
                   "other aspect.mp4": _mp4(640, 480)}}})
    chk = health.check_theme_video_shape(cfg)
    node = _node(chk, "Sega Naomi (games' own themes)")
    assert chk.status == WARN and node.status == WARN and len(chk.children) == 1
    assert node.detail == ("2 of 3 games' own themes stretch their video: "
                           '"wide" (1.3x too wide), "tall" (1.8x too wide)')
    assert str(hs / "Media" / "Sega Naomi" / "Themes") + "\\<game>.zip" in node.fix
    assert "give <video> its video's shape on screen, w x 1.875 : h x 1.406 = video width : height" in node.fix
    assert chk.detail == "2 of 3 game themes checked stretch the videos out of shape"


def test_one_game_theme_reads_in_the_singular(tmp_path):
    cfg, _hs = _cabinet(tmp_path, {"Nintendo Game Boy Color": {
        "own": {"zelda": FULL_SCREEN}, "videos": {"zelda.mp4": _mp4(534, 480)}}})
    chk = health.check_theme_video_shape(cfg)
    assert _node(chk, "Nintendo Game Boy Color (games' own themes)").detail == (
        "1 of 1 game's own theme stretches its video: \"zelda\" (1.6x too wide)")
    assert chk.detail == "1 of 1 game theme checked stretches the videos out of shape"


def test_games_not_on_the_wheel_dont_count(tmp_path):
    # Commented out, switched off, or (wheels_only) without wheel art: only "a" is on the wheel,
    # and it has its own theme, so the full-screen main theme is skipped.
    db = ('<game name="a"><description>A</description></game>'
          '<!-- <game name="gone"><description>Gone</description></game> -->'
          '<game name="off"><description>Off</description><enabled>No</enabled></game>'
          '<game name="no art"><description>No art</description></game>')
    tall = _mp4(256, 384)
    cfg, _hs = _cabinet(tmp_path, {"Nintendo DSi": {
        "box": FULL_SCREEN, "db": db, "own": {"a": {"w": "203.5", "h": "518.9"}, "no art": FULL_SCREEN},
        "art": ["a", "off"], "ini": "[filters]\nwheels_only=true\n",
        "videos": {"a.mp4": tall, "gone.mp4": tall, "off.mp4": tall, "no art.mp4": tall}}})
    chk = health.check_theme_video_shape(cfg)
    assert chk.status == OK and not chk.children
    assert chk.detail.endswith("1 wheel theme that no game uses (each has its own) was skipped")


def test_clones_use_their_parents_theme_and_video_when_set(tmp_path):
    db = ('<game name="pac"><description>P</description></game>'
          '<game name="pacc"><description>C</description><cloneof>pac</cloneof></game>')
    spec = {"box": BOX_3X4, "db": db, "own": {"pac": FULL_SCREEN}, "videos": {"pac.mp4": _mp4(640, 480)}}
    on = dict(spec, ini="[themes]\nuse_parent_vids=true\nuse_parent_themes=true\n")
    cfg, _hs = _cabinet(tmp_path / "on", {"MAME": on})
    chk = health.check_theme_video_shape(cfg)
    assert _node(chk, "MAME (games' own themes)").detail.startswith(
        '2 of 2 games\' own themes stretch their video: "pac" (1.3x too wide), "pacc" (1.3x too wide)')
    assert chk.detail.endswith("1 wheel theme that no game uses (each has its own) was skipped")
    # Off: the clone has no video of its own, so only the parent's theme is judged.
    cfg, _hs = _cabinet(tmp_path / "off", {"MAME": spec})
    chk = health.check_theme_video_shape(cfg)
    assert chk.detail == "1 of 1 game theme checked stretches the videos out of shape"
    # Videos only (any case): the clone plays the parent's 4:3 video in the tall main theme.
    vids = dict(spec, ini="[Themes]\nUse_Parent_Vids=TRUE\n")
    cfg, _hs = _cabinet(tmp_path / "vids", {"MAME": vids})
    node = _node(health.check_theme_video_shape(cfg), "MAME")
    assert node.status == WARN and node.detail.startswith("its videos play 1.8x too tall")


def test_videos_of_another_shape_on_the_main_theme_are_info(tmp_path):
    videos = {f"w{i}.mp4": _mp4(640, 480) for i in range(5)}
    videos.update({"Tall B.mp4": _mp4(480, 640), "tall a.mp4": _mp4(480, 640)})
    cfg, hs = _cabinet(tmp_path, {"Nintendo Arcade Systems": {"box": BOX_4X3, "videos": videos}})
    chk = health.check_theme_video_shape(cfg)
    node = _node(chk, "Nintendo Arcade Systems")
    assert chk.status == INFO and node.status == INFO
    assert node.detail == ('some videos are another shape and play stretched (2 of the 7 read are 3:4: '
                           '"tall a", "Tall B"); the theme\'s video box is 4:3 on the 1920x1080 screen, '
                           "its videos are 4:3 (the usual shape of 7 read)")
    assert node.fix == ("One box can't fit videos of two shapes: give those games their own copy of the theme, "
                        f"{hs / 'Media' / 'Nintendo Arcade Systems' / 'Themes'}\\<game>.zip, with a box of "
                        "their shape (w x 1.875 : h x 1.406 = video width : height)")
    assert chk.detail == ("the video box of 1 wheel theme matches the videos' shape; "
                          "1 wheel theme also stretches the videos of another shape than most")


def test_no_database_judges_the_main_theme_by_all_videos(tmp_path):
    cfg, _hs = _cabinet(tmp_path, {"Nintendo DSi": {
        "box": FULL_SCREEN, "db": None, "videos": {"x.mp4": _mp4(256, 384), "y.mp4": _mp4(256, 384)}}})
    node = _node(health.check_theme_video_shape(cfg), "Nintendo DSi")
    assert node.status == WARN and "(the usual shape of 2 read)" in node.detail


def test_registered_in_doctor():
    import inspect

    assert 'check_theme_video_shape(config)' in inspect.getsource(health.run_health_checks)
