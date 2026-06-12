"""Tests for the shared HTTPS networking helpers in spindoctor._net.

The TLS 1.2 floor is the load-bearing behaviour here — Win7 cabinet
binaries ship Python 3.8.10 + OpenSSL 1.0.2u, which can otherwise
negotiate TLS 1.0/1.1 against scraper / media endpoints that have
dropped them. Verifying the SSLContext on the mounted adapters keeps
that floor from regressing.
"""
from __future__ import annotations

import ssl


from spindoctor._net import _TLS12Adapter, make_session


def test_make_session_mounts_tls12_adapter_for_https():
    session = make_session()
    adapter = session.get_adapter("https://example.invalid/")
    assert isinstance(adapter, _TLS12Adapter)


def test_make_session_mounts_tls12_adapter_for_http():
    session = make_session()
    adapter = session.get_adapter("http://example.invalid/")
    assert isinstance(adapter, _TLS12Adapter)


def test_make_session_sets_user_agent():
    session = make_session()
    assert session.headers["User-Agent"] == "SpinDoctor/1.0"


def test_make_session_user_agent_can_be_overridden():
    session = make_session(user_agent="SpinDoctorTest/9.9")
    assert session.headers["User-Agent"] == "SpinDoctorTest/9.9"


def test_tls12_adapter_poolmanager_uses_tls12_floor():
    # ssl.TLSVersion was added in Python 3.7; project floor is 3.8,
    # so this is always available — no skip guard needed.
    adapter = _TLS12Adapter()
    adapter.init_poolmanager(connections=1, maxsize=1, block=False)
    ctx = adapter.poolmanager.connection_pool_kw["ssl_context"]
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
