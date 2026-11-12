"""Tests for the LEDBlinky pattern batch generator (spindoctor.lwax_patterns).

Runs the whole batch against this cabinet's committed reference input map
(docs/reference/LEDBlinkyInputMap.xml) and checks the output is well-formed,
in range, uniquely named, and dash-free; that the files it made before the
cute_* set and _soft twins are unchanged; and that the flash scorer agrees
with the report the example cabinet's animation pool was sorted by.
"""
import hashlib
import xml.etree.ElementTree as ET

import pytest

from spindoctor import lwax_patterns
from spindoctor.lwax import parse_input_map
from spindoctor.lwax_cute import CUTE_THEMES
from spindoctor.lwax_flash import score_lwax


@pytest.fixture(scope="module")
def controllers():
    ref = lwax_patterns.reference_input_map()
    assert ref.exists(), f"committed reference map missing: {ref}"
    return parse_input_map(ref)


@pytest.fixture(scope="module")
def generated(controllers, tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("lwax-patterns")
    written, palette_used = lwax_patterns.generate_batch(controllers, out_dir)
    return out_dir, written, palette_used


def test_generates_a_full_batch(generated):
    _out_dir, written, _used = generated
    # 22 families x 5 + breathe library + cycles -- comfortably over 150.
    assert len(written) > 150


# Families whose builders use only exact arithmetic (no sin/cos/atan2/hypot),
# so their bytes don't depend on the platform's maths library.
_EXACT_FAMILIES = {
    "fade", "sweep", "rain", "confetti", "scroll", "fill", "drain", "checker", "radial", "cyclone",
    "race", "heartbeat", "strobe", "marquee", "bounce", "rowblink", "pulse", "breathe", "candle", "twinkle",
}


def _is_original(name):
    """The 169 files the batch made before the _soft twins and cute_* set."""
    return not name.startswith("cute_") and not name.endswith("_soft.lwax")


def test_original_files_are_unchanged(generated):
    out_dir, written, _used = generated
    names = sorted(f for f, _fr, _d in written)
    assert sum(1 for n in names if _is_original(n)) == 169
    digest = hashlib.sha256()
    count = 0
    for name in names:
        if (_is_original(name) and name.split("_", 1)[0] in _EXACT_FAMILIES
                and name != "breathe_rainbow_slow.lwax"):
            digest.update(name.encode() + b"\0" + (out_dir / name).read_bytes())
            count += 1
    # 143 files, byte for byte as installed on the example cabinet before the
    # cute set and the _soft twins were added (strobes and flashing fill/drain
    # included). A change here means an existing animation changed.
    assert count == 143
    assert digest.hexdigest()[:16] == "fa6ceb754de38f77"


def test_soft_fill_and_drain_twins(generated):
    out_dir, written, _used = generated
    names = {f for f, _fr, _d in written}
    soft = sorted(n for n in names if n.endswith("_soft.lwax"))
    assert len(soft) == 8
    for name in soft:
        assert name.startswith(("fill_", "drain_"))
        assert name.replace("_soft", "") in names  # the flashing original stays
    # Byte for byte the flash-free remakes first made from the installed files.
    for name, expected in (("fill_cyan_fast_soft.lwax", "6885ca135fe1823e"),
                           ("drain_amber_fast_soft.lwax", "d436fd7a50935c3e")):
        assert hashlib.sha256((out_dir / name).read_bytes()).hexdigest()[:16] == expected


def test_batch_includes_the_cute_set(generated):
    _out_dir, written, _used = generated
    names = {f for f, _fr, _d in written}
    assert {f"{t.name}.lwax" for t in CUTE_THEMES} <= names
    assert len(written) == 169 + 8 + 60


def test_flash_scores_match_the_cabinet_report(generated, controllers):
    """The Python scorer agrees with Analyze-LwaxFlash.ps1's report on the
    example cabinet's 169 installed files."""
    out_dir, written, _used = generated
    tiers = {}
    for name, _fr, _d in written:
        tier = score_lwax(out_dir / name, controllers).tier
        if _is_original(name):
            tiers[tier] = tiers.get(tier, 0) + 1
        else:
            assert tier == "smooth", name  # every _soft twin and cute_* file
    assert tiers == {"strobe": 6, "blink": 5, "borderline": 22, "busy": 4, "smooth": 132}

    # A few rows of that report, every metric.
    rows = {
        "strobe_lime_slow.lwax": (240, 10.8, 45, 2.78, 3, 5.56, 5.56, 2.78, 2.78, "strobe"),
        "heartbeat_aqua_fast.lwax": (132, 3.96, 30, 3.03, 4, 0, 0, 3.03, 3.03, "strobe"),
        "checker_orange_yellow_fast.lwax": (16, 3.2, 200, 0, 0, 5, 5, 0, 0, "blink"),
        "fill_cyan_fast.lwax": (60, 1.8, 30, 1.11, 2, 2.22, 2.78, 1.11, 1.11, "borderline"),
        "drain_amber_fast.lwax": (79, 2.37, 30, 1.27, 2.5, 2.11, 2.53, 1.27, 1.27, "borderline"),
    }
    for name, expected in rows.items():
        s = score_lwax(out_dir / name, controllers)
        got = (s.frames, s.loop_sec, s.min_frame_ms, s.panel_flash_hz, s.panel_worst_1s, s.sync_blink_hz,
               s.snaps_per_led_hz, s.max_led_flicker_hz, s.mean_led_flicker_hz, s.tier)
        assert got == expected, name


def test_every_file_is_valid_xml_and_in_range(generated):
    out_dir, written, _used = generated
    checked_values = set()
    for filename, _frames, _desc in written:
        path = out_dir / filename
        # Read/parse each real output once; do not render it again. Repeated
        # intensity vectors need only one integer/range conversion per batch.
        root = ET.parse(path).getroot()
        vectors = {intensity.attrib["Value"] for intensity in root.iter("Intensity")}
        assert vectors, filename
        for vector in vectors - checked_values:
            for value in vector.split(","):
                assert 0 <= int(value) <= 48, (filename, vector)
        checked_values.update(vectors)


def test_file_names_are_clean_and_unique(generated):
    _out_dir, written, _used = generated
    names = [f for f, _fr, _d in written]
    assert len(names) == len(set(names)), "duplicate file names"
    for name in names:
        assert name.endswith(".lwax")
        stem = name[: -len(".lwax")]
        # underscores only -- no spaces, hyphens, or dashes of any kind
        assert all(ch.isalnum() or ch == "_" for ch in stem), name


def test_palette_stays_globally_unique(generated):
    _out_dir, _written, palette_used = generated
    # Every fixed-colour variant consumed a distinct palette colour; must fit.
    assert 0 < palette_used <= len(lwax_patterns.MASTER_PALETTE)
    palette = lwax_patterns.Palette(lwax_patterns.MASTER_PALETTE)
    consumed = palette.take_n(palette_used)
    assert consumed == lwax_patterns.MASTER_PALETTE[:palette_used]
    assert palette.used == palette_used
    assert len({rgb for _shade, _hue, rgb in consumed}) == palette_used
    # Names alone are not sufficient: different shade/hue labels could resolve
    # to identical LED intensities.
    all_rgb = [rgb for _shade, _hue, rgb in lwax_patterns.MASTER_PALETTE]
    assert len(set(all_rgb)) == len(all_rgb)


def test_readme_index_written(generated):
    out_dir, _written, _used = generated
    readme = out_dir / "README.md"
    assert readme.exists()
    assert "pattern library" in readme.read_text(encoding="utf-8").lower()


def test_one_rainbow_variant_per_effect_family(generated):
    _out_dir, written, _used = generated
    names = [f for f, _fr, _d in written]
    # A representative sample of families that must each ship a rainbow variant.
    for family in ("fade", "sweep", "radial", "heartbeat", "ripple", "candle"):
        assert any(n.startswith(f"{family}_rainbow") for n in names), family


def test_calibration_lights_only_requested_controls(controllers):
    anim, legend = lwax_patterns.build_calibration(controllers)
    # Default is the admin row — 6 controls, each a distinct legend colour.
    assert [label for label, _c in legend] == lwax_patterns.ADMIN_LABELS
    assert len({c for _l, c in legend}) == len(legend)  # distinct colour names

    # Exactly the admin labels are lit; everything else is off.
    resolved = anim._resolved_colors()[-1]
    lit = {label for label, rgb in resolved.items() if rgb != (0, 0, 0)}
    assert lit == set(lwax_patterns.ADMIN_LABELS)

    # Output is well-formed XML in range.
    root = ET.fromstring(anim.render())
    for intensity in root.iter("Intensity"):
        for value in intensity.get("Value").split(","):
            assert 0 <= int(value) <= 48


def test_calibration_rejects_unknown_label(controllers):
    with pytest.raises(ValueError):
        lwax_patterns.build_calibration(controllers, labels=["NOPE"])
