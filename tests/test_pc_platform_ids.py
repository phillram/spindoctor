"""ScreenScraper / TheGamesDB platform IDs for PC system aliases."""
from __future__ import annotations

import pytest

from spindoctor.scraper import (
    SCREENSCRAPER_SYSTEMS,
    THEGAMESDB_PLATFORMS,
    ScreenScraperClient,
    TheGamesDBClient,
)


@pytest.mark.parametrize("name,expected", [
    ("PC Games", 138),
    ("Windows", 138),
    ("Windows Games", 138),
    ("Steam", 138),
    ("Steam Games", 138),
    ("PC", 135),
])
def test_screenscraper_pc_ids_resolve(name, expected):
    client = ScreenScraperClient("u", "p")
    assert client._system_id(name) == expected


def test_screenscraper_constants_present():
    for k in ("pc games", "windows games", "steam games", "pc"):
        assert k in SCREENSCRAPER_SYSTEMS


@pytest.mark.parametrize("name", ["PC", "PC Games", "Windows Games", "Steam Games"])
def test_thegamesdb_pc_ids_resolve(name):
    client = TheGamesDBClient("k")
    assert client._platform_id(name) == 1


def test_thegamesdb_constants_present():
    for k in ("pc games", "windows games", "steam games", "pc"):
        assert k in THEGAMESDB_PLATFORMS
