"""Tests for the cute_* animation set (spindoctor.lwax_cute) and `ledblinky lwax cute`.

The 60 built-in themes are checked against the files first made by the C#
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

# First 16 hex digits of the SHA-256 of each reference file
# (New-CuteLwax.ps1 under Windows PowerShell 5.1 / .NET Framework 4.8).
REFERENCE_SHA256 = {
    "cute_gumball_roll": "33ade5d05969fd61",
    "cute_gumball_roll_sunset_sorbet": "fa5b46864840673d",
    "cute_gumball_roll_sea_glass": "309f0a99d9d7de35",
    "cute_fairy_lights": "731fcdec1f41c2ca",
    "cute_fairy_lights_pastel_party": "0ded7df64a10eabe",
    "cute_fairy_lights_winter_frost": "3c68ca9df79ce69d",
    "cute_cotton_candy_clouds": "64eeb77cca819c17",
    "cute_cotton_candy_pink_lemonade": "bd56f4f211f0564d",
    "cute_cotton_candy_sour_apple": "2aeb4ada597f34f7",
    "cute_rainbow_sherbet": "fbc061ee67dc55d1",
    "cute_sherbet_blue_raspberry": "f5f66f75ab9caf9f",
    "cute_sherbet_lavender_honey": "b1a3554c46f839e7",
    "cute_firefly_meadow": "96224906f2fd984b",
    "cute_glowworm_cave": "27f347568a67ea98",
    "cute_lantern_festival": "fd31a8e3cde06e36",
    "cute_koi_pond": "674978a0f82aa13b",
    "cute_koi_moonlight": "cf21a68591743bb1",
    "cute_koi_lily_pads": "0d6dfb4b28f0d9e6",
    "cute_sprinkle_donut": "0d172a7f88ed0932",
    "cute_donut_chocolate": "f3855246391cf0bb",
    "cute_donut_blueberry_glaze": "4492f5cb6cb98ac6",
    "cute_bubble_tea": "3c1a822cf2ccd646",
    "cute_bubble_tea_butterfly_pea": "58310ff7b0caa571",
    "cute_bubble_tea_matcha": "32b05ac147670f85",
    "cute_lollipop_swirl": "6235b68dbc9d6350",
    "cute_lollipop_unicorn": "fa7f196e34ce9909",
    "cute_lollipop_watermelon": "abd3b32989c8500f",
    "cute_sakura_breeze": "f553fda04c8d06ba",
    "cute_autumn_leaves": "29f80c4f5c979d7c",
    "cute_confetti_drift": "1457cf46ed2e4793",
    "cute_sunrise_sunset": "2acdac1747cf6df5",
    "cute_tropical_sunset": "8e3c95583fc0e99d",
    "cute_lavender_morning": "2c5fef3056a0a185",
    "cute_aurora_dance": "4eaf71a4b2476994",
    "cute_aurora_fire_opal": "35c251f90c55a52c",
    "cute_aurora_unicorn": "1a178310206c457f",
    "cute_rainbow_caterpillar": "a5c51c18f87d9f7e",
    "cute_paper_dragon": "1bda54dd498bf810",
    "cute_sea_serpent": "3b7dfb4e8d7eeea9",
    "cute_garden_bloom": "84bcf85fd3e64c77",
    "cute_coral_reef": "d3a8c91e1cb49439",
    "cute_cactus_flowers": "e756335664e12514",
    "cute_candy_cane_stripes": "6527081585a0ce83",
    "cute_circus_tent": "a0edf943062d1553",
    "cute_beach_towel": "ad45a34170d33116",
    "cute_fruit_punch": "c83b72d256084029",
    "cute_berry_smoothie": "d8c672ef40aedc05",
    "cute_galaxy_swirl": "198a07a18523f43d",
    "cute_bouncy_ball": "a09eff6979ee794b",
    "cute_bouncy_beach_ball": "1fab598c6cc070ff",
    "cute_bouncy_bubble": "82f533eeb5b4ad0e",
    "cute_mermaid_scales": "1e0cc9f15da4bc22",
    "cute_dragon_scales": "bd212391602595f3",
    "cute_rose_gold_scales": "ad7a6325296e5cd0",
    "cute_starry_lullaby": "ae4381e042e961de",
    "cute_candy_stars": "ab8c74fba71be264",
    "cute_starfish_lagoon": "b06f911de008e7a9",
    "cute_paw_prints": "2fd50af4771669a7",
    "cute_bunny_hops": "4a4049c08e2330cb",
    "cute_dino_stomps": "9525284330324f85",
}

# One firefly reaches exactly sin(pi/4)**2 = 0.5, and one red value lands on
# exactly x.5 before rounding. .NET's Math.Sin and glibc return the correctly
# rounded sin(pi/4); the Windows C runtime that CPython uses returns the next
# double up, so that value rounds to 26 instead of 25 (frame 307, SELECT red).
LIBM_VARIANTS = {
    "cute_firefly_meadow": {"2dda0f36d178f8a8"},
}

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

def test_sixty_themes_three_per_pattern():
    assert len(CUTE_THEMES) == 60
    assert len(CUTE_PATTERNS) == 20
    assert set(REFERENCE_SHA256) == {t.name for t in CUTE_THEMES}
    for key in CUTE_PATTERNS:
        themes = [t for t in CUTE_THEMES if t.pattern == key]
        assert len(themes) == 3, key
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
