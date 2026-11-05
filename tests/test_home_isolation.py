"""The suite must never read or write the real ``~/.spindoctor``.

``tests/conftest.py`` re-homes the process before the package is imported.
If that stops working — a new module caching a path from the real home, or
something importing ``spindoctor`` ahead of the conftest — these tests fail
instead of the suite quietly editing the developer's own config.
"""
from pathlib import Path

from spindoctor import config as config_mod
from spindoctor import ledblinky, matcher, media_scan, migrate, scraper, themes


def test_home_is_the_temporary_test_home():
    assert Path.home().name.startswith("spindoctor-test-home-")


def test_per_user_paths_live_under_the_test_home():
    home = Path.home()
    paths = {
        "config.CONFIG_DIR": config_mod.CONFIG_DIR,
        "config.CONFIG_FILE": config_mod.CONFIG_FILE,
        "media_scan.MANIFEST_DIR": media_scan.MANIFEST_DIR,
        "scraper.SCRAPER_LOG_PATH": scraper.SCRAPER_LOG_PATH,
        "scraper.METADATA_CACHE_DIR": scraper.METADATA_CACHE_DIR,
        "themes.THEMES_DIR": themes.THEMES_DIR,
        "migrate.MIGRATIONS_DIR": migrate.MIGRATIONS_DIR,
        "ledblinky.LISTXML_CACHE_DIR": ledblinky.LISTXML_CACHE_DIR,
        "matcher.CACHE_DIR": matcher.CACHE_DIR,
        "matcher.MEDIA_CACHE_DIR": matcher.MEDIA_CACHE_DIR,
    }
    outside = {name: str(path) for name, path in paths.items() if home not in path.parents}
    assert not outside
