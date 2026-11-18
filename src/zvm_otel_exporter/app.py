# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""Process lifecycle: scrape loop, Prometheus server, and OTLP exporter."""

from __future__ import annotations

import logging
import threading

from zvm_otel_exporter.collector import Collector
from zvm_otel_exporter.config import Config
from zvm_otel_exporter.feilong import FeilongClient
from zvm_otel_exporter.otel import SnapshotStore, start_otel
from zvm_otel_exporter.prometheus import render_prometheus
from zvm_otel_exporter.server import ExporterHTTPServer, serve

log = logging.getLogger(__name__)


class ExporterApp:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.stop = threading.Event()
        self.store = SnapshotStore()
        self.client = FeilongClient(config.feilong, config.secrets())
        self.collector = Collector(self.client, config)
        self.httpd: ExporterHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._otel = None
        self._closed = False

    def start(self) -> None:
        if self.config.otlp.enabled:
            interval_ms = max(1000, int(self.config.scrape_interval * 1000))
            self._otel = start_otel(self.config.otlp, self.store, interval_ms)
            log.info(
                "OTLP export enabled protocol=%s",
                self.config.otlp.protocol,
            )
        self._publish()
        if self.config.prometheus_enabled:
            self.httpd = serve(self.config.server.listen, self.config.server.port, self.store)
            log.info(
                "Prometheus endpoint http://%s:%s/metrics",
                self.config.server.listen,
                self.httpd.server_address[1],
            )
        self._thread = threading.Thread(target=self._loop, name="scrape", daemon=True)
        self._thread.start()

    def wait(self) -> None:
        while not self.stop.is_set():
            self.stop.wait(0.5)

    def run_once(self) -> int:
        """Collect once, flush OTLP, and write Prometheus text to stdout."""

        if self.config.otlp.enabled:
            self._otel = start_otel(self.config.otlp, self.store, export_interval_ms=3_600_000)
        snapshot = self._publish()
        if self._otel is not None:
            self._otel.force_flush()
        if self.config.prometheus_enabled:
            import sys

            sys.stdout.buffer.write(render_prometheus(snapshot))
        self.shutdown()
        return 0 if snapshot.up else 1

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.stop.set()
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        if self._otel is not None:
            self._otel.shutdown()
            self._otel = None
        self.client.close()

    def _publish(self):
        snapshot = self.collector.collect()
        self.store.update(snapshot)
        return snapshot

    def _loop(self) -> None:
        while not self.stop.wait(self.config.scrape_interval):
            try:
                self._publish()
            except Exception as exc:
                log.warning("scrape loop error: %s", exc)
