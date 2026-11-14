"""Tests for the shared HTTPS networking helpers in spindoctor._net.

The TLS 1.2 floor is the load-bearing behaviour here — Win7 cabinet
binaries ship Python 3.8.10 + OpenSSL 1.0.2u, which can otherwise
negotiate TLS 1.0/1.1 against scraper / media endpoints that have
dropped them. Verifying the SSLContext on the mounted adapters keeps
that floor from regressing.
"""
from __future__ import annotations

import ssl

import pytest

from spindoctor._net import _TLS12Adapter, make_session


@pytest.mark.parametrize("scheme", ["https", "http"])
def test_make_session_mounts_tls12_adapter(scheme):
    session = make_session()
    adapter = session.get_adapter(f"{scheme}://example.invalid/")
    assert isinstance(adapter, _TLS12Adapter)


@pytest.mark.parametrize(
    "user_agent,expected",
    [
        pytest.param(None, "SpinDoctor/1.0", id="default"),
        pytest.param("SpinDoctorTest/9.9", "SpinDoctorTest/9.9", id="custom"),
    ],
)
def test_make_session_user_agent(user_agent, expected):
    session = make_session() if user_agent is None else make_session(user_agent=user_agent)
    assert session.headers["User-Agent"] == expected


def test_tls12_adapter_poolmanager_uses_tls12_floor():
    # ssl.TLSVersion was added in Python 3.7; project floor is 3.8,
    # so this is always available — no skip guard needed.
    adapter = _TLS12Adapter()
    adapter.init_poolmanager(connections=1, maxsize=1, block=False)
    ctx = adapter.poolmanager.connection_pool_kw["ssl_context"]
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
