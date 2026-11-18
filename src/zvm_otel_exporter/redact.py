# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""Redact configured secrets before they reach a log record."""

from __future__ import annotations

import logging
import re

_BEARER = re.compile(r"(?i)\b(bearer|api-token)\s+\S{8,}")
_HEADER = re.compile(r"(?i)\b(x-admin-token|x-auth-token|authorization)\s*[:=]\s*\S+")
_MIN_SECRET = 6


def secret_values(*values: str) -> list[str]:
    """Return unique secrets long enough to be worth redacting."""

    found: list[str] = []
    for value in values:
        if not value or len(value) < _MIN_SECRET:
            continue
        if value not in found:
            found.append(value)
    return found


def redact(text: str, secrets: list[str]) -> str:
    """Replace known secrets and common token assignments."""

    redacted = text
    for secret in secrets:
        if secret and secret in redacted:
            redacted = redacted.replace(secret, "***")
    redacted = _BEARER.sub(r"\1 ***", redacted)
    redacted = _HEADER.sub(r"\1 ***", redacted)
    return redacted


class RedactFilter(logging.Filter):
    """Logging filter that rewrites messages containing known secrets.

    Attached to the logger (not only a handler) so every handler, including
    test captures, sees the redacted text. Tracebacks are dropped when a
    secret was present in the message, because a formatted stack can repeat
    the same value.
    """

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [secret for secret in secrets if secret and len(secret) >= _MIN_SECRET]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact(message, self._secrets)
        if redacted != message or record.exc_info:
            record.msg = redacted
            record.args = ()
            if any(secret in message for secret in self._secrets):
                record.exc_info = None
                record.exc_text = None
        return True
