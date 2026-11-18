# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""In-memory metric samples shared by the Prometheus and OTLP exporters."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
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
    """Result of one scrape, including exporter self-metrics.

    ``vmcp_cached_at`` is the monotonic time of the last vmcp command pass.
    Prometheus scrapes and OTLP exports recompute ``zvm.vmcp.cache_age`` from
    that timestamp so the age climbs between refreshes without another CP call.
    """

    samples: tuple[Sample, ...]
    up: bool
    stale: bool
    scraped_at: float
    vmcp_cached_at: float | None = None
    clock: Callable[[], float] | None = None

    @staticmethod
    def empty() -> Snapshot:
        return Snapshot(samples=(), up=False, stale=False, scraped_at=0.0)


def samples_for_export(snapshot: Snapshot) -> tuple[Sample, ...]:
    """Return samples with vmcp cache age evaluated at read time."""

    cached_at = snapshot.vmcp_cached_at
    if cached_at is None:
        return snapshot.samples
    clock = snapshot.clock or time.monotonic
    age = max(0.0, clock() - cached_at)
    return tuple(
        Sample(sample.name, age, sample.attributes)
        if sample.name == "zvm.vmcp.cache_age"
        else sample
        for sample in snapshot.samples
    )
