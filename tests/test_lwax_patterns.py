"""Tests for the LEDBlinky pattern batch generator (spindoctor.lwax_patterns).

Runs the whole batch against this cabinet's committed reference input map
(docs/reference/LEDBlinkyInputMap.xml) and checks the output is well-formed,
in range, uniquely named, and dash-free.
"""
import xml.etree.ElementTree as ET

import pytest

from spindoctor import lwax_patterns
from spindoctor.lwax import parse_input_map


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


def test_every_file_is_valid_xml_and_in_range(generated):
    out_dir, written, _used = generated
    for filename, _frames, _desc in written:
        path = out_dir / filename
        assert path.exists()
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        for intensity in root.iter("Intensity"):
            for value in intensity.get("Value").split(","):
                assert 0 <= int(value) <= 48


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
