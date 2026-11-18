"""Shared fixtures."""

from __future__ import annotations

import pytest

from zvm_otel_exporter.mock import start_mock


@pytest.fixture
def mock_feilong():
    server = start_mock()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
