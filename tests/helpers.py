# SPDX-License-Identifier: Apache-2.0
"""Test helpers."""

from __future__ import annotations

from zvm_otel_exporter.config import (
    CollectorToggles,
    Config,
    FeilongConfig,
    OtlpConfig,
    ServerConfig,
)
from zvm_otel_exporter.models import Snapshot


def make_config(url: str, **feilong: object) -> Config:
    base = {
        "url": url,
        "admin_token": "test-admin-token",
        "auth": "token",
        "verify_tls": False,
        "timeout": 5,
        "disk_pools": ("ECKD:ECKDPOOL",),
        "batch_size": 25,
        "concurrency": 4,
    }
    base.update(feilong)
    return Config(
        feilong=FeilongConfig(**base),
        server=ServerConfig(listen="127.0.0.1", port=0),
        scrape_interval=60,
        prometheus_enabled=True,
        otlp=OtlpConfig(enabled=False),
        collectors=CollectorToggles(
            host=True,
            disk_pool=True,
            guests=True,
            interfaces=True,
            power_state=True,
            minidisks=True,
            vswitches=True,
            ssi=True,
            pcif=True,
            smapi=True,
            version=True,
        ),
        log_level="WARNING",
    )


def sample_values(snapshot: Snapshot, name: str, **attributes: str) -> list[float]:
    found: list[float] = []
    for sample in snapshot.samples:
        if sample.name != name:
            continue
        if all(sample.attributes.get(key) == value for key, value in attributes.items()):
            found.append(sample.value)
    return found
