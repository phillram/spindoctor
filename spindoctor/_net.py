"""Networking helpers shared by scraper / media / credential-verify paths.

Centralises the TLS 1.2 floor for outbound HTTPS so every `requests.Session`
SpinDoctor builds negotiates the same minimum protocol version regardless
of which OpenSSL the host happens to ship. Without this the Win7-cabinet
frozen build (Python 3.8.10, OpenSSL 1.0.2u) can negotiate TLS 1.0/1.1
against ScreenScraper / TheGamesDB / Steam media CDNs that have since
disabled those — surfacing as a cryptic `EOF occurred in violation of
protocol` instead of a clean handshake error. `update_check.py` already
does the same thing for its urllib path; this is the requests-side twin.
"""
from __future__ import annotations

import ssl
from typing import Optional

import requests
from requests.adapters import HTTPAdapter


class _TLS12Adapter(HTTPAdapter):
    """HTTPAdapter that pins a TLS 1.2 floor on its connection pool.

    Falls back silently to the platform default when the running Python
    lacks the ``ssl.TLSVersion`` enum (3.6 and earlier — below our
    supported floor, but guarded for safety on exotic OpenSSL builds).
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        except (AttributeError, ValueError):
            pass
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        except (AttributeError, ValueError):
            pass
        kwargs["ssl_context"] = ctx
        return super().proxy_manager_for(*args, **kwargs)


def make_session(user_agent: str = "SpinDoctor/1.0") -> requests.Session:
    """Build a ``requests.Session`` with the TLS 1.2 floor pre-mounted.

    Replaces ``requests.Session()`` everywhere SpinDoctor talks to
    third-party HTTPS endpoints (scraper APIs, media CDNs, credential
    probes). The User-Agent default matches the historical literal used
    in scraper.py and media.py so server-side logs stay consistent.
    """
    session = requests.Session()
    adapter = _TLS12Adapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = user_agent
    return session


def request_get(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> requests.Response:
    """One-shot HTTPS GET that reuses :func:`make_session` for its TLS floor.

    Used by the credential-verify probes that don't need session reuse but
    still want the same minimum TLS guarantee as the live clients.
    """
    with make_session() as session:
        if headers:
            session.headers.update(headers)
        return session.get(url, params=params, timeout=timeout)
