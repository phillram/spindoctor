"""Synthetic ownership and theme-pack regressions from the PR review."""
import pytest

from spindoctor import config, favorites, recent, themes


def write(path, data=b"original"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("operation", ["clear", "favorites", "recent"])
def test_real_pc_wheel_is_not_owned_because_it_has_launchers(tmp_path, operation):
    cfg = config.Config(hyperspin_dir=str(tmp_path / "hs"), rocketlauncher_dir=str(tmp_path / "rl"))
    name = "PC Games"
    db = write(cfg.databases_dir / name / f"{name}.xml", b"<menu/>")
    ini = write(tmp_path / "rl" / "Modules" / "PCLauncher" / name / "Game.ini")
    art = write(cfg.media_dir / name / "Images" / "Wheel" / "Game.png")
    with pytest.raises(ValueError, match="non-synthetic"):
        if operation == "clear":
            recent.clear_wheel_artifacts(cfg, name, dry_run=False)
        elif operation == "favorites":
            favorites.rebuild(favorites.FavoriteStore([], name), cfg, skip_launchers=True)
        else:
            recent._build_synthetic_wheel(cfg, name, [], skip_launchers=True)
    assert db.read_bytes() == b"<menu/>"
    assert ini.read_bytes() == art.read_bytes() == b"original"
    assert not (db.parent / ".spindoctor-synthetic").exists()


def test_marked_custom_wheel_remains_rebuildable(tmp_path):
    cfg = config.Config(hyperspin_dir=str(tmp_path / "hs"))
    name = "My Favorites"
    db = write(cfg.databases_dir / name / f"{name}.xml", b"<menu/>")
    write(db.parent / ".spindoctor-synthetic", b"")
    favorites.rebuild(favorites.FavoriteStore([], name), cfg, skip_launchers=True)
    assert db.exists()


def test_community_images_special_a_pack_matches_by_filename(tmp_path):
    cfg = config.Config(hyperspin_dir=str(tmp_path / "hs"))
    target = write(cfg.media_dir / "MAME" / "Images" / "Special A" / "buttons.png")
    source = write(tmp_path / "pack" / "Images" / "Special A" / "buttons.png", b"new art")
    plans = themes.plan_apply(cfg, tmp_path / "pack")
    assert len(plans) == 1
    assert plans[0].source == source and plans[0].target == target
