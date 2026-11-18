# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""Render a snapshot as Prometheus text exposition."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from zvm_otel_exporter.catalog import CATALOG, prometheus_label, prometheus_name
from zvm_otel_exporter.models import Sample, Snapshot, samples_for_export

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class SnapshotCollector:
    """Prometheus collector that reads the latest snapshot."""

    def __init__(self, snapshot: Snapshot) -> None:
        self._snapshot = snapshot

    def collect(self):
        grouped: dict[str, list[Sample]] = {}
        for sample in samples_for_export(self._snapshot):
            grouped.setdefault(sample.name, []).append(sample)
        for name in sorted(grouped):
            defn = CATALOG[name]
            labels = [prometheus_label(label) for label in defn.labels]
            family_type = CounterMetricFamily if defn.type == "counter" else GaugeMetricFamily
            family = family_type(prometheus_name(defn), defn.description, labels=labels)
            ordered = sorted(
                grouped[name],
                key=lambda sample: tuple(
                    str(sample.attributes.get(label, "")) for label in defn.labels
                ),
            )
            for sample in ordered:
                values = [str(sample.attributes.get(label, "")) for label in defn.labels]
                family.add_metric(values, sample.value)
            yield family


def render_prometheus(snapshot: Snapshot) -> bytes:
    registry = CollectorRegistry(auto_describe=False)
    registry.register(SnapshotCollector(snapshot))
    return generate_latest(registry)
