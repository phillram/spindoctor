"""scraper.log must not expose passwords in urllib3 exception strings."""
from __future__ import annotations

import pytest

from spindoctor.scraper import _redact_error_str


def _make_urllib3_error(sspassword: str, devpassword: str) -> Exception:
    """Simulate the MaxRetryError/NameResolutionError message urllib3 produces.

    When DNS fails, urllib3 embeds the full request URL (with query params)
    in the exception string. This is exactly the text that ends up in
    scraper.log without redaction.
    """
    url = (
        f"https://www.screenscraper.fr/api2/jeuInfos.php"
        f"?devid=testdevuser&devpassword={devpassword}"
        f"&softname=SpinDoctor&ssid=testuser&sspassword={sspassword}"
        f"&output=json&romnom=Animal+Crossing.zip&systemeid=13"
    )
    return Exception(
        f"HTTPSConnectionPool(host='www.screenscraper.fr', port=443): "
        f"Max retries exceeded with url: {url} "
        f"(Caused by NameResolutionError(\"Failed to resolve 'www.screenscraper.fr'\"))"
    )


def test_redact_error_str_removes_sspassword():
    password = "fake_sspassword_for_test"
    devpass = "fake_devpassword_for_test"
    params = {"sspassword": password, "devpassword": devpass, "ssid": "testuser"}
    error = _make_urllib3_error(password, devpass)

    result = _redact_error_str(error, params)

    assert password not in result
    assert devpass not in result
    assert "***" in result
    # Non-sensitive values should survive
    assert "testuser" in result
    assert "screenscraper.fr" in result


@pytest.mark.parametrize(
    "params",
    [
        pytest.param(None, id="no-params"),
        pytest.param({}, id="empty-params"),
        # params dict without sspassword — no crash, string unchanged
        pytest.param({"ssid": "user"}, id="missing-secret-key"),
    ],
)
def test_redact_error_str_without_secret_params_leaves_message_unchanged(params):
    error = Exception("some network error without params")
    result = _redact_error_str(error, params)
    assert result == "some network error without params"


def test_redact_error_str_thegamesdb_apikey():
    apikey = "fake_thegamesdb_api_key_for_testing_only_000000000"
    params = {"apikey": apikey, "name": "Animal Crossing"}
    error = Exception(
        f"HTTPSConnectionPool(host='api.thegamesdb.net', port=443): "
        f"Max retries exceeded with url: /v1/Games/ByGameName?apikey={apikey}&name=Animal+Crossing "
        f"(Caused by NameResolutionError(\"Failed to resolve 'api.thegamesdb.net'\"))"
    )
    result = _redact_error_str(error, params)
    assert apikey not in result
    assert "***" in result
    assert "Animal+Crossing" in result
