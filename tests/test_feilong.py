"""Feilong client behavior against the mock server."""

from __future__ import annotations

import logging

import pytest

from tests.helpers import make_config
from zvm_otel_exporter.feilong import (
    FeilongAPIError,
    FeilongAuthError,
    FeilongClient,
    FeilongUnavailable,
    unwrap,
)
from zvm_otel_exporter.logging_setup import setup_logging


def _client(url: str, **kwargs: object) -> FeilongClient:
    config = make_config(url, **kwargs).feilong
    return FeilongClient(config, ["test-admin-token", "test-auth-token"])


def test_token_exchange_and_host(mock_feilong) -> None:
    client = _client(mock_feilong.url)
    try:
        host = client.get_output("/host")
    finally:
        client.close()
    assert host["hypervisor_hostname"] == "OPNSTK2"
    assert mock_feilong.token_mints == 1
    assert mock_feilong.data_tokens == ["test-auth-token"]
    assert mock_feilong.data_admin_headers == 0
    assert "test-admin-token" not in repr(client)


def test_refreshes_session_token_after_401(mock_feilong) -> None:
    mock_feilong.reject_data_once = True
    client = _client(mock_feilong.url)
    try:
        assert client.get_output("/host")["vcpus"] == 6
    finally:
        client.close()
    assert mock_feilong.token_mints == 2


def test_bad_admin_token_is_redacted(mock_feilong) -> None:
    mock_feilong.echo_bad_token = True
    secret = "wrong-admin-token-value"
    setup_logging("INFO", [secret])
    messages: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    logging.getLogger().addHandler(_Capture())
    client = _client(mock_feilong.url, admin_token=secret)
    with pytest.raises(FeilongAuthError) as raised:
        try:
            client.get_output("/host")
        finally:
            client.close()
    logging.getLogger("zvm_otel_exporter.tests").error(
        "token exchange failed: bad token: %s", secret
    )
    assert secret not in str(raised.value)
    assert messages
    assert all(secret not in message for message in messages)
    assert any("bad token: ***" in message for message in messages)


def test_unreachable_does_not_include_a_token() -> None:
    client = _client("http://127.0.0.1:1", timeout=1)
    try:
        with pytest.raises(FeilongUnavailable) as raised:
            client.get_output("/host")
    finally:
        client.close()
    assert "test-admin-token" not in str(raised.value)


def test_non_json_and_overall_rc(mock_feilong) -> None:
    mock_feilong.garbage_paths.add("/host")
    client = _client(mock_feilong.url)
    try:
        with pytest.raises(FeilongAPIError, match="non-JSON"):
            client.get_output("/host")
    finally:
        client.close()
    with pytest.raises(FeilongAPIError, match="nope"):
        unwrap({"overallRC": 8, "errmsg": "nope", "output": {}}, [])


def test_auth_none_skips_token(mock_feilong) -> None:
    mock_feilong.require_auth = False
    client = _client(mock_feilong.url, auth="none", admin_token="")
    try:
        assert client.get_output("/")["version"] == "1.6.7"
    finally:
        client.close()
    assert mock_feilong.token_mints == 0
