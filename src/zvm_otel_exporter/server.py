# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""HTTP server for /metrics and /health.

The process stays healthy when Feilong is down. Scrape failure is reported by
``zvm_exporter_up`` and by the ``feilong`` field of ``/health``, both of which
remain available.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from zvm_otel_exporter.otel import SnapshotStore
from zvm_otel_exporter.prometheus import CONTENT_TYPE, render_prometheus


class ExporterHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(listen: str, port: int, store: SnapshotStore) -> ExporterHTTPServer:
    handler = _handler_class(store)
    httpd = ExporterHTTPServer((listen, port), handler)
    thread = threading.Thread(target=httpd.serve_forever, name="http", daemon=True)
    thread.start()
    httpd.serve_thread = thread  # type: ignore[attr-defined]
    return httpd


def _handler_class(store: SnapshotStore) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/metrics":
                body = render_prometheus(store.get())
                self._send(200, body, CONTENT_TYPE)
                return
            if path == "/health":
                snapshot = store.get()
                payload = {
                    "status": "ok",
                    "feilong": "up" if snapshot.up else "down",
                    "stale": snapshot.stale,
                }
                self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
                return
            if path == "/":
                body = b"zvm-otel-exporter\nmetrics: /metrics\nhealth: /health\n"
                self._send(200, body, "text/plain; charset=utf-8")
                return
            self._send(404, b"not found\n", "text/plain; charset=utf-8")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            return

    return Handler
