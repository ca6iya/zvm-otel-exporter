# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""In-memory metric samples shared by the Prometheus and OTLP exporters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sample:
    """One observation of a catalog metric.

    Attribute values are strings so they are valid on both Prometheus labels
    and OpenTelemetry attributes. The numeric measurement is ``value``.
    """

    name: str
    value: float
    attributes: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Snapshot:
    """Result of one scrape, including exporter self-metrics."""

    samples: tuple[Sample, ...]
    up: bool
    stale: bool
    scraped_at: float

    @staticmethod
    def empty() -> Snapshot:
        return Snapshot(samples=(), up=False, stale=False, scraped_at=0.0)
