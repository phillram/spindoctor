"""Media-link planning + apply (hardlink / symlink / copy)."""
from __future__ import annotations

from spindoctor.medialink import (
    LinkMode, apply_plan, plan_mirror, remove_target,
)


def _layout(tmp_path):
    media = tmp_path / "Media"
    src = media / "Super Nintendo"
    (src / "Images" / "Wheel").mkdir(parents=True)
    (src / "Images" / "Backgrounds").mkdir(parents=True)
    (src / "Video").mkdir(parents=True)
    (src / "Themes").mkdir(parents=True)
    (src / "Images" / "Wheel" / "Mario.png").write_bytes(b"wheel-bytes")
    (src / "Images" / "Backgrounds" / "Mario.jpg").write_bytes(b"bg-bytes")
    (src / "Video" / "Mario.mp4").write_bytes(b"mp4-bytes")
    theme = src / "Themes" / "Mario"
    theme.mkdir()
    (theme / "Theme.xml").write_bytes(b"<theme/>")
    return media


def test_plan_lists_every_media_asset(tmp_path):
    media = _layout(tmp_path)
    plan = plan_mirror(media, "Super Nintendo", "Favorites", "Mario")
    sources = sorted(a.src.name for a in plan.actions)
    # 3 file assets + 1 directory (Themes/Mario)
    assert "Mario.png" in sources
    assert "Mario.jpg" in sources
    assert "Mario.mp4" in sources
    assert any(a.is_dir for a in plan.actions)


def test_apply_copy_creates_files_and_themes(tmp_path):
    media = _layout(tmp_path)
    plan = plan_mirror(media, "Super Nintendo", "Favorites", "Mario")
    summary = apply_plan(plan, mode=LinkMode.COPY)

    assert summary["copied"] >= 3
    assert (media / "Favorites" / "Images" / "Wheel" / "Mario.png").exists()
    assert (media / "Favorites" / "Themes" / "Mario" / "Theme.xml").exists()


def test_target_rename_collision_resolution(tmp_path):
    """Mirror with a different target stem (collision resolution)."""
    media = _layout(tmp_path)
    plan = plan_mirror(
        media, "Super Nintendo", "Favorites",
        source_stem="Mario", target_stem="Mario (SNES)",
    )
    apply_plan(plan, mode=LinkMode.COPY)
    assert (media / "Favorites" / "Images" / "Wheel" / "Mario (SNES).png").exists()


def test_idempotent_when_target_already_present(tmp_path):
    media = _layout(tmp_path)
    plan = plan_mirror(media, "Super Nintendo", "Favorites", "Mario")
    apply_plan(plan, mode=LinkMode.COPY)
    plan2 = plan_mirror(media, "Super Nintendo", "Favorites", "Mario")
    summary2 = apply_plan(plan2, mode=LinkMode.COPY)
    assert summary2["copied"] == 0
    assert summary2["skipped"] >= 3


def test_remove_target_drops_mirrored_files(tmp_path):
    media = _layout(tmp_path)
    plan = plan_mirror(media, "Super Nintendo", "Favorites", "Mario")
    apply_plan(plan, mode=LinkMode.COPY)
    n = remove_target(media, "Favorites", "Mario")
    assert n >= 3
    assert not (media / "Favorites" / "Images" / "Wheel" / "Mario.png").exists()
    assert not (media / "Favorites" / "Themes" / "Mario").exists()


def test_missing_source_returns_empty_plan(tmp_path):
    plan = plan_mirror(tmp_path / "Media", "Nope", "Favorites", "Mario")
    assert plan.actions == []


def test_zip_theme_is_copied(tmp_path):
    """plan_mirror must copy zip-form themes from the source system.

    HyperSpin themes are almost always distributed as per-game ``.zip``
    files (e.g. ``Media/MAME/Themes/1942.zip``), not as extracted
    subdirectories.  Without them HyperSpin shows no video preview or
    background artwork for games in a synthetic wheel.
    """
    media = tmp_path / "Media"
    themes_dir = media / "MAME" / "Themes"
    themes_dir.mkdir(parents=True)
    (themes_dir / "1942.zip").write_bytes(b"fake-theme-zip")

    plan = plan_mirror(media, "MAME", "Favorites", "1942")
    planned_names = {a.src.name for a in plan.actions if not a.is_dir}

    assert "1942.zip" in planned_names, (
        "Themes/1942.zip must be included in the media mirror plan — "
        "zip-form themes were not being copied, causing no video/background "
        "in synthetic wheels (Favorites, Recently Played, Most Played)."
    )

    apply_plan(plan, mode=LinkMode.COPY)
    dest = media / "Favorites" / "Themes" / "1942.zip"
    assert dest.exists(), "1942.zip was not copied to Media/Favorites/Themes/"


def test_archive_packed_media_is_copied(tmp_path):
    """plan_mirror must include archive-packed media files.

    HyperSpin reads ``.zip``-packed media natively.  Downloaded media packs
    may also use ``.rar``, ``.7z``, ``.lha``, ``.lzh``, ``.gz``, ``.tar``.
    All must be copied to the synthetic wheel's media folder so they are
    not silently skipped during a Favorites / Recently Played / Most Played
    rebuild.
    """
    media = tmp_path / "Media"
    src = media / "MAME" / "Video"
    src.mkdir(parents=True)
    archive_names = [
        "1942.zip", "1942.rar", "1942.7z",
        "1942.lha", "1942.lzh", "1942.gz", "1942.tar",
    ]
    for name in archive_names:
        (src / name).write_bytes(b"fake-archive-bytes")

    plan = plan_mirror(media, "MAME", "Favorites", "1942")
    planned = {a.src.name for a in plan.actions if not a.is_dir}

    for name in archive_names:
        assert name in planned, (
            f"{name} must be included in the media mirror plan — "
            "archive-packed media must not be silently skipped."
        )

    apply_plan(plan, mode=LinkMode.COPY)
    for name in archive_names:
        dest = media / "Favorites" / "Video" / name
        assert dest.exists(), f"{name} was not copied to the Favorites media folder."


def test_titles_directory_is_mirrored(tmp_path):
    """plan_mirror must copy Images/Titles/ files to the synthetic wheel.

    HyperSpin themes display title-screen captures from Images/Titles/.
    This directory was absent from MEDIA_FILE_SUBDIRS — games in synthetic
    wheels showed a blank title-image slot even when the source system had
    the file.
    """
    media = tmp_path / "Media"
    titles_dir = media / "MAME" / "Images" / "Titles"
    titles_dir.mkdir(parents=True)
    (titles_dir / "1942.png").write_bytes(b"title-screen-bytes")

    plan = plan_mirror(media, "MAME", "Favorites", "1942")
    planned = {a.src.name for a in plan.actions if not a.is_dir}

    assert "1942.png" in planned, (
        "Images/Titles/1942.png must be included in the media mirror plan — "
        "title-screen captures were not being copied to synthetic wheels."
    )

    apply_plan(plan, mode=LinkMode.COPY)
    dest = media / "Favorites" / "Images" / "Titles" / "1942.png"
    assert dest.exists(), "1942.png was not copied to Favorites/Images/Titles/"


def test_wmv_and_mpeg_videos_are_mirrored(tmp_path):
    """plan_mirror must copy .wmv and .mpeg/.mpg video files.

    .wmv is the native Windows Media Video format, very common in older
    HyperSpin media packs (especially on Windows 7 cabinets).  .mpeg/.mpg
    appear in legacy packs.  These were absent from _FILE_EXTS and were
    silently skipped during synthetic-wheel media mirroring.
    """
    media = tmp_path / "Media"
    video_dir = media / "MAME" / "Video"
    video_dir.mkdir(parents=True)
    for name in ("1942.wmv", "1942.mpeg", "1942.mpg"):
        (video_dir / name).write_bytes(b"fake-video-bytes")

    plan = plan_mirror(media, "MAME", "Favorites", "1942")
    planned = {a.src.name for a in plan.actions if not a.is_dir}

    for name in ("1942.wmv", "1942.mpeg", "1942.mpg"):
        assert name in planned, (
            f"{name} must be included in the media mirror plan — "
            "Windows video formats were being silently skipped."
        )

    apply_plan(plan, mode=LinkMode.COPY)
    for name in ("1942.wmv", "1942.mpeg", "1942.mpg"):
        dest = media / "Favorites" / "Video" / name
        assert dest.exists(), f"{name} was not copied to Favorites/Video/"
