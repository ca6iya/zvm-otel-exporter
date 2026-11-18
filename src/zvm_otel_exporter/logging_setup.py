# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""Logging configuration that cannot print Feilong or OTLP credentials."""

from __future__ import annotations

import logging
import sys

from zvm_otel_exporter.redact import RedactFilter

_QUIET_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "requests",
    "opentelemetry",
    "opentelemetry.sdk",
    "opentelemetry.exporter",
)

# Shared with the process-wide log hook so a secret loaded later is still redacted.
_SECRETS: list[str] = []
_INSTALLED = False


def setup_logging(level: str, secrets: list[str]) -> None:
    """Configure the root logger.

    HTTP client loggers stay at WARNING even when the exporter is at DEBUG.
    Those libraries can echo request headers, and the headers carry tokens.
    A process-wide log hook redacts secrets before any handler, including
    handlers installed by a test runner, sees the record.
    """

    _SECRETS.clear()
    _SECRETS.extend(secrets)
    _install_hook()
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    redact_filter = RedactFilter(_SECRETS)
    handler.addFilter(redact_filter)
    root.handlers.clear()
    root.addHandler(handler)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _install_hook() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    original = logging.Logger.handle

    def handle(self: logging.Logger, record: logging.LogRecord) -> None:
        RedactFilter(_SECRETS).filter(record)
        original(self, record)

    logging.Logger.handle = handle  # type: ignore[method-assign]
    _INSTALLED = True
