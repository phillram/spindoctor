"""``spindoctor generate-media``: what is missing, staging, putting in, undo.

No test here needs Windows, ffmpeg or a network: ffmpeg is a stand-in that
writes small files, and every socket call fails the test.
"""
from __future__ import annotations

import io
import json
import socket
from pathlib import Path

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor import clips, genmedia, media_scan, placeholders
from spindoctor.cli import cli
from spindoctor.config import Config, save_config

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """generate-media must work on a PC with no network at all."""
    def refuse(*_args, **_kwargs):
        raise AssertionError("generate-media used the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """SpinDoctor's own folder, with its import manifests, inside *tmp_path*."""
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", folder)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", folder / "config.json")
    monkeypatch.setattr(genmedia, "CONFIG_DIR", folder)
    monkeypatch.setattr(media_scan, "MANIFEST_DIR", folder / "media_imports")
    return folder


class FakeTools:
    """clips.Tools that writes a few bytes instead of running ffmpeg."""

    def __init__(self):
        self.made = []

    def make_card_clip(self, card: Path, out: Path) -> Path:
        assert card.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        self.made.append(out.name)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"clip of " + out.stem.encode())
        return out

    make_card_flv = make_card_clip


def _png(path: Path, size=(400, 175)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size).save(path)
    return path


def _file(path: Path, data: bytes = b"real media") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _wheel(cfg: Config, system: str, games, ini: str = "") -> None:
    """*games*: ``(name, extra XML)``."""
    rows = "".join(f'<game name="{n}"><description>{n} (USA)</description>{extra}</game>' for n, extra in games)
    _file(cfg.databases_dir / system / f"{system}.xml", f"<menu>{rows}</menu>".encode())
    if ini:
        _file(Path(cfg.hyperspin_dir) / "Settings" / f"{system}.ini", ini.encode())


@pytest.fixture
def cabinet(tmp_path, home) -> Config:
    """NES: Alpha has everything, Bravo a still, Charlie nothing, Delta is
    Alpha's clone, Echo is switched off.  Hidden: only games with a picture."""
    cfg = Config(hyperspin_dir=str(tmp_path / "hs"), output_dir=str(tmp_path / "out"))
    menu = "".join(f'<game name="{m}"/>' for m in ("NES", "Hidden", "MAME", "Favorites"))
    _file(cfg.databases_dir / "Main Menu" / "Main Menu.xml",
          f'<menu>{menu}<game name="Off" enabled="False"/></menu>'.encode())
    _wheel(cfg, "NES", [("Alpha", "<year>1990</year><manufacturer>Maker</manufacturer>"), ("Bravo", ""),
                        ("Charlie", ""), ("Delta", "<cloneof>Alpha</cloneof>"), ("Echo", "<enabled>No</enabled>")],
           "[filters]\nwheels_only=false\n[themes]\nuse_parent_vids=true\n[video defaults]\npath=\n")
    _wheel(cfg, "Hidden", [("Foxtrot", ""), ("Golf", "")], "[filters]\nwheels_only=true\n")
    _wheel(cfg, "MAME", [("alpha", "<year>1990</year><manufacturer>Maker</manufacturer>")])
    _wheel(cfg, "Favorites", [("Alpha", "")])
    _wheel(cfg, "Off", [("Hotel", "")])
    nes = cfg.media_dir / "NES"
    _png(nes / "Images" / "Wheel" / "Alpha.png")
    _file(nes / "Video" / "Alpha.mp4")
    _png(nes / "Video" / "Bravo.png")
    _png(cfg.media_dir / "Hidden" / "Images" / "Wheel" / "Golf.png", (320, 120))
    save_config(cfg)
    return cfg


def _state(cfg, system="NES"):
    return genmedia.wheel_state(cfg, system)


def _by_name(state):
    return {g.name: g for g in state.games}


def _stage(cfg, what="test"):
    return genmedia.Stage.create(genmedia.stage_root(cfg), what)


def _draw(cfg, system="NES", **kwargs):
    jobs, _hidden = genmedia.plan_wheel_pictures(_state(cfg, system), **kwargs)
    stage = _stage(cfg, "wheel pictures")
    assert genmedia.make_wheel_pictures(stage, jobs, config=cfg) == []
    stage.finish()
    return stage


# ─── what is missing ─────────────────────────────────────────────────────────

def test_gaps_are_judged_the_way_hyperspin_looks(cabinet):
    games = _by_name(_state(cabinet))
    assert {n: (g.wheel, g.video) for n, g in games.items()} == {
        "Alpha": ("yes", "yes"), "Bravo": ("no", "still"), "Charlie": ("no", "no"), "Delta": ("no", "parent")}
    assert games["Charlie"].title == "Charlie" and not games["Charlie"].hidden


def test_a_clone_is_missing_its_video_without_use_parent_vids(cabinet):
    ini = Path(cabinet.hyperspin_dir) / "Settings" / "NES.ini"
    ini.write_text("[themes]\nuse_parent_vids=false\n", encoding="utf-8")
    assert _by_name(_state(cabinet))["Delta"].video == "no"
    ini.write_text("[filters]\nparents_only=true\n", encoding="utf-8")
    assert "Delta" not in _by_name(_state(cabinet))


def test_games_without_a_picture_are_hidden_on_a_wheels_only_wheel(cabinet):
    state = _state(cabinet, "Hidden")
    assert state.wheels_only and state.hidden == 1
    assert _by_name(state)["Foxtrot"].hidden and not _by_name(state)["Golf"].hidden


def test_a_video_redirect_is_followed_and_a_missing_one_named(cabinet, tmp_path):
    ini = Path(cabinet.hyperspin_dir) / "Settings" / "NES.ini"
    shared = tmp_path / "shared"
    _file(shared / "Charlie.mp4")
    ini.write_text(f"[video defaults]\npath={shared}\n", encoding="utf-8")
    state = _state(cabinet)
    assert state.video_dir == shared and _by_name(state)["Charlie"].video == "yes"
    assert _by_name(state)["Alpha"].video == "no"  # the wheel's own folder isn't read then
    ini.write_text(f"[video defaults]\npath={tmp_path / 'gone'}\n", encoding="utf-8")
    state = _state(cabinet)
    assert "doesn't exist" in state.video_problem
    assert genmedia.plan_placeholders(state) == []


def test_ignored_games_and_broken_databases(cabinet):
    cabinet.add_ignore("Charlie", "NES")
    assert "Charlie" not in _by_name(_state(cabinet))
    assert _state(cabinet, "Nowhere").problem
    (cabinet.databases_dir / "MAME" / "MAME.xml").write_text("<menu><game", encoding="utf-8")
    assert _state(cabinet, "MAME").problem


def test_an_empty_file_is_not_media(cabinet):
    _file(cabinet.media_dir / "NES" / "Video" / "Charlie.mp4", b"")
    assert _by_name(_state(cabinet))["Charlie"].video == "no"


def test_resolve_wheels(cabinet):
    assert genmedia.resolve_wheels(cabinet, all_systems=True) == ["NES", "Hidden", "MAME"]
    assert genmedia.resolve_wheels(cabinet, ["nes", "NES"]) == ["NES"]
    assert genmedia.resolve_wheels(cabinet, ["Off"]) == ["Off"]  # named, so switched off doesn't matter
    for bad in (["Favorites"], ["Nowhere"], []):
        with pytest.raises(genmedia.GenMediaError):
            genmedia.resolve_wheels(cabinet, bad)


def test_names_with_characters_no_file_can_have():
    assert genmedia.media_stem("Sample: Quest") == "Sample Quest"
    assert genmedia.media_stem("Trailing ") == "Trailing "


# ─── wheel pictures ──────────────────────────────────────────────────────────

def test_hidden_games_get_no_picture_unless_asked(cabinet):
    jobs, hidden = genmedia.plan_wheel_pictures(_state(cabinet, "Hidden"))
    assert jobs == [] and hidden == 1
    jobs, hidden = genmedia.plan_wheel_pictures(_state(cabinet, "Hidden"), show_hidden=True)
    assert [j.game.name for j in jobs] == ["Foxtrot"] and hidden == 0


def test_only_gaps_are_planned_and_patterns_narrow_them(cabinet):
    jobs, _h = genmedia.plan_wheel_pictures(_state(cabinet))
    assert [j.game.name for j in jobs] == ["Bravo", "Charlie", "Delta"]
    jobs, _h = genmedia.plan_wheel_pictures(_state(cabinet), games=["char*"])
    assert [j.game.name for j in jobs] == ["Charlie"]


def test_pictures_already_on_the_pc_are_found(cabinet):
    nes = cabinet.media_dir / "NES" / "Images" / "Wheel"
    _png(nes / "Bravo (USA).png")       # saved under another name, belongs to no game
    mame = cabinet.media_dir / "MAME" / "Images" / "Wheel"
    local = genmedia.LocalPictures(cabinet)
    games = _by_name(_state(cabinet))
    assert local.find(games["Bravo"]) == (nes / "Bravo (USA).png", "saved as Bravo (USA).png")
    assert local.find(games["Delta"])[0] == nes / "Alpha.png"   # its parent's
    assert local.find(games["Charlie"]) == (None, "")
    # Another wheel's only with the same name, year and maker.
    source, note = local.find(_by_name(_state(cabinet, "MAME"))["alpha"])
    assert source == nes / "Alpha.png" and "NES" in note
    _wheel(cabinet, "MAME", [("alpha", "<year>1991</year><manufacturer>Maker</manufacturer>")])
    assert genmedia.LocalPictures(cabinet).find(_by_name(_state(cabinet, "MAME"))["alpha"]) == (None, "")
    assert not mame.exists()


def test_two_pictures_that_could_be_it_are_neither(cabinet):
    nes = cabinet.media_dir / "NES" / "Images" / "Wheel"
    _png(nes / "Bravo (USA).png")
    _png(nes / "Bravo (Japan).png")
    assert genmedia.LocalPictures(cabinet).find(_by_name(_state(cabinet))["Bravo"]) == (None, "")


def test_a_drawn_title_isnt_copied_to_other_games(cabinet):
    stage = _draw(cabinet, games=["Bravo"])
    genmedia.put_in(cabinet, stage, genmedia.plan_put_in(cabinet, stage))
    _wheel(cabinet, "NES", [("Alpha", ""), ("Bravo", ""), ("Kilo", "<cloneof>Bravo</cloneof>")])
    assert genmedia.LocalPictures(cabinet).find(_by_name(_state(cabinet))["Kilo"]) == (None, "")


def test_pictures_are_sized_like_the_wheels_others(cabinet):
    folder = cabinet.media_dir / "MAME" / "Images" / "Wheel"
    for i, size in enumerate([(500, 210)] * 4 + [(2000, 1000)] * 2):
        _png(folder / f"{i}.png", size)
    assert genmedia.typical_size(folder) == (500, 210)
    assert genmedia.typical_size(cabinet.media_dir / "Hidden" / "Images" / "Wheel") == (400, 175)  # one is too few
    stage = _draw(cabinet, "MAME")
    assert Image.open(stage.target(stage.items[0])).size == (500, 210)


# ─── staging ─────────────────────────────────────────────────────────────────

def test_staging_touches_nothing_in_hyperspin(cabinet):
    before = sorted(p for p in Path(cabinet.hyperspin_dir).rglob("*"))
    stage = _draw(cabinet)
    assert sorted(p for p in Path(cabinet.hyperspin_dir).rglob("*")) == before
    assert [i.file for i in stage.items] == [
        f"Media/NES/Images/Wheel/{n}.png" for n in ("Bravo", "Charlie", "Delta")]
    again = genmedia.Stage.load(stage.folder)
    assert again.items == stage.items and not again.put_in_at
    assert genmedia.list_stages(genmedia.stage_root(cabinet))[0].name == stage.name


def test_the_review_page_is_plain_and_local(cabinet):
    stage = _draw(cabinet)
    page = (stage.folder / "review.html").read_text(encoding="utf-8")
    assert "Charlie" in page and "Media/NES/Images/Wheel/Charlie.png" in page
    assert "http" not in page and "<script" not in page


def test_a_hand_copied_batch_keeps_its_marks(cabinet):
    stage = _draw(cabinet)
    folder = stage.folder / "Media" / "NES" / "Images" / "Wheel"
    lists = placeholders.list_files(folder)
    assert len(lists) == 1 and lists[0].name != placeholders.LIST_NAME
    assert placeholders.is_placeholder(folder / "Charlie.png")


def test_stage_files_stay_inside_the_stage(cabinet):
    stage = _stage(cabinet)
    item = genmedia.StageItem("NES", "Alpha", "Alpha", "wheel", "drawn", "../../evil.png")
    with pytest.raises(genmedia.GenMediaError, match="outside"):
        stage.target(item)


def test_find_stage(cabinet):
    root = genmedia.stage_root(cabinet)
    with pytest.raises(genmedia.GenMediaError, match="Nothing is waiting"):
        genmedia.find_stage(root)
    stage = _draw(cabinet)
    assert genmedia.find_stage(root).name == stage.name
    assert genmedia.find_stage(root, stage.name).folder == stage.folder
    assert genmedia.find_stage(root, str(stage.folder)).folder == stage.folder
    with pytest.raises(genmedia.GenMediaError, match="No staged batch"):
        genmedia.find_stage(root, "nope")


# ─── putting in and undo ─────────────────────────────────────────────────────

def test_put_in_fills_empty_places_and_undo_empties_them(cabinet):
    stage = _draw(cabinet)
    plan = genmedia.plan_put_in(cabinet, stage)
    assert [(p.item.game, p.action) for p in plan] == [("Bravo", "new"), ("Charlie", "new"), ("Delta", "new")]
    result = genmedia.put_in(cabinet, stage, plan)
    folder = cabinet.media_dir / "NES" / "Images" / "Wheel"
    assert len(result.imported) == 3 and (folder / "Charlie.png").is_file()
    games = _by_name(_state(cabinet))
    assert games["Charlie"].wheel == "drawn" and games["Alpha"].wheel == "yes"
    assert genmedia.Stage.load(stage.folder).put_in_at
    with pytest.raises(genmedia.GenMediaError):
        genmedia.find_stage(genmedia.stage_root(cabinet))
    manifest, summary = genmedia.undo_put_in()
    assert summary == {"reverted": 3, "errors": []} and not manifest.exists()
    assert not (folder / "Charlie.png").exists() and (folder / "Alpha.png").exists()
    assert not genmedia.Stage.load(stage.folder).put_in_at  # can be put in again
    assert genmedia.undo_put_in() is None


def test_put_in_never_replaces_real_media(cabinet):
    stage = _draw(cabinet)
    folder = cabinet.media_dir / "NES" / "Images" / "Wheel"
    logo = _file(folder / "Charlie.png", b"a logo added meanwhile")
    plan = genmedia.plan_put_in(cabinet, stage)
    assert {p.item.game: p.action for p in plan} == {"Bravo": "new", "Charlie": "skip", "Delta": "new"}
    # Even a plan made before the logo came leaves it alone.
    for p in plan:
        p.action = "new"
    result = genmedia.put_in(cabinet, stage, plan)
    assert logo.read_bytes() == b"a logo added meanwhile"
    assert len(result.imported) == 2 and "exists" in result.skipped[0][1]


def test_a_file_deleted_from_the_stage_is_left_out(cabinet):
    stage = _draw(cabinet)
    stage.target(stage.items[1]).unlink()
    plan = genmedia.plan_put_in(cabinet, stage)
    assert [p.action for p in plan] == ["new", "skip", "new"]


def test_put_in_can_be_narrowed(cabinet):
    stage = _draw(cabinet)
    assert genmedia.plan_put_in(cabinet, stage, systems=["MAME"]) == []
    assert [p.item.game for p in genmedia.plan_put_in(cabinet, stage, games=["b*"])] == ["Bravo"]


def test_redrawing_replaces_drawn_titles_and_undo_brings_them_back(cabinet):
    stage = _draw(cabinet)
    genmedia.put_in(cabinet, stage, genmedia.plan_put_in(cabinet, stage))
    picture = cabinet.media_dir / "NES" / "Images" / "Wheel" / "Charlie.png"
    first = picture.read_bytes()
    assert genmedia.plan_wheel_pictures(_state(cabinet))[0] == []
    jobs, _h = genmedia.plan_wheel_pictures(_state(cabinet), redraw=True)
    again = _stage(cabinet, "gold")
    genmedia.make_wheel_pictures(again, jobs, style="gold", config=cabinet)
    again.finish()
    plan = genmedia.plan_put_in(cabinet, again)
    assert {p.action for p in plan} == {"replace"}
    genmedia.put_in(cabinet, again, plan)
    assert picture.read_bytes() != first and placeholders.is_placeholder(picture)
    assert genmedia.undo_put_in()[1]["errors"] == []
    assert picture.read_bytes() == first


def test_a_copied_picture_is_real_media(cabinet):
    jobs, _h = genmedia.plan_wheel_pictures(_state(cabinet), games=["Delta"],
                                            local=genmedia.LocalPictures(cabinet))
    stage = _stage(cabinet)
    genmedia.make_wheel_pictures(stage, jobs, config=cabinet)
    stage.finish()
    genmedia.put_in(cabinet, stage, genmedia.plan_put_in(cabinet, stage))
    assert _by_name(_state(cabinet))["Delta"].wheel == "yes"
    assert placeholders.list_files(cabinet.media_dir / "NES" / "Images" / "Wheel") == []


# ─── placeholders ────────────────────────────────────────────────────────────

def _placeholders(cfg, kind="clip", **kwargs):
    games = genmedia.plan_placeholders(_state(cfg), **kwargs)
    stage = _stage(cfg, "placeholders")
    assert genmedia.make_placeholders(stage, games, kind=kind, tools=FakeTools()) == []
    stage.finish()
    genmedia.put_in(cfg, stage, genmedia.plan_put_in(cfg, stage))
    return games


def test_placeholders_go_only_to_games_with_nothing(cabinet):
    assert [g.name for g in _placeholders(cabinet)] == ["Charlie"]  # not the still, not the parent's video
    video = cabinet.media_dir / "NES" / "Video" / "Charlie.mp4"
    assert video.is_file() and placeholders.is_placeholder(video)
    assert _by_name(_state(cabinet))["Charlie"].video == "placeholder"
    assert genmedia.plan_placeholders(_state(cabinet)) == []
    assert [g.name for g in genmedia.plan_placeholders(_state(cabinet), redo=True)] == ["Charlie"]


def test_hidden_games_get_no_placeholder_unless_asked(cabinet):
    assert [g.name for g in genmedia.plan_placeholders(_state(cabinet, "Hidden"))] == ["Golf"]
    assert len(genmedia.plan_placeholders(_state(cabinet, "Hidden"), show_hidden=True)) == 2


def test_the_other_kind_takes_the_first_ones_place(cabinet):
    _placeholders(cabinet)
    _placeholders(cabinet, "picture", redo=True)
    folder = cabinet.media_dir / "NES" / "Video"
    assert sorted(p.name for p in folder.iterdir() if p.stem == "Charlie") == ["Charlie.png"]
    assert placeholders.is_placeholder(folder / "Charlie.png")
    assert _by_name(_state(cabinet))["Charlie"].video == "placeholder"


def _recorded(cfg, game="Charlie", media="still", ext=".png"):
    state = _by_name(_state(cfg))[game]
    stage = _stage(cfg, "recordings")
    stage.add(stage.new_item("NES", game, state.title, media, "recorded", state.stem, ext),
              data=b"recorded from the game")
    stage.finish()
    return stage


def test_recorded_media_replaces_a_placeholder_whatever_its_extension(cabinet):
    _placeholders(cabinet)
    folder = cabinet.media_dir / "NES" / "Video"
    stage = _recorded(cabinet)                          # a still beside the placeholder clip
    genmedia.put_in(cabinet, stage, genmedia.plan_put_in(cabinet, stage))
    assert not (folder / "Charlie.mp4").exists()
    assert _by_name(_state(cabinet))["Charlie"].video == "still"
    stage = _recorded(cabinet, "Charlie", "video", ".mp4")   # a video beside the real still
    genmedia.put_in(cabinet, stage, genmedia.plan_put_in(cabinet, stage))
    assert (folder / "Charlie.png").exists() and _by_name(_state(cabinet))["Charlie"].video == "yes"
    stage = _recorded(cabinet, "Charlie", "video", ".mp4")
    assert genmedia.plan_put_in(cabinet, stage)[0].why == "it has a video now"


def test_stand_ins_dont_push_out_a_still_or_a_parents_video(cabinet):
    stage = _stage(cabinet)
    for game in ("Bravo", "Delta"):
        stage.add(stage.new_item("NES", game, game, "video", "clip", game, ".mp4"), data=b"clip")
    stage.finish()
    assert [p.why for p in genmedia.plan_put_in(cabinet, stage)] == [
        "it has a still picture now", "it plays its parent's video"]


def test_the_frontend_clip_is_replaced_and_undone(cabinet):
    old = _file(cabinet.media_dir / "Frontend" / "Video" / "No Video.flv", b"television snow")
    stage = _stage(cabinet, "No Video clip")
    genmedia.make_frontend_clip(stage, tools=FakeTools())
    stage.finish()
    plan = genmedia.plan_put_in(cabinet, stage)
    assert [(p.target, p.action) for p in plan] == [(old, "replace")]
    genmedia.put_in(cabinet, stage, plan)
    assert old.read_bytes().startswith(b"clip of")
    assert not placeholders.is_placeholder(old)  # HyperSpin's own file, not a game's
    assert genmedia.undo_put_in()[1]["errors"] == []
    assert old.read_bytes() == b"television snow"
    assert not (stage.folder / "card.png").exists()


def test_the_frontend_clip_is_never_mixed_with_game_files(cabinet):
    stage = _stage(cabinet)
    genmedia.make_frontend_clip(stage, tools=FakeTools())
    stage.add(stage.new_item("NES", "Charlie", "Charlie", "video", "clip", "Charlie", ".mp4"), data=b"clip")
    stage.finish()
    with pytest.raises(genmedia.GenMediaError, match="by itself"):
        genmedia.put_in(cabinet, stage, genmedia.plan_put_in(cabinet, stage))


# ─── the command ─────────────────────────────────────────────────────────────

def _run(*args, input=None):
    result = CliRunner().invoke(cli, ["generate-media", *args], input=input)
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    return result


def test_list_command(cabinet, tmp_path):
    out = _run("list", "--all", "--details", "--csv", str(tmp_path / "gaps.csv")).output
    assert "Charlie" in out and "wheel picture: none; video: none" in out
    assert "Favorites" not in out and "Hotel" not in out
    assert len((tmp_path / "gaps.csv").read_text(encoding="utf-8").splitlines()) == 1 + 6
    data = json.loads(_run("list", "-s", "Hidden", "--json").output)
    assert data[0]["wheels_only"] and {g["name"]: g["hidden"] for g in data[0]["games"]} == {
        "Foxtrot": True, "Golf": False}
    assert _run("list").exit_code == 1 and _run("list", "-s", "Nowhere").exit_code == 1


def test_pictures_from_dry_run_to_undo(cabinet):
    dry = _run("wheel-pictures", "-s", "NES")
    assert "3 wheel picture(s) to make: 2 drawn, 1 already on this PC." in dry.output
    assert "DRY RUN" in dry.output and not genmedia.stage_root(cabinet).exists()
    made = _run("wheel-pictures", "-s", "NES", "--style", "gold", "--size", "320x100", "--no-copy", "--apply")
    assert "3 file(s) made" in made.output
    stage = genmedia.find_stage(genmedia.stage_root(cabinet))
    assert Image.open(io.BytesIO(stage.target(stage.items[0]).read_bytes())).size == (320, 100)
    folder = cabinet.media_dir / "NES" / "Images" / "Wheel"
    assert "3 file(s) to put in, 0 left out" in _run("put-in").output and not (folder / "Bravo.png").exists()
    assert "3 file(s) put in" in _run("put-in", stage.name, "--apply").output and (folder / "Bravo.png").exists()
    assert "put in" in _run("stages").output
    assert "DRY RUN" in _run("undo").output and (folder / "Bravo.png").exists()
    assert "3 file(s) undone" in _run("undo", "--apply").output and not (folder / "Bravo.png").exists()
    assert "Nothing to undo" in _run("undo").output
    assert "waiting" in _run("stages").output


def test_media_scan_undo_also_takes_a_batch_out(cabinet):
    _run("wheel-pictures", "-s", "NES", "--apply")
    _run("put-in", "--apply")
    folder = cabinet.media_dir / "NES" / "Images" / "Wheel"
    assert (folder / "Bravo.png").exists()
    assert CliRunner().invoke(cli, ["media-scan", "--undo"]).exit_code == 0
    assert not (folder / "Bravo.png").exists()


def test_placeholder_commands(cabinet, monkeypatch):
    monkeypatch.setattr(clips, "find_tools", lambda config: FakeTools())
    assert "1 game(s) have neither" in _run("placeholders", "-s", "NES").output
    _run("placeholders", "-s", "NES", "--apply")
    _run("put-in", "--apply")
    video = cabinet.media_dir / "NES" / "Video" / "Charlie.mp4"
    assert video.exists()
    assert "DRY RUN" in _run("remove", "--all").output and video.exists()
    assert "No placeholders to remove" in _run("remove", "-s", "NES", "-g", "bravo", "--apply").output
    assert "1 removed" in _run("remove", "-s", "NES", "-g", "charlie", "--apply").output and not video.exists()
    assert "No placeholders to remove" in _run("remove", "--all", "--apply").output
    out = _run("placeholders", "--no-video-clip", "--apply").output
    assert "1 file(s) made" in out
    assert "Frontend" in _run("put-in").output


def test_remove_leaves_drawn_titles_unless_asked(cabinet):
    _run("wheel-pictures", "-s", "NES", "--no-copy", "--apply")
    _run("put-in", "--apply")
    picture = cabinet.media_dir / "NES" / "Images" / "Wheel" / "Bravo.png"
    _run("remove", "-s", "NES", "--apply")
    assert picture.exists()
    _run("remove", "-s", "NES", "--kind", "drawn", "--apply")
    assert not picture.exists() and (picture.parent / "Alpha.png").exists()


def test_missing_ffmpeg_stops_clips_but_not_pictures(cabinet, monkeypatch):
    def missing(config):
        raise clips.ClipError("ffmpeg not found. Put it somewhere.")

    monkeypatch.setattr(clips, "find_tools", missing)
    result = _run("placeholders", "-s", "NES", "--apply")
    assert result.exit_code == 1 and "ffmpeg not found" in result.output
    assert "1 file(s) made" in _run("placeholders", "-s", "NES", "--kind", "picture", "--apply").output


def test_a_bad_size_is_refused(cabinet):
    assert _run("wheel-pictures", "-s", "NES", "--size", "huge").exit_code == 2
