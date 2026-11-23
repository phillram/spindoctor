"""Drawing titles and "not found" cards."""
from __future__ import annotations

import io

import pytest

from spindoctor import titleart

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


@pytest.mark.parametrize("description, name, title", [
    ("Orbit Runner (USA) (Rev 1)", "orbit", "Orbit Runner"),
    ("Sample Quest, The (Europe)", "", "The Sample Quest"),
    ("Sample Quest, The - Part Two (USA)", "", "The Sample Quest - Part Two"),
    ("Pixel Rally (Disk 2 of 3) (PD)", "", "Pixel Rally - Disk 2"),
    ("Pixel Rally (Side B)", "", "Pixel Rally - Side B"),
    ("Pixel Rally [b1]", "", "Pixel Rally"),
    ("", "pixelrally", "pixelrally"),
    ("[BIOS] Sample", "", "Sample"),
    ("(Untitled)", "", "(Untitled)"),
    ("Comma, Not an Article", "", "Comma, Not an Article"),
])
def test_display_title(description, name, title):
    assert titleart.display_title(description, name) == title


def _open(data: bytes):
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


@pytest.mark.parametrize("style", sorted(titleart.STYLES))
def test_a_drawn_title_is_a_transparent_png_of_the_asked_size(style):
    img = _open(titleart.draw_title("Orbit Runner", style, (400, 175)))
    assert img.format == "PNG" and img.mode == "RGBA" and img.size == (400, 175)
    assert img.info["Software"] == "SpinDoctor"
    alpha = img.getchannel("A")
    box = alpha.getbbox()
    assert box and alpha.getpixel((0, 0)) == 0 and alpha.getpixel((399, 174)) == 0
    # The letters fill the picture and don't touch its edge.
    assert box[0] > 0 and box[1] > 0 and box[2] < 400 and box[3] < 175
    assert box[2] - box[0] > 200 or box[3] - box[1] > 100


def test_styles_differ_and_drawing_is_repeatable():
    one, two = (titleart.draw_title("Orbit Runner", s) for s in ("gold", "chrome"))
    assert one != two
    assert titleart.draw_title("Orbit Runner", "gold") == one


@pytest.mark.parametrize("title", ["X", "A" * 40, "word " * 60, "Pixel Rally - Disk 2", "ドラゴン"])
def test_any_title_fits(title):
    if titleart.font_for(title) is None and not title.isascii():
        pytest.skip("no font with these letters here")
    img = _open(titleart.draw_title(title, size=(300, 120)))
    box = img.getchannel("A").getbbox()
    assert box and box[0] >= 0 and box[2] <= 300 and box[3] <= 120


def test_long_titles_are_split_into_balanced_lines():
    lines, size = titleart.layout("The Sample Quest of the Clockwork Kings",
                                  titleart.font_for("The"), 384, 159, 100)
    assert 2 <= len(lines) <= 4 and size >= 8
    assert " ".join(lines) == "The Sample Quest of the Clockwork Kings"
    dashed, _size = titleart.layout("Pixel Rally - Part Two", titleart.font_for("P"), 200, 159, 100)
    assert all(not line.startswith("-") and not line.endswith("-") for line in dashed)


def test_bad_requests_say_why(tmp_path):
    with pytest.raises(titleart.TitleArtError, match="Unknown style"):
        titleart.draw_title("Orbit Runner", "neon")
    with pytest.raises(titleart.TitleArtError, match="no title"):
        titleart.draw_title("   ")
    bad = tmp_path / "bad.ttf"
    bad.write_bytes(b"not a font")
    with pytest.raises(titleart.TitleArtError, match="Can't use the font"):
        titleart.draw_title("Orbit Runner", font=bad)
    with pytest.raises(titleart.TitleArtError, match="Unknown background"):
        titleart.draw_card("No video found", background="plaid")


def test_without_pillow_it_says_how_to_get_it(monkeypatch):
    monkeypatch.setattr(titleart, "pillow_available", lambda: False)
    with pytest.raises(titleart.TitleArtError, match="Pillow"):
        titleart.draw_title("Orbit Runner")


@pytest.mark.parametrize("background", titleart.BACKGROUNDS)
def test_cards_are_opaque_and_carry_the_title(background):
    plain = _open(titleart.draw_card("No video found", background=background))
    titled = _open(titleart.draw_card("No video found", "Orbit Runner", background))
    assert plain.size == titled.size == titleart.CARD_SIZE and plain.mode == "RGB"
    rgb = titled.tobytes()
    yellow = sum(1 for r, g, b in zip(rgb[0::3], rgb[1::3], rgb[2::3]) if r > 230 and 180 < g < 225 and b < 120)
    assert yellow > 200  # the title's colour
