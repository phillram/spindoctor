"""Tests for the cute_* animation set (spindoctor.lwax_cute) and `ledblinky lwax cute`.

The 100 built-in themes are checked against the files first made by the C#
generator on the example cabinet, by SHA-256: the port keeps that generator's
arithmetic and seeds a port of .NET's System.Random, so the bytes match.
"""
from __future__ import annotations

import hashlib
import math

import pytest
from click import unstyle
from click.testing import CliRunner

from spindoctor import lwax_cute, lwax_patterns
from spindoctor.cli import cli
from spindoctor.config import Config, save_config
from spindoctor.lwax import parse_input_map
from spindoctor.lwax_cute import (
    CUTE_PATTERNS,
    CUTE_THEMES,
    DotNetRandom,
    build_cute,
    find_theme,
    labels_in_map_order,
)
from spindoctor.lwax_flash import score_animation

from tests.lwax_reference import LIBM_VARIANTS, REFERENCE_SHA256

# (frames, frame ms) per pattern, as in the C# generator. Gumball roll runs
# 36 frames per palette colour; its built-in themes all have 8.
TIMING = {
    "gumball_roll": (288, 42), "fairy_lights": (264, 45), "cotton_candy_clouds": (320, 50),
    "rainbow_sherbet": (300, 45), "firefly_meadow": (360, 45), "koi_pond": (360, 45),
    "sprinkle_donut": (336, 42), "bubble_tea": (320, 45), "lollipop_swirl": (288, 42),
    "sakura_breeze": (360, 45), "sunrise_sunset": (400, 50), "aurora_dance": (360, 45),
    "rainbow_caterpillar": (300, 40), "garden_bloom": (400, 45), "candy_cane_stripes": (270, 45),
    "fruit_punch": (360, 45), "bouncy_ball": (320, 45), "mermaid_scales": (360, 45),
    "starry_lullaby": (400, 45), "paw_prints": (380, 45),
}


@pytest.fixture(scope="module")
def controllers():
    return parse_input_map(lwax_patterns.reference_input_map())


@pytest.fixture(scope="module")
def built(controllers):
    return {theme.name: build_cute(controllers, theme) for theme in CUTE_THEMES}


# ─── System.Random port ───────────────────────────────────────────────────────

def test_dotnet_random_matches_dotnet_framework():
    # Values from `New-Object System.Random <seed>` in Windows PowerShell 5.1.
    r = DotNetRandom(0)
    assert [r.next(), r.next(), r.next(100), r.next_range(-30, 31)] == [1559595546, 1755192844, 76, 4]
    assert r.next_double() == 0.2060331540210327
    r = DotNetRandom(19)
    assert [r.next(27) for _ in range(5)] == [17, 10, 1, 16, 21]
    # Large and negative seeds go through C#'s unchecked int32 wrap-around.
    r = DotNetRandom(2147483647)
    assert [r.next(), r.next()] == [1559595546, 1755192844]
    assert r.next_double() == 0.7680226921886312
    r = DotNetRandom(-123456789)
    assert [r.next(), r.next(1000)] == [1091672793, 177]
    r = DotNetRandom(-2 ** 31)
    assert [r.next(), r.next()] == [1559595546, 1755192844]


def test_dotnet_random_rejects_seeds_outside_int32():
    with pytest.raises(ValueError):
        DotNetRandom(2 ** 31)


# ─── the built-in themes ──────────────────────────────────────────────────────

def test_hundred_themes_five_per_pattern():
    assert len(CUTE_THEMES) == 100
    assert len(CUTE_PATTERNS) == 20
    assert set(REFERENCE_SHA256) == {t.name for t in CUTE_THEMES}
    assert len({t.name for t in CUTE_THEMES}) == 100
    for key in CUTE_PATTERNS:
        themes = [t for t in CUTE_THEMES if t.pattern == key]
        assert len(themes) == 5, key
        assert themes[0].name == f"cute_{key}"  # the original design comes first
    for theme in CUTE_THEMES:
        assert all(ch.isalnum() or ch == "_" for ch in theme.name), theme.name


def test_themes_match_reference_files(built):
    mismatched = []
    for name, animation in built.items():
        digest = hashlib.sha256(animation.render().encode("utf-8")).hexdigest()[:16]
        if digest != REFERENCE_SHA256[name] and digest not in LIBM_VARIANTS.get(name, ()):
            mismatched.append(name)
    assert not mismatched, f"output differs from the reference files: {mismatched}"


def test_frame_counts_and_durations(built):
    for theme in CUTE_THEMES:
        animation = built[theme.name]
        frames, ms = TIMING[theme.pattern]
        assert len(animation.frames) == frames, theme.name
        assert {f.duration_ms for f in animation.frames} == {ms}, theme.name


def test_every_theme_is_smooth_with_no_hard_cuts(built):
    for name, animation in built.items():
        score = score_animation(animation)
        assert score.tier == "smooth", (name, score)
        # Nothing snaps anywhere, the loop seam included.
        assert score.snaps_per_led_hz == 0, (name, score)
        assert score.sync_blink_hz == 0, (name, score)


def test_labels_follow_input_map_order(controllers):
    labels = labels_in_map_order(controllers)
    assert labels[:4] == ["TRACKBALL", "SELECT", "RMOUSE", "LMOUSE"]
    assert len(labels) == 27 == len(set(labels))
    assert set(labels) == set(lwax_cute.PANEL_POS)


def test_trackball_sits_at_2_4():
    assert lwax_cute.PANEL_POS["TRACKBALL"] == (9.0, 2.4)


# ─── custom colourways ────────────────────────────────────────────────────────

def test_custom_colourway_builds_and_stays_smooth(controllers):
    base = find_theme("cute_gumball_roll")
    theme = base.with_changes(name="cute_gumball_mine", p1=[(48, 0, 0), (48, 36, 0), (0, 36, 48)])
    animation = build_cute(controllers, theme)
    assert len(animation.frames) == 36 * 3
    assert score_animation(animation).tier == "smooth"
    # The palette really is used: frame 0 shows only these colours.
    shown = set(animation._resolved_colors()[0].values())
    assert shown <= {(48, 0, 0), (48, 36, 0), (0, 36, 48)}


def test_seed_changes_random_placement_only(controllers):
    base = find_theme("cute_firefly_meadow")
    a = build_cute(controllers, base).render()
    b = build_cute(controllers, base.with_changes(seed=99)).render()
    assert a != b
    assert len(b.split("<Frame ")) == len(a.split("<Frame "))


def test_find_theme_accepts_short_names():
    assert find_theme("koi_moonlight").name == "cute_koi_moonlight"
    assert find_theme("cute_koi_moonlight.lwax").name == "cute_koi_moonlight"
    with pytest.raises(ValueError):
        find_theme("cute_no_such_theme")


@pytest.mark.parametrize("changes, message", [
    ({"p1": [(48, 0, 0)] * 3}, "exactly 4"),                       # koi needs 4 per fish
    ({"p3": [(0, 10, 20)]}, "exactly 2"),                          # two water colours
    ({"p1": [(49, 0, 0)] * 4}, "0-48"),                            # out of range
])
def test_bad_palettes_are_rejected(controllers, changes, message):
    theme = find_theme("cute_koi_pond").with_changes(**changes)
    with pytest.raises(ValueError, match=message):
        build_cute(controllers, theme)


def test_unused_slot_is_rejected(controllers):
    theme = find_theme("cute_lollipop_swirl").with_changes(p2=[(0, 0, 0)])
    with pytest.raises(ValueError, match="doesn't use p2"):
        build_cute(controllers, theme)


def test_unknown_pattern_is_rejected(controllers):
    theme = find_theme("cute_koi_pond").with_changes(pattern="nope")
    with pytest.raises(ValueError, match="Unknown cute pattern"):
        build_cute(controllers, theme)


def test_control_without_panel_position_is_rejected(controllers):
    from dataclasses import replace

    from spindoctor.lwax import LwaxPort

    board = controllers[0]
    ports = list(board.ports)
    ports[-1] = LwaxPort(number=ports[-1].number, label="EXTRA", channel="")
    odd = [replace(board, ports=tuple(ports))] + list(controllers[1:])
    with pytest.raises(ValueError, match="EXTRA"):
        build_cute(odd, find_theme("cute_koi_pond"))


def test_slot_counts_and_meanings_are_described():
    for pattern in CUTE_PATTERNS.values():
        assert pattern.p1 is not None and pattern.p1.meaning
        for _name, slot in pattern.slots():
            if slot is not None:
                assert slot.count_text()


def test_easing_helpers_are_exact_at_the_ends():
    assert lwax_cute._sm(0) == 0 and lwax_cute._sm(1) == 1 and lwax_cute._sm(0.5) == 0.5
    assert lwax_cute._level(25.5) == 26 and lwax_cute._level(24.5) == 24  # half to even
    assert lwax_cute._level(-3) == 0 and lwax_cute._level(60) == 48
    assert math.isclose(lwax_cute._fr(-0.25), 0.75)


# ─── CLI ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def cli_config(home, tmp_path):
    # No ledblinky_dir: the commands fall back to the committed reference map
    # (the re-homed test HOME has no ~/Downloads copy).
    save_config(Config(output_dir=str(tmp_path / "out")))
    return tmp_path / "out"


def test_cli_list_names_every_pattern_and_theme(cli_config):
    result = CliRunner().invoke(cli, ["ledblinky", "lwax", "cute", "--list"])
    assert result.exit_code == 0, result.output
    for key in CUTE_PATTERNS:
        assert key in result.output
    assert "cute_koi_moonlight" in result.output


def test_cli_dry_run_writes_nothing(cli_config):
    result = CliRunner().invoke(cli, ["ledblinky", "lwax", "cute", "--theme", "cute_koi_pond"])
    assert result.exit_code == 0, result.output
    assert "Would write" in result.output and "Smooth" in result.output
    assert not cli_config.exists()


def test_cli_writes_a_builtin_theme(cli_config, controllers):
    result = CliRunner().invoke(cli, ["ledblinky", "lwax", "cute", "--theme", "koi_moonlight", "--apply"])
    assert result.exit_code == 0, result.output
    out = cli_config / "LEDBlinky" / "lwax" / "cute_koi_moonlight.lwax"
    with out.open(encoding="utf-8", newline="") as fh:
        assert fh.read() == build_cute(controllers, find_theme("cute_koi_moonlight")).render()


def test_cli_custom_colourway(cli_config, tmp_path):
    target = tmp_path / "mine.lwax"
    result = CliRunner().invoke(cli, [
        "ledblinky", "lwax", "cute", "--pattern", "gumball_roll",
        "--color", "FF0000", "--color", "FFC000", "--color", "00C0FF",
        "--output", str(target), "--apply",
    ])
    assert result.exit_code == 0, result.output
    assert target.exists()
    assert "108" in result.output  # 3 colours x 36 frames


def test_cli_default_name_marks_a_changed_theme(cli_config):
    result = CliRunner().invoke(cli, [
        "ledblinky", "lwax", "cute", "--theme", "cute_firefly_meadow", "--seed", "42", "--apply",
    ])
    assert result.exit_code == 0, result.output
    assert (cli_config / "LEDBlinky" / "lwax" / "cute_firefly_meadow_custom.lwax").exists()


@pytest.mark.parametrize("args, message", [
    (["--pattern", "nope"], "Unknown cute pattern"),
    (["--theme", "cute_lollipop_swirl", "--color2", "000000"], "--color2"),
    (["--theme", "cute_koi_pond", "--color", "FF0000"], "exactly 4"),
    ([], "--theme or --pattern"),
])
def test_cli_errors(cli_config, args, message):
    result = CliRunner().invoke(cli, ["ledblinky", "lwax", "cute", *args])
    assert result.exit_code == 1
    assert message in unstyle(result.output)
