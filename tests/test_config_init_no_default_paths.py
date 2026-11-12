"""`spindoctor config init` never offers or saves a path the user didn't type."""
from __future__ import annotations

from click.testing import CliRunner

from spindoctor.cli import _INIT_FIELDS, cli
from spindoctor.config import load_config


def test_init_fields_have_no_default_paths():
    for field in _INIT_FIELDS:
        assert len(field) == 3, field
        assert ":\\" not in field[1] and ":/" not in field[1], field


def test_required_paths_must_be_typed_and_optional_ones_stay_blank(config_home, tmp_path):
    roms, hs, emus, rl = (str(tmp_path / n) for n in ("roms", "hs", "emus", "rl"))
    required = [roms, hs, emus, rl]
    optional_count = sum(1 for f in _INIT_FIELDS if f[2])
    # A blank answer to a required prompt is re-asked, so the first ""
    # is consumed and the real path is taken next.
    answers = ["", roms, hs, emus, rl] + [""] * optional_count + ["y"]
    result = CliRunner().invoke(cli, ["config", "init"], input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    assert "D:\\" not in result.output and "C:\\LEDBlinky" not in result.output
    cfg = load_config()
    assert [cfg.roms_dir, cfg.hyperspin_dir, cfg.emulators_dir, cfg.rocketlauncher_dir] == required
    for key, _label, allow_blank in _INIT_FIELDS:
        if allow_blank:
            assert getattr(cfg, key) == "", key
