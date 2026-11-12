"""ScreenScraper / TheGamesDB platform IDs for PC system aliases."""
from __future__ import annotations

import pytest

from spindoctor.scraper import ScreenScraperClient, TheGamesDBClient


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


@pytest.mark.parametrize("name", ["PC", "PC Games", "Windows Games", "Steam Games"])
def test_thegamesdb_pc_ids_resolve(name):
    client = TheGamesDBClient("k")
    assert client._platform_id(name) == 1
