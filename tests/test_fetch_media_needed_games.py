"""`fetch-media` looks up only the games that miss a requested type.

Regression coverage for a real-cabinet run: `fetch-media --types wheel`
on a 1,287-game handheld wheel with 146 missing wheel pictures resolved
metadata for every game, because every game lacked *some* optional type
(sound, trailer, fade) it was never asked for. Each lookup costs scraper
quota (TheGamesDB allows about a thousand a month). With `--output-dir`,
the missing list came from the empty output folder, so every game looked
missing there too. A dry run also said "Downloaded" and wrote the
automatic audit CSV.
"""
from __future__ import annotations

from click import unstyle
from click.testing import CliRunner

from spindoctor.cli import cli
from spindoctor.config import save_config
from tests.helpers import build_nes_library


def _fake_client(monkeypatch, fetched):
    import spindoctor.scraper as scraper_mod
    from spindoctor.scraper import GameMetadata

    class _FakeClient:
        source_name = "thegamesdb"
        _cache = None

        def fetch_with_search(self, game_name, system_name, threshold=0.80):
            fetched.append(game_name)
            return [GameMetadata(
                name=game_name, match_score=1.0,
                wheel_url=f"https://example.invalid/{game_name}.png",
                video_url=f"https://example.invalid/{game_name}.mp4",
            )]

    monkeypatch.setattr(scraper_mod, "build_client", lambda *_a, **_kw: _FakeClient())


def _fake_downloads(monkeypatch, queued):
    """Record the download jobs instead of fetching them."""
    from spindoctor import media as media_mod
    from spindoctor.media import DownloadResult

    def download_many(self, jobs, system_name, overwrite=False, max_workers=4,
                      on_complete=None):
        results = []
        for game_name, media_type, _url in jobs:
            queued.append((game_name, media_type))
            dest = self.media_path(system_name, game_name, media_type)
            r = DownloadResult(game_name=game_name, media_type=media_type,
                               success=True, path=dest)
            results.append(r)
            if on_complete:
                on_complete(r)
        return results

    monkeypatch.setattr(media_mod.MediaDownloader, "download_many", download_many)


def _remove_wheel(tmp_path, game):
    (tmp_path / "hs" / "Media" / "nes" / "Images" / "Wheel" / f"{game}.png").unlink()


def test_dry_run_looks_up_only_games_missing_the_requested_type(tmp_path, config_home, monkeypatch):
    build_nes_library(tmp_path)          # mario, zelda, contra: wheel + snap each
    _remove_wheel(tmp_path, "zelda")
    fetched: list[str] = []
    _fake_client(monkeypatch, fetched)

    result = CliRunner().invoke(cli, ["fetch-media", "--system", "nes", "--types", "wheel"])

    assert result.exit_code == 0, result.output
    assert fetched == ["zelda"]
    assert "Processing 1 games" in unstyle(result.output)


def test_nothing_looked_up_when_the_requested_types_are_all_present(tmp_path, config_home, monkeypatch):
    build_nes_library(tmp_path)
    fetched: list[str] = []
    _fake_client(monkeypatch, fetched)

    result = CliRunner().invoke(cli, ["fetch-media", "--system", "nes", "--types", "wheel,snap"])

    assert result.exit_code == 0, result.output
    assert fetched == []
    assert "All media present" in unstyle(result.output)


def test_only_the_missing_types_of_a_game_are_downloaded(tmp_path, config_home, monkeypatch):
    build_nes_library(tmp_path)
    _remove_wheel(tmp_path, "zelda")
    fetched: list[str] = []
    queued: list[tuple] = []
    _fake_client(monkeypatch, fetched)
    _fake_downloads(monkeypatch, queued)

    result = CliRunner().invoke(
        cli, ["fetch-media", "--system", "nes", "--types", "wheel,snap", "--apply"],
    )

    assert result.exit_code == 0, result.output
    assert fetched == ["zelda"]
    assert queued == [("zelda", "wheel")]          # zelda's snap is already there
    out = unstyle(result.output)
    assert "existing" in out and "Downloaded: 1" in out


def test_output_dir_judges_missing_media_by_the_live_folders(tmp_path, config_home, monkeypatch):
    build_nes_library(tmp_path)
    _remove_wheel(tmp_path, "zelda")
    stage = tmp_path / "stage"
    fetched: list[str] = []
    queued: list[tuple] = []
    _fake_client(monkeypatch, fetched)
    _fake_downloads(monkeypatch, queued)

    result = CliRunner().invoke(
        cli, ["fetch-media", "--system", "nes", "--types", "wheel",
              "--output-dir", str(stage), "--apply"],
    )

    assert result.exit_code == 0, result.output
    # Before the fix the empty output folder made all three look missing.
    assert fetched == ["zelda"]
    assert queued == [("zelda", "wheel")]


def test_output_dir_skips_what_is_already_staged(tmp_path, config_home, monkeypatch):
    build_nes_library(tmp_path)
    _remove_wheel(tmp_path, "zelda")
    stage = tmp_path / "stage"
    staged = stage / "Media" / "nes" / "Images" / "Wheel"
    staged.mkdir(parents=True)
    (staged / "zelda.png").write_bytes(b"staged earlier")
    fetched: list[str] = []
    _fake_client(monkeypatch, fetched)

    result = CliRunner().invoke(
        cli, ["fetch-media", "--system", "nes", "--types", "wheel", "--output-dir", str(stage)],
    )

    assert result.exit_code == 0, result.output
    assert fetched == []
    assert "All media present" in unstyle(result.output)


def test_overwrite_still_looks_up_every_game(tmp_path, config_home, monkeypatch):
    build_nes_library(tmp_path)
    fetched: list[str] = []
    _fake_client(monkeypatch, fetched)

    result = CliRunner().invoke(
        cli, ["fetch-media", "--system", "nes", "--types", "wheel", "--overwrite"],
    )

    assert result.exit_code == 0, result.output
    assert sorted(fetched) == ["contra", "mario", "zelda"]


def test_dry_run_says_would_download_and_writes_no_auto_audit(tmp_path, config_home, monkeypatch):
    cfg = build_nes_library(tmp_path)
    exports = tmp_path / "exports"
    cfg.auto_audit_export_dir = str(exports)
    save_config(cfg)
    _remove_wheel(tmp_path, "zelda")
    fetched: list[str] = []
    _fake_client(monkeypatch, fetched)

    result = CliRunner().invoke(cli, ["fetch-media", "--system", "nes", "--types", "wheel"])

    assert result.exit_code == 0, result.output
    out = unstyle(result.output)
    assert "Would download: 1" in out
    assert "Downloaded:" not in out
    assert not exports.exists() or not list(exports.glob("audit_*.csv"))


def test_dry_run_still_writes_an_explicit_report(tmp_path, config_home, monkeypatch):
    build_nes_library(tmp_path)
    _remove_wheel(tmp_path, "zelda")
    report = tmp_path / "report.csv"
    _fake_client(monkeypatch, [])

    result = CliRunner().invoke(
        cli, ["fetch-media", "--system", "nes", "--types", "wheel", "--report", str(report)],
    )

    assert result.exit_code == 0, result.output
    assert report.is_file()


def test_apply_still_writes_the_auto_audit(tmp_path, config_home, monkeypatch):
    cfg = build_nes_library(tmp_path)
    exports = tmp_path / "exports"
    cfg.auto_audit_export_dir = str(exports)
    save_config(cfg)
    _remove_wheel(tmp_path, "zelda")
    _fake_client(monkeypatch, [])
    _fake_downloads(monkeypatch, [])

    result = CliRunner().invoke(
        cli, ["fetch-media", "--system", "nes", "--types", "wheel", "--apply"],
    )

    assert result.exit_code == 0, result.output
    assert len(list(exports.glob("audit_*.csv"))) == 1
