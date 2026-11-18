# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""OpenTelemetry metrics export over OTLP/gRPC and OTLP/HTTP.

Instruments are observable gauges and counters. Callbacks read the latest
scrape snapshot, so Prometheus and OTLP publish the same numbers.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter as GrpcExporter,
)
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from zvm_otel_exporter import __version__
from zvm_otel_exporter.catalog import CATALOG
from zvm_otel_exporter.config import OtlpConfig


class SnapshotStore:
    """Thread-safe holder for the latest scrape."""

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        from zvm_otel_exporter.models import Snapshot

        self._snapshot = Snapshot.empty()

    def update(self, snapshot) -> None:  # noqa: ANN001
        with self._lock:
            self._snapshot = snapshot

    def get(self):  # noqa: ANN201
        with self._lock:
            return self._snapshot


@dataclass
class OtelRuntime:
    provider: MeterProvider

    def force_flush(self, timeout_millis: int = 10000) -> bool:
        return self.provider.force_flush(timeout_millis=timeout_millis)

    def shutdown(self) -> None:
        self.provider.shutdown()


def metrics_endpoint(endpoint: str, protocol: str) -> str:
    """Normalize an OTLP endpoint.

    HTTP exporters need the signal path ``/v1/metrics``. A base URL such as
    ``https://{env}.live.dynatrace.com/api/v2/otlp`` receives that suffix.
    gRPC endpoints gain an ``http://`` scheme when the caller passed host:port.
    """

    raw = endpoint.strip()
    if "://" not in raw:
        raw = "http://" + raw
    if protocol == "grpc":
        return raw
    parts = urlsplit(raw)
    path = parts.path.rstrip("/")
    if not path.endswith("/v1/metrics"):
        path = f"{path}/v1/metrics" if path else "/v1/metrics"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def start_otel(config: OtlpConfig, store: SnapshotStore, export_interval_ms: int) -> OtelRuntime:
    endpoint = metrics_endpoint(config.endpoint, config.protocol)
    headers = dict(config.headers)
    if config.protocol == "grpc":
        insecure = config.insecure or endpoint.startswith("http://")
        exporter = GrpcExporter(
            endpoint=endpoint,
            insecure=insecure,
            headers=headers or None,
            timeout=config.timeout,
        )
    else:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter as HttpExporter,
        )

        exporter = HttpExporter(
            endpoint=endpoint,
            headers=headers or None,
            timeout=config.timeout,
        )
    reader = PeriodicExportingMetricReader(
        exporter,
        export_interval_millis=export_interval_ms,
    )
    provider = MeterProvider(
        metric_readers=[reader],
        resource=Resource.create(
            {
                "service.name": "zvm-otel-exporter",
                "service.version": __version__,
            }
        ),
    )
    meter = provider.get_meter("zvm-otel-exporter", __version__)
    _register(meter, store)
    return OtelRuntime(provider)


def _register(meter, store: SnapshotStore) -> None:
    for defn in CATALOG.values():
        callback = _callback(store, defn.name, defn.type)

        if defn.type == "counter":
            meter.create_observable_counter(
                defn.name,
                callbacks=[callback],
                description=defn.description,
                unit=defn.unit,
            )
        else:
            meter.create_observable_gauge(
                defn.name,
                callbacks=[callback],
                description=defn.description,
                unit=defn.unit,
            )


def _callback(store: SnapshotStore, name: str, instrument_type: str):
    def observe(_options: CallbackOptions) -> Iterable[Observation]:
        snapshot = store.get()
        for sample in snapshot.samples:
            if sample.name != name:
                continue
            if instrument_type == "counter" and sample.value < 0:
                continue
            yield Observation(sample.value, dict(sample.attributes))

    return observe
