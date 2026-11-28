"""Tests for ``spindoctor boot-intros`` (``spindoctor.boot_intros``): consoles'
start-up logos on or off, emulator by emulator.

The fixtures copy the real files' layout: RetroArch's ``key = "value"`` core
options with LF line ends, DuckStation's LF ``settings.ini``, PCSX2's CRLF
``inis\\PCSX2.ini``, melonDS's CRLF ``melonDS.toml``.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor import boot_intros
from spindoctor.boot_intros import read_value, set_value
from spindoctor.cli import cli
from spindoctor.config import Config


# ── reading and writing one line ──────────────────────────────────────────────

def test_opt_value_is_replaced_in_place_and_the_rest_kept():
    text = ('gambatte_audio_resampler = "sinc"\n'
            'gambatte_gb_bootloader = "enabled"\n'
            'gambatte_gb_colorization = "disabled"\n')
    new = set_value(text, "gambatte_gb_bootloader", "disabled", style="opt")
    assert new == text.replace('bootloader = "enabled"', 'bootloader = "disabled"')
    assert read_value(new, "gambatte_gb_bootloader", style="opt") == "disabled"


def test_missing_opt_key_is_added_at_the_end_with_the_files_line_end():
    new = set_value('mgba_solar_sensor_level = "0"', "mgba_skip_bios", "OFF", style="opt")
    assert new == 'mgba_solar_sensor_level = "0"\nmgba_skip_bios = "OFF"\n'
    assert set_value("", "mgba_skip_bios", "OFF", style="opt") == 'mgba_skip_bios = "OFF"\n'


def test_ini_key_is_added_after_the_sections_last_setting_keeping_crlf():
    text = "[EmuCore]\r\nCdvdVerboseReads = false\r\n\r\n[Filenames]\r\nBIOS = scph10000.bin\r\n"
    new = set_value(text, "EnableFastBoot", "false", section="EmuCore")
    assert new == ("[EmuCore]\r\nCdvdVerboseReads = false\r\nEnableFastBoot = false\r\n\r\n"
                   "[Filenames]\r\nBIOS = scph10000.bin\r\n")


def test_ini_keys_and_sections_ignore_case_and_every_copy_is_set():
    text = "[core]\nskipipl = True\nSkipIPL = True\n[Other]\nSkipIPL = True\n"
    new = set_value(text, "SkipIPL", "False", section="Core")
    assert new == "[core]\nskipipl = False\nSkipIPL = False\n[Other]\nSkipIPL = True\n"
    assert read_value(new, "SkipIPL", section="Core") == "False"
    assert read_value(new, "SkipIPL", section="Other") == "True"


def test_missing_section_is_added_at_the_end():
    text = "[Main]\nSettingsVersion = 3\n"
    assert set_value(text, "PatchFastBoot", "true", section="BIOS") == (
        "[Main]\nSettingsVersion = 3\n\n[BIOS]\nPatchFastBoot = true\n")


def test_toml_value_keeps_its_comment_and_other_tables():
    text = "[Emu]\r\nDirectBoot = true # skip the firmware\r\n\r\n[Emu.Other]\r\nDirectBoot = true\r\n"
    new = set_value(text, "DirectBoot", "false", section="Emu", style="toml")
    assert new == ("[Emu]\r\nDirectBoot = false # skip the firmware\r\n\r\n"
                   "[Emu.Other]\r\nDirectBoot = true\r\n")
    assert read_value(new, "DirectBoot", section="Emu", style="toml") == "false"


def test_top_level_key_goes_before_the_first_section():
    assert set_value("[Window]\nx=1\n", "DirectBoot", "0", separator="=") == "DirectBoot=0\n[Window]\nx=1\n"


@pytest.mark.parametrize("value,expected", [
    (None, True), ("enabled", True), ("disabled", False), ("Enabled", True), ("bogus", True),
])
def test_values_count_as_the_core_reads_them(value, expected):
    gambatte = next(s for s in boot_intros.SETTINGS if s.id == "gambatte")
    assert boot_intros.is_on(value, gambatte) is expected


def test_yes_no_words_count_by_meaning():
    dolphin = next(s for s in boot_intros.SETTINGS if s.id == "dolphin")   # SkipIPL: False = logo
    assert boot_intros.is_on("false", dolphin) and boot_intros.is_on("0", dolphin)
    assert not boot_intros.is_on("True", dolphin) and not boot_intros.is_on(None, dolphin)


def test_every_setting_has_a_unique_core_or_exe_and_both_values():
    for s in boot_intros.SETTINGS:
        assert s.on and s.off and s.on != s.off, s.id
        assert bool(s.cores) != bool(s.exes), s.id
        if s.cores:
            assert s.library and s.prefix and s.key.startswith(s.prefix), s.id
    cores = [c for s in boot_intros.SETTINGS for c in s.cores]
    assert len(cores) == len(set(cores))
    assert not set(cores) & set(boot_intros.RETROARCH_NO_SETTING)


# ── a cabinet ─────────────────────────────────────────────────────────────────

def _cabinet(tmp_path, **kw):
    """RocketLauncher and Emulators folders with no emulator installed."""
    rl = tmp_path / "RocketLauncher"
    (rl / "Settings").mkdir(parents=True)
    emus = tmp_path / "Emulators"
    emus.mkdir()
    cfg = Config(rocketlauncher_dir=str(rl), emulators_dir=str(emus), **kw)
    return cfg, rl, emus


def _register(rl, section, exe_rel):
    """Add an emulator entry to Global Emulators.ini, as RocketLauncher writes it."""
    ini = rl / "Settings" / "Global Emulators.ini"
    text = ini.read_text(encoding="utf-8") if ini.exists() else ""
    ini.write_text(text + f"[{section}]\r\nEmu_Path=..\\Emulators\\{exe_rel}\r\nRom_Extension=zip\r\n",
                   encoding="utf-8")


def _put(path, text=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return path


GAMBATTE_OPT = ('gambatte_audio_resampler = "sinc"\n'
                'gambatte_gb_bootloader = "enabled"\n'
                'gambatte_gb_hwmode = "Auto"\n')


def _retroarch(emus, rl, cores=("gambatte_libretro",), cfg=None):
    ra = emus / "RetroArch"
    _put(ra / "retroarch.exe", b"MZ")
    for core in cores:
        _put(ra / "cores" / f"{core}.dll", b"MZ")
    if cfg is not None:
        _put(ra / "retroarch.cfg", cfg)
    _register(rl, "RetroArch", "RetroArch\\retroarch.exe")
    return ra


def _only(found, ident):
    hits = [t for t in found.targets if t.setting.id == ident]
    assert len(hits) == 1, [t.label for t in found.targets]
    return hits[0]


# ── RetroArch cores ───────────────────────────────────────────────────────────

def test_a_games_own_options_file_keeps_its_setting_unless_asked(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path, backup_before_modify=False)
    ra = _retroarch(emus, rl, cores=("genesis_plus_gx_libretro",))
    own = _put(ra / "config" / "Genesis Plus GX" / "Genesis Plus GX.opt", 'genesis_plus_gx_bios = "disabled"\n')
    # A cartridge without "SEGA" in its header, kept off the TMSS BIOS on purpose.
    kept = _put(ra / "config" / "Genesis Plus GX" / "Populous (USA).opt", 'genesis_plus_gx_bios = "disabled"\n')
    _put(ra / "system" / "bios_MD.bin")

    t = _only(boot_intros.survey(cfg), "genesis-plus-gx")
    assert t.files == [own] and t.game_files == [kept]
    result = boot_intros.plan([t], turn_on=True)
    assert [c.file for c in result.changes] == [own]
    assert result.kept == [(t, [kept])]
    boot_intros.write_plan(result, cfg)
    assert kept.read_text(encoding="utf-8") == 'genesis_plus_gx_bios = "disabled"\n'
    assert _only(boot_intros.survey(cfg), "genesis-plus-gx").state is True


def test_core_and_per_game_options_are_both_switched(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    ra = _retroarch(emus, rl)
    own = _put(ra / "config" / "Gambatte" / "Gambatte.opt", GAMBATTE_OPT)
    game = _put(ra / "config" / "Gambatte" / "Tetris (World).opt", GAMBATTE_OPT)
    _put(ra / "system" / "gb_bios.bin")

    t = _only(boot_intros.survey(cfg), "gambatte")
    assert t.label == "Gambatte (RetroArch)" and t.used_by == ["RetroArch"]
    assert t.state is True and t.files == [own] and t.game_files == [game]
    assert t.missing == [f"gbc_bios.bin (Game Boy Color boot ROM) in {ra / 'system'}"]

    result = boot_intros.plan([t], turn_on=False, game_files=True)
    assert [(c.file, c.old, c.new) for c in result.changes] == [
        (own, "enabled", "disabled"), (game, "enabled", "disabled")]
    written = boot_intros.write_plan(result, cfg)
    expected = GAMBATTE_OPT.replace('"enabled"', '"disabled"')
    assert own.read_text(encoding="utf-8") == expected
    assert game.read_text(encoding="utf-8") == expected
    assert all(w.backup is not None and w.backup.read_text(encoding="utf-8") == GAMBATTE_OPT
               for w in written)
    assert _only(boot_intros.survey(cfg), "gambatte").state is False


def test_a_new_core_file_starts_from_the_old_shared_options_file(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path, backup_before_modify=False)
    ra = _retroarch(emus, rl, cores=("mgba_libretro",), cfg='rgui_config_directory = ":\\config"\n')
    _put(ra / "retroarch-core-options.cfg",
         'gambatte_gb_hwmode = "GBC"\nmgba_solar_sensor_level = "3"\n')
    _put(ra / "system" / "gba_bios.bin")

    t = _only(boot_intros.survey(cfg), "mgba")
    assert t.state is True          # mgba_skip_bios defaults to OFF
    result = boot_intros.plan([t], turn_on=False)
    [w] = boot_intros.write_plan(result, cfg)
    assert w.created and w.file == ra / "config" / "mGBA" / "mGBA.opt"
    assert w.file.read_text(encoding="utf-8") == ('mgba_solar_sensor_level = "3"\n'
                                                  'mgba_skip_bios = "ON"\n')


def test_global_core_options_mode_edits_the_shared_file(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path, backup_before_modify=False)
    ra = _retroarch(emus, rl, cores=("genesis_plus_gx_libretro",),
                    cfg='global_core_options = "true"\ncore_options_path = ""\n')
    shared = _put(ra / "retroarch-core-options.cfg", 'genesis_plus_gx_bios = "disabled"\n')
    _put(ra / "system" / "bios_MD.bin")

    t = _only(boot_intros.survey(cfg), "genesis-plus-gx")
    assert t.files == [shared] and t.state is False
    boot_intros.write_plan(boot_intros.plan([t], turn_on=True), cfg)
    assert shared.read_text(encoding="utf-8") == 'genesis_plus_gx_bios = "enabled"\n'


def test_turning_on_without_the_bios_is_refused_and_names_it(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    ra = _retroarch(emus, rl, cores=("genesis_plus_gx_libretro",))
    opt = _put(ra / "config" / "Genesis Plus GX" / "Genesis Plus GX.opt", 'genesis_plus_gx_bios = "disabled"\n')

    result = boot_intros.plan(boot_intros.survey(cfg).targets, turn_on=True)
    assert not result.changes
    [(t, why)] = result.refused
    assert "bios_MD.bin (Mega Drive TMSS BIOS)" in why and "bios.gg (Game Gear BIOS)" in why
    assert opt.read_text(encoding="utf-8") == 'genesis_plus_gx_bios = "disabled"\n'


def test_system_directory_default_means_the_games_own_folder(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    ra = _retroarch(emus, rl, cfg='system_directory = "default"\n')
    _put(ra / "system" / "gb_bios.bin")
    t = _only(boot_intros.survey(cfg), "gambatte")
    assert t.found == [] and "system_directory is \"default\"" in t.missing[0]
    assert boot_intros.plan([t], turn_on=True).refused


def test_configs_rocketlauncher_starts_with_are_followed(tmp_path):
    # No retroarch.cfg: RocketLauncher passes -c config\<System>.cfg, which
    # points the system folder elsewhere.
    cfg, rl, emus = _cabinet(tmp_path)
    ra = _retroarch(emus, rl, cores=("mednafen_psx_hw_libretro",))
    bios = tmp_path / "BIOS"
    _put(bios / "scph5501.bin")
    _put(ra / "config" / "Sony PlayStation.cfg", f'system_directory = "{bios}"\n')
    t = _only(boot_intros.survey(cfg), "beetle-psx-hw")
    assert t.found == [str(bios / "scph5501.bin")]
    assert any(str(ra / "system") in m for m in t.missing)   # the default layout has none
    assert t.can_turn_on is False                            # one BIOS, every layout needs it


def test_pcsx_rearmed_on_hle_bios_is_refused(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    ra = _retroarch(emus, rl, cores=("pcsx_rearmed_libretro",))
    _put(ra / "config" / "PCSX-ReARMed" / "PCSX-ReARMed.opt", 'pcsx_rearmed_bios = "HLE"\n')
    _put(ra / "system" / "scph1001.bin")
    [(t, why)] = boot_intros.plan(boot_intros.survey(cfg).targets, turn_on=True).refused
    assert "HLE" in why and t.state is False


def test_desmume_turns_on_its_external_bios_too(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path, backup_before_modify=False)
    ra = _retroarch(emus, rl, cores=("desmume_libretro",))
    for name in ("bios7.bin", "bios9.bin", "firmware.bin"):
        _put(ra / "system" / name)
    t = _only(boot_intros.survey(cfg), "desmume")
    boot_intros.write_plan(boot_intros.plan([t], turn_on=True), cfg)
    opt = ra / "config" / "DeSmuME" / "DeSmuME.opt"
    assert opt.read_text(encoding="utf-8") == ('desmume_boot_into_bios = "enabled"\n'
                                               'desmume_use_external_bios = "enabled"\n'
                                               'desmume_cpu_mode = "interpreter"\n')
    assert _only(boot_intros.survey(cfg), "desmume").state is True


def test_melonds_ds_firmware_is_found_by_its_contents(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    ra = _retroarch(emus, rl, cores=("melondsds_libretro",))
    _put(ra / "system" / "bios7.bin")
    _put(ra / "system" / "bios9.bin")
    _put(ra / "system" / "scph5501.bin", b"\0" * 262144)                  # right size, no header
    t = _only(boot_intros.survey(cfg), "melonds-ds")
    assert len(t.missing) == 1 and "DS firmware" in t.missing[0]
    fw = _put(ra / "system" / "melonDS DS" / "NTR firmware.bin", b"\0" * 8 + b"MACP" + b"\0" * 262132)
    t = _only(boot_intros.survey(cfg), "melonds-ds")
    assert t.missing == [] and str(fw) in t.found


def test_cores_without_a_setting_are_listed_as_such(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    _retroarch(emus, rl, cores=("mednafen_saturn_libretro", "sameboy_libretro"))
    found = boot_intros.survey(cfg)
    assert found.targets == []
    assert sorted(n.name for n in found.no_setting) == ["Beetle Saturn (RetroArch)", "SameBoy (RetroArch)"]


# ── standalone emulators ──────────────────────────────────────────────────────

DUCK_INI = "[Main]\nSettingsVersion = 3\n\n[BIOS]\nSearchDirectory = bios\n\n[CDROM]\nAutoDiscChange = true\n"


def test_duckstation_portable_settings_get_patch_fast_boot(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path, backup_before_modify=False)
    _put(emus / "DuckStation" / "duckstation-qt-x64-ReleaseLTCG.exe", b"MZ")
    ini = _put(emus / "DuckStation" / "settings.ini", DUCK_INI)
    _register(rl, "DuckStation", "DuckStation\\duckstation-qt-x64-ReleaseLTCG.exe")

    t = _only(boot_intros.survey(cfg), "duckstation")
    assert t.state is True and t.files == [ini]        # PatchFastBoot defaults to false
    boot_intros.write_plan(boot_intros.plan([t], turn_on=False), cfg)
    assert ini.read_bytes() == DUCK_INI.replace(
        "SearchDirectory = bios\n", "SearchDirectory = bios\nPatchFastBoot = true\n").encode()


def test_pcsx2_qt_fast_boot_keeps_crlf_and_pcsx2_1x_has_no_setting(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path, backup_before_modify=False)
    _put(emus / "PCSX2" / "pcsx2-qt.exe", b"MZ")
    _put(emus / "PCSX2" / "portable.ini", "")
    ini = _put(emus / "PCSX2" / "inis" / "PCSX2.ini",
               "[EmuCore]\r\nEnableFastBoot = true\r\nEnableFastBootFastForward = false\r\n")
    _register(rl, "PCSX2", "PCSX2\\pcsx2-qt.exe")
    _put(emus / "PCSX2 1.6" / "pcsx2.exe", b"MZ")
    _register(rl, "PCSX2 1.6", "PCSX2 1.6\\pcsx2.exe")

    found = boot_intros.survey(cfg)
    t = _only(found, "pcsx2")
    assert t.state is False
    assert [(n.name, n.program) for n in found.no_setting] == [("PCSX2 1.x", "PCSX2 1.6")]
    boot_intros.write_plan(boot_intros.plan([t], turn_on=True), cfg)
    assert ini.read_bytes() == (b"[EmuCore]\r\nEnableFastBoot = false\r\n"
                                b"EnableFastBootFastForward = false\r\n")


def test_dolphin_needs_an_ipl_for_every_region(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path, backup_before_modify=False)
    dol = emus / "Dolphin"
    _put(dol / "Dolphin.exe", b"MZ")
    _put(dol / "portable.txt", "")
    ini = _put(dol / "User" / "Config" / "Dolphin.ini", "[General]\nISOPaths = 0\n[Core]\nCPUThread = True\n")
    _register(rl, "Dolphin", "Dolphin\\Dolphin.exe")
    _put(dol / "User" / "GC" / "USA" / "IPL.bin")

    t = _only(boot_intros.survey(cfg), "dolphin")
    assert t.state is False                              # SkipIPL defaults to True
    [(_, why)] = boot_intros.plan([t], turn_on=True).refused
    assert "GameCube IPL, EUR" in why and "GameCube IPL, JAP" in why and "USA" not in why.split(";")[0][:30]

    _put(dol / "Sys" / "GC" / "EUR" / "IPL.bin")
    _put(dol / "Sys" / "GC" / "JAP" / "IPL.bin")
    t = _only(boot_intros.survey(cfg), "dolphin")
    boot_intros.write_plan(boot_intros.plan([t], turn_on=True), cfg)
    assert ini.read_text() == "[General]\nISOPaths = 0\n[Core]\nCPUThread = True\nSkipIPL = False\n"


def test_flycast_off_uses_its_own_bios_and_on_needs_dc_boot(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path, backup_before_modify=False)
    fly = emus / "Flycast"
    _put(fly / "flycast.exe", b"MZ")
    emu = _put(fly / "emu.cfg", "[config]\nDreamcast.BiosPath = \nrend.vsync = yes\n\n[input]\nx = 1\n")
    _register(rl, "Flycast", "Flycast\\flycast.exe")

    t = _only(boot_intros.survey(cfg), "flycast")
    assert t.state is True and not t.can_turn_on
    boot_intros.write_plan(boot_intros.plan([t], turn_on=False), cfg)
    assert emu.read_text() == "[config]\nDreamcast.BiosPath = \nrend.vsync = yes\nUseReios = yes\n\n[input]\nx = 1\n"
    assert "dc_boot.bin or dc_bios.bin" in boot_intros.plan(
        boot_intros.survey(cfg).targets, turn_on=True).refused[0][1]
    _put(fly / "data" / "dc_boot.bin")
    assert boot_intros.plan(boot_intros.survey(cfg).targets, turn_on=True).changes


def test_melonds_on_sets_external_bios_when_its_files_are_set(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path, backup_before_modify=False)
    mel = emus / "melonDS"
    _put(mel / "melonDS.exe", b"MZ")
    toml = _put(mel / "melonDS.toml",
                "[DS]\r\nBIOS9Path = 'bios\\bios9.bin'\r\nBIOS7Path = 'bios\\bios7.bin'\r\n"
                "FirmwarePath = 'bios\\firmware.bin'\r\n\r\n[Emu]\r\nDirectBoot = true\r\n"
                "ExternalBIOSEnable = false\r\n")
    _register(rl, "melonDS", "melonDS\\melonDS.exe")
    t = _only(boot_intros.survey(cfg), "melonds")
    assert len(t.missing) == 3 and not t.can_turn_on

    for name in ("bios9.bin", "bios7.bin", "firmware.bin"):
        _put(mel / "bios" / name)
    t = _only(boot_intros.survey(cfg), "melonds")
    boot_intros.write_plan(boot_intros.plan([t], turn_on=True), cfg)
    text = toml.read_text()
    assert "DirectBoot = false\r\nExternalBIOSEnable = true\r\n" in text.replace("\n", "\r\n").replace("\r\r", "\r")
    assert _only(boot_intros.survey(cfg), "melonds").state is True


def test_without_rocketlauncher_entries_the_emulators_folder_is_read(tmp_path):
    cfg, _rl, emus = _cabinet(tmp_path)
    _put(emus / "xemu" / "xemu.exe", b"MZ")
    _put(emus / "xemu" / "xemu.toml", "[general]\nshow_welcome = false\n")
    t = _only(boot_intros.survey(cfg), "xemu")
    assert t.state is True and t.used_by == []


def test_a_missing_settings_file_is_a_problem_not_a_new_file(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    _put(emus / "xemu" / "xemu.exe", b"MZ")
    _register(rl, "xemu", "xemu\\xemu.exe")
    [t] = boot_intros.survey(cfg).targets
    assert "settings file not found" in t.problem
    assert boot_intros.plan([t], turn_on=False).refused


def test_select_by_name_folder_or_rocketlauncher_name(tmp_path):
    cfg, rl, emus = _cabinet(tmp_path)
    _retroarch(emus, rl, cores=("gambatte_libretro", "mgba_libretro"))
    _put(emus / "SSF" / "SSF.exe", b"MZ")
    _register(rl, "SSF", "SSF\\SSF.exe")
    found = boot_intros.survey(cfg)
    assert [t.setting.id for t in boot_intros.select(found, ["MGBA"])] == ["mgba"]
    assert len(boot_intros.select(found, ["RetroArch"])) == 2
    assert [t.setting.id for t in boot_intros.select(found, ["Gambatte (RetroArch)"])] == ["gambatte"]
    with pytest.raises(boot_intros.BootIntroError) as err:
        boot_intros.select(found, ["ssf"])
    assert "SSF: no such setting" in str(err.value) and "gambatte, mgba" in str(err.value)


# ── the command ───────────────────────────────────────────────────────────────

@pytest.fixture
def saved(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home / ".spindoctor")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / ".spindoctor" / "config.json")
    config_mod.reset_override_cache()
    cfg, rl, emus = _cabinet(tmp_path)
    config_mod.save_config(cfg)
    _put(emus / "DuckStation" / "duckstation-qt-x64-ReleaseLTCG.exe", b"MZ")
    ini = _put(emus / "DuckStation" / "settings.ini", DUCK_INI)
    _register(rl, "DuckStation (PS1)", "DuckStation\\duckstation-qt-x64-ReleaseLTCG.exe")
    _put(emus / "SSF" / "SSF.exe", b"MZ")
    _register(rl, "SSF", "SSF\\SSF.exe")
    yield ini
    config_mod.reset_override_cache()


def test_list_shows_the_setting_and_the_emulators_without_one(saved):
    result = CliRunner().invoke(cli, ["boot-intros", "list"])
    assert result.exit_code == 0, result.output
    assert "duckstation" in result.output and "PlayStation" in result.output
    assert "No start-up logo setting: SSF" in result.output


def test_off_previews_then_writes_with_a_backup(saved):
    runner = CliRunner()
    dry = runner.invoke(cli, ["boot-intros", "off", "DuckStation (PS1)"])
    assert dry.exit_code == 0, dry.output
    assert "Would set PatchFastBoot = true (now not set)" in dry.output
    assert "Re-run with --apply" in dry.output
    assert saved.read_text() == DUCK_INI

    done = runner.invoke(cli, ["boot-intros", "off", "--apply"])
    assert done.exit_code == 0, done.output
    assert "PatchFastBoot = true" in saved.read_text()
    assert len(list(saved.parent.glob("settings.ini.*.bak"))) == 1

    again = runner.invoke(cli, ["boot-intros", "off"])
    assert "already off: DuckStation" in again.output


def test_list_names_the_files_an_emulator_with_its_own_check_misses(saved, tmp_path):
    emus = tmp_path / "Emulators"
    dol = emus / "Dolphin"
    _put(dol / "Dolphin.exe", b"MZ")
    _put(dol / "portable.txt", "")
    _put(dol / "User" / "Config" / "Dolphin.ini", "[Core]\nCPUThread = True\n")
    _put(dol / "User" / "GC" / "USA" / "IPL.bin")
    _register(tmp_path / "RocketLauncher", "Dolphin", "Dolphin\\Dolphin.exe")
    result = CliRunner().invoke(cli, ["boot-intros", "list"])
    assert result.exit_code == 0, result.output
    row = next(line for line in result.output.splitlines() if "dolphin" in line)
    assert "missing GameCube IPL, EUR" in row and "nothing extra" not in row
    assert "IPL, JAP" in result.output     # the table may wrap the cell


def test_unknown_name_exits_1_and_lists_the_names(saved):
    result = CliRunner().invoke(cli, ["boot-intros", "on", "nosuch"])
    assert result.exit_code == 1
    assert "nosuch" in result.output and "duckstation" in result.output
