"""Where ScreenScraper developer credentials come from.

ScreenScraper refuses SpinDoctor's bundled ``devid=SpinDoctor`` on every
request, even ones that need no user login. The 403 message sent users to
the member sign-up page, which gives only a user login; ScreenScraper's API
page says developers get their devid/devpassword by asking on its forum.
``doctor`` reported ScreenScraper as OK whenever a user login was set,
although every request with the placeholder fails.
"""
from __future__ import annotations

from unittest.mock import patch

from spindoctor import health, scraper
from spindoctor.config import Config


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def json(self):
        raise ValueError("no json body")


def _verify_with_403(devid):
    body = "Erreur de login : Verifier vos identifiants developpeur !"
    with patch.object(scraper, "request_get", return_value=_FakeResponse(403, body)):
        return scraper.verify_screenscraper("u", "p", devid=devid, devpassword="x")


def test_placeholder_403_points_at_the_developer_request_not_the_sign_up_page():
    ok, msg = _verify_with_403("SpinDoctor")
    assert ok is False
    assert scraper.SCREENSCRAPER_DEVELOPER_REQUEST_URL in msg
    assert "membreinscription" not in msg
    assert "config set screenscraper_devid" in msg


def test_issued_devid_403_gets_no_placeholder_advice():
    ok, msg = _verify_with_403("issued-dev-id")
    assert ok is False
    assert scraper.SCREENSCRAPER_DEVELOPER_REQUEST_URL not in msg


def test_doctor_warns_when_the_developer_id_is_the_placeholder():
    cfg = Config()
    cfg.screenscraper_user = "u"
    cfg.screenscraper_pass = "p"
    assert cfg.screenscraper_devid == "SpinDoctor"     # the bundled default

    parent = health.check_api_creds(cfg)
    ss = next(c for c in parent.children if c.name == "ScreenScraper")

    assert ss.status == health.Status.WARN
    assert "placeholder" in ss.detail
    assert scraper.SCREENSCRAPER_DEVELOPER_REQUEST_URL in ss.fix
    assert "screenscraper_devid" in ss.fix


def test_doctor_is_ok_with_an_issued_developer_id():
    cfg = Config()
    cfg.screenscraper_user = "u"
    cfg.screenscraper_pass = "p"
    cfg.screenscraper_devid = "issued-dev-id"
    cfg.screenscraper_devpassword = "issued-dev-password"

    parent = health.check_api_creds(cfg)
    ss = next(c for c in parent.children if c.name == "ScreenScraper")

    assert ss.status == health.Status.OK


def test_doctor_stays_info_without_a_user_login():
    parent = health.check_api_creds(Config())
    ss = next(c for c in parent.children if c.name == "ScreenScraper")
    assert ss.status == health.Status.INFO
