"""Intro Video Randomizer — Random.ini parsing, add/remove, list."""
from __future__ import annotations

import pytest

from spindoctor.config import Config
from spindoctor.introvideo import (
    RandomizerIniError,
    add_video,
    get_ini_path,
    list_videos,
    load_randomizer,
    remove_video,
)


def _write_ini(randomizer_dir, videos_dir, intro_mp4, file_list, random_list, extra_lines=""):
    randomizer_dir.mkdir(parents=True, exist_ok=True)
    text = (
        "[Randomize1]\n"
        "Option=1\n"
        f"Folder={videos_dir}\n"
        f"FileToRandomize={intro_mp4}\n"
        f"FileList={'|'.join(file_list)}\n"
        f"RandomList={'|'.join(random_list)}\n"
        f"{extra_lines}"
    )
    (randomizer_dir / "Random.ini").write_text(text, encoding="utf-8")


@pytest.fixture
def layout(tmp_path):
    randomizer_dir = tmp_path / "Intro Video Randomizer"
    videos_dir = randomizer_dir / "Intro Videos"
    videos_dir.mkdir(parents=True)
    (videos_dir / "Backup").mkdir()
    (videos_dir / "Backup" / "stale.mp4").write_bytes(b"stale")
    (videos_dir / "Capcom Intro.mp4").write_bytes(b"a" * 100)
    (videos_dir / "FF16 Victory Theme.mp4").write_bytes(b"b" * 200)
    intro_mp4 = tmp_path / "Intro.mp4"
    _write_ini(
        randomizer_dir, videos_dir, intro_mp4,
        file_list=["Capcom Intro.mp4", "FF16 Victory Theme.mp4"],
        random_list=["Capcom Intro.mp4", "FF16 Victory Theme.mp4"],
    )
    cfg = Config()
    cfg.intro_randomizer_dir = str(randomizer_dir)
    cfg.backup_dir = str(tmp_path / "backups")
    return cfg, randomizer_dir, videos_dir, intro_mp4


def test_get_ini_path_requires_config():
    with pytest.raises(RandomizerIniError):
        get_ini_path(Config())


def test_load_randomizer_parses_pipe_lists(layout):
    cfg, randomizer_dir, videos_dir, _ = layout
    state = load_randomizer(get_ini_path(cfg))
    assert state.option == "1"
    assert state.folder == videos_dir
    assert state.file_list == ["Capcom Intro.mp4", "FF16 Victory Theme.mp4"]
    assert state.random_list == ["Capcom Intro.mp4", "FF16 Victory Theme.mp4"]


def test_load_randomizer_missing_file_raises(tmp_path):
    cfg = Config()
    cfg.intro_randomizer_dir = str(tmp_path / "nope")
    with pytest.raises(RandomizerIniError):
        load_randomizer(get_ini_path(cfg))


def test_load_randomizer_missing_keys_raises(tmp_path):
    randomizer_dir = tmp_path / "rand"
    randomizer_dir.mkdir()
    (randomizer_dir / "Random.ini").write_text("[Randomize1]\nOption=1\n", encoding="utf-8")
    cfg = Config()
    cfg.intro_randomizer_dir = str(randomizer_dir)
    with pytest.raises(RandomizerIniError):
        load_randomizer(get_ini_path(cfg))


def test_list_videos_excludes_backup_subfolder(layout):
    cfg, *_ = layout
    state = load_randomizer(get_ini_path(cfg))
    videos = list_videos(state)
    assert {v.filename for v in videos} == {"Capcom Intro.mp4", "FF16 Victory Theme.mp4"}
    assert all(v.registered for v in videos)


def test_list_videos_surfaces_orphans_and_dangling_entries(layout):
    cfg, randomizer_dir, videos_dir, intro_mp4 = layout
    (videos_dir / "Unregistered.mp4").write_bytes(b"c" * 50)
    _write_ini(
        randomizer_dir, videos_dir, intro_mp4,
        file_list=["Capcom Intro.mp4", "Missing From Disk.mp4"],
        random_list=["Capcom Intro.mp4"],
    )
    state = load_randomizer(get_ini_path(cfg))
    by_name = {v.filename: v for v in list_videos(state)}
    assert by_name["Unregistered.mp4"].on_disk is True
    assert by_name["Unregistered.mp4"].in_file_list is False
    assert by_name["Missing From Disk.mp4"].on_disk is False
    assert by_name["Missing From Disk.mp4"].in_file_list is True
    assert by_name["Capcom Intro.mp4"].registered is True


def test_add_video_dry_run_does_not_touch_disk(layout, tmp_path):
    cfg, randomizer_dir, videos_dir, _ = layout
    source = tmp_path / "new.mp4"
    source.write_bytes(b"new")
    before = (randomizer_dir / "Random.ini").read_text()

    result = add_video(cfg, source, apply=False)

    assert result.copied is True
    assert result.file_list_changed is True
    assert not (videos_dir / "new.mp4").exists()
    assert (randomizer_dir / "Random.ini").read_text() == before


def test_add_video_applies_copy_and_registers(layout, tmp_path):
    cfg, randomizer_dir, videos_dir, _ = layout
    source = tmp_path / "new.mp4"
    source.write_bytes(b"new")

    result = add_video(cfg, source, apply=True)

    assert result.copied is True
    assert (videos_dir / "new.mp4").exists()
    state = load_randomizer(get_ini_path(cfg))
    assert "new.mp4" in state.file_list
    assert "new.mp4" in state.random_list
    # Every other line survives untouched.
    text = (randomizer_dir / "Random.ini").read_text()
    assert "Option=1" in text
    assert f"Folder={videos_dir}" in text


def test_add_video_existing_file_not_overwritten(layout, tmp_path):
    cfg, randomizer_dir, videos_dir, _ = layout
    dest = videos_dir / "Capcom Intro.mp4"
    original_bytes = dest.read_bytes()
    source = tmp_path / "Capcom Intro.mp4"
    source.write_bytes(b"different content, same name")

    result = add_video(cfg, source, apply=True)

    assert result.copied is False
    assert result.already_registered is True
    assert dest.read_bytes() == original_bytes


def test_add_video_missing_source_raises(layout, tmp_path):
    cfg, *_ = layout
    with pytest.raises(RandomizerIniError):
        add_video(cfg, tmp_path / "does-not-exist.mp4", apply=True)


def test_add_video_backs_up_ini_when_configured(layout, tmp_path):
    cfg, randomizer_dir, videos_dir, _ = layout
    source = tmp_path / "new.mp4"
    source.write_bytes(b"new")
    cfg.backup_before_modify = True

    result = add_video(cfg, source, apply=True)

    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert result.backup_path.parent.name == "IntroVideoRandomizer"


def test_remove_video_dry_run_does_not_touch_ini(layout):
    cfg, randomizer_dir, *_ = layout
    before = (randomizer_dir / "Random.ini").read_text()

    result = remove_video(cfg, "Capcom Intro.mp4", apply=False)

    assert result.changed is True
    assert (randomizer_dir / "Random.ini").read_text() == before


def test_remove_video_applies_without_deleting_file(layout):
    cfg, randomizer_dir, videos_dir, _ = layout

    result = remove_video(cfg, "Capcom Intro.mp4", apply=True)

    assert result.changed is True
    state = load_randomizer(get_ini_path(cfg))
    assert "Capcom Intro.mp4" not in state.file_list
    assert "Capcom Intro.mp4" not in state.random_list
    assert "FF16 Victory Theme.mp4" in state.file_list
    assert (videos_dir / "Capcom Intro.mp4").exists()


def test_remove_video_not_registered_is_noop(layout):
    cfg, randomizer_dir, *_ = layout
    before = (randomizer_dir / "Random.ini").read_text()

    result = remove_video(cfg, "Never Heard Of It.mp4", apply=True)

    assert result.changed is False
    assert (randomizer_dir / "Random.ini").read_text() == before


def test_list_videos_matches_case_insensitively(tmp_path):
    # Regression: Random.ini stores one case variant, the on-disk file
    # (and NTFS lookups) use another — must be treated as the same video,
    # not one "on disk, unregistered" plus one "registered, missing".
    randomizer_dir = tmp_path / "rand"
    videos_dir = randomizer_dir / "Intro Videos"
    videos_dir.mkdir(parents=True)
    (videos_dir / "Capcom Intro.mp4").write_bytes(b"data")
    _write_ini(
        randomizer_dir, videos_dir, tmp_path / "Intro.mp4",
        file_list=["capcom intro.mp4"],
        random_list=["capcom intro.mp4"],
    )
    cfg = Config()
    cfg.intro_randomizer_dir = str(randomizer_dir)

    videos = list_videos(load_randomizer(get_ini_path(cfg)))

    assert len(videos) == 1
    v = videos[0]
    assert v.on_disk is True
    assert v.registered is True
    # On-disk casing wins for display.
    assert v.filename == "Capcom Intro.mp4"


def test_add_video_case_insensitive_already_registered(layout, tmp_path):
    cfg, randomizer_dir, videos_dir, _ = layout
    # FileList/RandomList have "Capcom Intro.mp4"; adding a source with a
    # different case for the same name must be recognized as already
    # registered, not appended as a near-duplicate entry.
    source = tmp_path / "capcom intro.mp4"
    source.write_bytes(b"a" * 100)

    result = add_video(cfg, source, apply=True)

    assert result.already_registered is True
    assert result.file_list_changed is False
    assert result.random_list_changed is False
    state = load_randomizer(get_ini_path(cfg))
    assert state.file_list.count("Capcom Intro.mp4") == 1
    assert "capcom intro.mp4" not in state.file_list


def test_remove_video_case_insensitive_match(layout):
    cfg, randomizer_dir, videos_dir, _ = layout

    result = remove_video(cfg, "CAPCOM INTRO.MP4", apply=True)

    assert result.changed is True
    state = load_randomizer(get_ini_path(cfg))
    assert "Capcom Intro.mp4" not in state.file_list
    assert (videos_dir / "Capcom Intro.mp4").exists()


def test_remove_then_readd_round_trip(layout, tmp_path):
    cfg, randomizer_dir, videos_dir, _ = layout
    remove_video(cfg, "Capcom Intro.mp4", apply=True)
    state = load_randomizer(get_ini_path(cfg))
    assert "Capcom Intro.mp4" not in state.random_list

    # File is still on disk, so re-adding just re-registers it.
    result = add_video(cfg, videos_dir / "Capcom Intro.mp4", apply=True)
    assert result.copied is False
    state2 = load_randomizer(get_ini_path(cfg))
    assert "Capcom Intro.mp4" in state2.file_list
    assert "Capcom Intro.mp4" in state2.random_list
