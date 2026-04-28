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
