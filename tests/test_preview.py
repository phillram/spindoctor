"""Tests for the preview / contact-sheet generator."""
from __future__ import annotations

import pytest

import spindoctor.config as config_mod
from spindoctor.config import Config, save_config
from spindoctor.preview import (
    collect_previews,
    collect_previews_including_missing,
    render_contact_sheet_html,
    render_contact_sheet_png,
    render_game_card_html,
    render_system_overview,
)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "spindoctor_home")
    monkeypatch.setattr(
        config_mod, "CONFIG_FILE", tmp_path / "spindoctor_home" / "config.json"
    )
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _make_system(tmp_path, system="nes", games=("Mario", "Zelda"),
                 wheels=("Mario",), backgrounds=(), snaps=(),
                 titles=(), artworks=(), themes=(), videos=()):
    """Create a small HyperSpin tree under tmp_path with the requested media."""
    hs = tmp_path / "hs"
    roms_dir = tmp_path / "roms"
    (roms_dir / system).mkdir(parents=True)

    # Database
    db_dir = hs / "Databases" / system
    db_dir.mkdir(parents=True)
    game_xml = "".join(
        f'<game name="{g}"><description>{g} Display</description>'
        f'<year>198{i}</year><manufacturer>ACME</manufacturer>'
        f'<genre>Action</genre></game>'
        for i, g in enumerate(games)
    )
    (db_dir / f"{system}.xml").write_text(
        f"<menu>{game_xml}</menu>", encoding="utf-8"
    )

    media = hs / "Media" / system
    for d in ("Images/Wheel", "Images/Backgrounds", "Images/Artwork1",
              "Images/Artwork2", "Images/Artwork3", "Video", "Themes"):
        (media / d).mkdir(parents=True, exist_ok=True)

    for stem in wheels:
        (media / "Images" / "Wheel" / f"{stem}.png").write_bytes(b"\x89PNG\r\n")
    for stem in backgrounds:
        (media / "Images" / "Backgrounds" / f"{stem}.png").write_bytes(b"\x89PNG\r\n")
    for stem in artworks:
        (media / "Images" / "Artwork1" / f"{stem}.png").write_bytes(b"\x89PNG\r\n")
    for stem in titles:
        (media / "Images" / "Artwork2" / f"{stem}.png").write_bytes(b"\x89PNG\r\n")
    for stem in snaps:
        (media / "Images" / "Artwork3" / f"{stem}.png").write_bytes(b"\x89PNG\r\n")
    for stem in videos:
        (media / "Video" / f"{stem}.mp4").write_bytes(b"\x00\x00")
    for stem in themes:
        (media / "Themes" / stem).mkdir()

    return roms_dir, hs


def _cfg(roms_dir, hs):
    cfg = Config()
    cfg.roms_dir = str(roms_dir)
    cfg.hyperspin_dir = str(hs)
    save_config(cfg)
    return cfg


# ─── collect_previews ─────────────────────────────────────────────────────────


def test_collect_previews_skips_games_with_no_media(isolated_config, tmp_path):
    roms_dir, hs = _make_system(
        tmp_path,
        games=("Mario", "Zelda"),
        wheels=("Mario",),
    )
    cfg = _cfg(roms_dir, hs)

    items = collect_previews("nes", cfg)
    names = [i.game_name for i in items]
    assert names == ["Mario"]
    assert items[0].wheel is not None
    assert items[0].wheel.name == "Mario.png"
    assert items[0].metadata["year"] == "1980"
    assert items[0].metadata["manufacturer"] == "ACME"
    assert items[0].display_name == "Mario Display"


def test_collect_previews_resolves_all_slots(isolated_config, tmp_path):
    roms_dir, hs = _make_system(
        tmp_path, games=("Mario",),
        wheels=("Mario",), backgrounds=("Mario",), snaps=("Mario",),
        titles=("Mario",), artworks=("Mario",), themes=("Mario",),
        videos=("Mario",),
    )
    cfg = _cfg(roms_dir, hs)

    items = collect_previews("nes", cfg)
    assert len(items) == 1
    item = items[0]
    assert item.wheel is not None and item.wheel.name == "Mario.png"
    assert item.background is not None
    assert item.snap is not None
    assert item.title_img is not None
    assert item.artwork is not None
    assert item.theme is not None and item.theme.is_dir()
    assert item.video is not None and item.video.suffix == ".mp4"


def test_include_missing_keeps_zero_media_games(isolated_config, tmp_path):
    roms_dir, hs = _make_system(
        tmp_path, games=("Mario", "Zelda"),
        wheels=("Mario",),
    )
    cfg = _cfg(roms_dir, hs)

    items = collect_previews_including_missing("nes", cfg)
    assert len(items) == 2
    by_name = {i.game_name: i for i in items}
    assert by_name["Zelda"].wheel is None


# ─── HTML renderers ───────────────────────────────────────────────────────────


def test_render_contact_sheet_html_writes_self_contained(isolated_config, tmp_path):
    roms_dir, hs = _make_system(
        tmp_path, games=("Mario", "Zelda"),
        wheels=("Mario", "Zelda"),
    )
    cfg = _cfg(roms_dir, hs)
    items = collect_previews("nes", cfg)

    out = tmp_path / "out" / "index.html"
    written = render_contact_sheet_html(items, out, columns=4)
    assert written == out
    text = out.read_text(encoding="utf-8")
    assert "<style>" in text
    assert "Mario.png" in text
    assert "Zelda.png" in text
    assert "<link" not in text  # no external CSS
    assert "<script" not in text  # no external JS
    assert "--cols: 4" in text


def test_render_game_card_html_self_contained(isolated_config, tmp_path):
    roms_dir, hs = _make_system(
        tmp_path, games=("Mario",),
        wheels=("Mario",), backgrounds=("Mario",), snaps=("Mario",),
        titles=("Mario",),
    )
    cfg = _cfg(roms_dir, hs)
    items = collect_previews("nes", cfg)

    out = tmp_path / "out" / "mario.html"
    render_game_card_html(items[0], out)
    text = out.read_text(encoding="utf-8")
    assert "<style>" in text
    assert "Mario Display" in text
    assert "ACME" in text
    assert "1980" in text
    assert "Action" in text
    assert "Mario.png" in text  # at least one of the images
    assert "<link" not in text


def test_render_contact_sheet_html_skips_missing_unless_include(
    isolated_config, tmp_path,
):
    roms_dir, hs = _make_system(
        tmp_path, games=("Mario", "Zelda"),
        wheels=("Mario",), backgrounds=("Zelda",),
    )
    cfg = _cfg(roms_dir, hs)
    items = collect_previews("nes", cfg)
    # Both have *some* media so both are in `items`, but only Mario has a wheel.

    out_default = tmp_path / "default.html"
    render_contact_sheet_html(items, out_default)
    text = out_default.read_text(encoding="utf-8")
    assert "Mario Display" in text
    assert "Zelda Display" not in text  # filtered out by missing wheel

    out_all = tmp_path / "all.html"
    render_contact_sheet_html(items, out_all, include_missing=True)
    text_all = out_all.read_text(encoding="utf-8")
    assert "Mario Display" in text_all
    assert "Zelda Display" in text_all
    assert "no wheel" in text_all  # placeholder rendered


# ─── system overview ──────────────────────────────────────────────────────────


def test_render_system_overview_creates_tree(isolated_config, tmp_path):
    roms_dir, hs = _make_system(
        tmp_path, games=("Mario", "Zelda"),
        wheels=("Mario", "Zelda"),
    )
    cfg = _cfg(roms_dir, hs)
    items = collect_previews("nes", cfg)

    out = tmp_path / "preview"
    result = render_system_overview("nes", items, out)

    assert result["index_html"].exists()
    assert (out / "index.html").exists()
    assert (out / "games").is_dir()
    cards = sorted(p.name for p in (out / "games").iterdir())
    assert cards == ["Mario.html", "Zelda.html"]
    assert len(result["cards"]) == 2
    # Index links to cards via relative paths.
    text = (out / "index.html").read_text(encoding="utf-8")
    assert "games/Mario.html" in text
    assert "games/Zelda.html" in text


def test_render_system_overview_html_only_no_png(isolated_config, tmp_path):
    roms_dir, hs = _make_system(tmp_path, games=("Mario",), wheels=("Mario",))
    cfg = _cfg(roms_dir, hs)
    items = collect_previews("nes", cfg)

    out = tmp_path / "preview"
    result = render_system_overview("nes", items, out, formats=("html",))
    assert result["index_png"] is None
    assert not (out / "index.png").exists()


# ─── PNG renderer ─────────────────────────────────────────────────────────────


def test_render_contact_sheet_png_with_pillow(isolated_config, tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    roms_dir, hs = _make_system(tmp_path, games=("Mario",), wheels=("Mario",))
    # Replace the dummy PNG bytes with a real Pillow-readable one.
    real_png = hs / "Media" / "nes" / "Images" / "Wheel" / "Mario.png"
    Image.new("RGB", (50, 50), (200, 80, 80)).save(real_png)

    cfg = _cfg(roms_dir, hs)
    items = collect_previews("nes", cfg)

    out = tmp_path / "sheet.png"
    written = render_contact_sheet_png(items, out, columns=2)
    assert written == out
    assert out.exists()
    img = Image.open(out)
    assert img.size[0] > 0 and img.size[1] > 0


def test_render_contact_sheet_png_falls_back_when_pillow_missing(
    isolated_config, tmp_path, monkeypatch,
):
    # Force the Pillow probe to return None so we hit the HTML fallback.
    import spindoctor.preview as preview_mod
    monkeypatch.setattr(preview_mod, "_try_import_pillow", lambda: None)

    roms_dir, hs = _make_system(tmp_path, games=("Mario",), wheels=("Mario",))
    cfg = _cfg(roms_dir, hs)
    items = collect_previews("nes", cfg)

    out = tmp_path / "sheet.png"
    with pytest.warns(RuntimeWarning, match="Pillow not installed"):
        written = render_contact_sheet_png(items, out)
    # Fell back to .html alongside the requested .png.
    assert written.suffix == ".html"
    assert written.exists()
    assert not out.exists()


def test_collect_previews_handles_jpeg_extension(isolated_config, tmp_path):
    roms_dir, hs = _make_system(tmp_path, games=("Mario",), wheels=())
    # Drop a .jpg wheel instead of .png.
    (hs / "Media" / "nes" / "Images" / "Wheel" / "Mario.jpg").write_bytes(b"\xff\xd8")
    cfg = _cfg(roms_dir, hs)

    items = collect_previews("nes", cfg)
    assert len(items) == 1
    assert items[0].wheel.suffix == ".jpg"
