"""Prometheus exposition and OTLP export."""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import grpc
from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2, metrics_service_pb2_grpc

from tests.helpers import make_config, sample_values
from zvm_otel_exporter.app import ExporterApp
from zvm_otel_exporter.catalog import CATALOG, prometheus_name
from zvm_otel_exporter.config import Config, OtlpConfig
from zvm_otel_exporter.feilong import FeilongClient
from zvm_otel_exporter.models import Sample, Snapshot
from zvm_otel_exporter.otel import metrics_endpoint
from zvm_otel_exporter.prometheus import render_prometheus


def test_prometheus_names_follow_otel_translation() -> None:
    snapshot = Snapshot(
        samples=(
            Sample("zvm.host.cpu.count", 6, {"zvm.host.name": "OPNSTK2"}),
            Sample(
                "zvm.guest.cpu.time", 1.5, {"zvm.host.name": "OPNSTK2", "zvm.guest.id": "LINUX01"}
            ),
            Sample("zvm.host.memory.usage", 1024, {"zvm.host.name": "OPNSTK2"}),
            Sample("zvm.exporter.up", 1, {}),
            Sample("zvm.smapi.calls", 3, {"zvm.smapi.call.state": "success"}),
        ),
        up=True,
        stale=False,
        scraped_at=1,
    )
    text = render_prometheus(snapshot).decode()
    assert "zvm_host_cpu_count_cpus{" in text
    assert 'zvm_host_name="OPNSTK2"' in text
    assert "zvm_guest_cpu_time_seconds_total{" in text
    assert "zvm_host_memory_usage_bytes{" in text
    assert "\nzvm_exporter_up 1.0\n" in text
    assert "zvm_smapi_calls_requests_total{" in text
    for defn in CATALOG.values():
        assert prometheus_name(defn)


def test_endpoint_normalization() -> None:
    assert metrics_endpoint("http://localhost:4318", "http") == "http://localhost:4318/v1/metrics"
    assert (
        metrics_endpoint("http://localhost:4318/v1/metrics", "http")
        == "http://localhost:4318/v1/metrics"
    )
    assert (
        metrics_endpoint("https://abc.live.dynatrace.com/api/v2/otlp", "http")
        == "https://abc.live.dynatrace.com/api/v2/otlp/v1/metrics"
    )
    assert metrics_endpoint("localhost:4317", "grpc") == "http://localhost:4317"
    assert (
        metrics_endpoint("https://abc.live.dynatrace.com/api/v2/otlp", "grpc")
        == "https://abc.live.dynatrace.com/api/v2/otlp"
    )


class _HttpOtlp(ThreadingHTTPServer):
    def __init__(self) -> None:
        self.bodies: list[bytes] = []
        super().__init__(("127.0.0.1", 0), _HttpHandler)


class _HttpHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        if self.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        self.server.bodies.append(body)  # type: ignore[attr-defined]
        response = metrics_service_pb2.ExportMetricsServiceResponse().SerializeToString()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, fmt: str, *args) -> None:
        return


class _GrpcServicer(metrics_service_pb2_grpc.MetricsServiceServicer):
    def __init__(self) -> None:
        self.requests: list[metrics_service_pb2.ExportMetricsServiceRequest] = []

    def Export(self, request, context):  # noqa: N802
        self.requests.append(request)
        return metrics_service_pb2.ExportMetricsServiceResponse()


def _metric_names(payload: bytes) -> set[str]:
    message = metrics_service_pb2.ExportMetricsServiceRequest()
    message.ParseFromString(payload)
    names: set[str] = set()
    for resource in message.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                names.add(metric.name)
    return names


def _enable_otlp(
    config: Config, endpoint: str, protocol: str, headers: dict[str, str] | None = None
) -> Config:
    config.otlp = OtlpConfig(
        enabled=True,
        endpoint=endpoint,
        protocol=protocol,
        headers=headers or {},
        insecure=True,
        timeout=5,
    )
    config.prometheus_enabled = True
    config.server.listen = "127.0.0.1"
    config.server.port = 0
    return config


def test_app_serves_prometheus_and_otlp_http(mock_feilong) -> None:
    receiver = _HttpOtlp()
    thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    thread.start()
    header = "Api-Token dt0c01.REPLACE_ME"
    config = _enable_otlp(
        make_config(mock_feilong.url),
        f"http://127.0.0.1:{receiver.server_address[1]}",
        "http",
        {"Authorization": header},
    )
    app = ExporterApp(config)
    try:
        app.start()
        port = app.httpd.server_address[1]
        import urllib.request

        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics").read().decode()
        health = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health").read())
        assert "zvm_host_cpu_count_cpus" in body
        assert "zvm_guest_cpu_time_seconds_total" in body
        assert "zvm_guest_network_io_bytes_total" in body
        assert health["feilong"] == "up"
        assert header not in body
        assert app._otel is not None
        assert app._otel.force_flush()
        names: set[str] = set()
        for payload in receiver.bodies:
            names |= _metric_names(payload)
        assert "zvm.host.cpu.count" in names
        assert "zvm.guest.cpu.time" in names
        assert "zvm.exporter.up" in names
    finally:
        app.shutdown()
        receiver.shutdown()
        receiver.server_close()


def test_otlp_grpc_export(mock_feilong) -> None:
    servicer = _GrpcServicer()
    server = grpc.server(
        thread_pool := __import__(
            "concurrent.futures", fromlist=["ThreadPoolExecutor"]
        ).ThreadPoolExecutor(max_workers=2)
    )
    metrics_service_pb2_grpc.add_MetricsServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    config = _enable_otlp(make_config(mock_feilong.url), f"127.0.0.1:{port}", "grpc")
    config.prometheus_enabled = False
    app = ExporterApp(config)
    try:
        app.start()
        assert app._otel is not None
        assert app._otel.force_flush()
        names: set[str] = set()
        for request in servicer.requests:
            for resource in request.resource_metrics:
                values = {
                    item.key: item.value.string_value for item in resource.resource.attributes
                }
                assert values.get("service.name") == "zvm-otel-exporter"
                for scope in resource.scope_metrics:
                    for metric in scope.metrics:
                        names.add(metric.name)
        assert "zvm.host.memory.limit" in names
        assert "zvm.guest.up" in names
    finally:
        app.shutdown()
        server.stop(0)
        thread_pool.shutdown(wait=False)


def test_cli_once_against_mock(mock_feilong) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "zvm_otel_exporter",
            "--feilong-url",
            mock_feilong.url,
            "--feilong-admin-token",
            "test-admin-token",
            "--no-verify-tls",
            "--once",
            "--log-level",
            "ERROR",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "zvm_host_cpu_count_cpus" in completed.stdout
    assert "zvm_disk_pool_available_bytes" in completed.stdout
    assert "test-admin-token" not in completed.stdout
    assert "test-admin-token" not in completed.stderr


def test_cli_once_exits_nonzero_when_feilong_is_down() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "zvm_otel_exporter",
            "--feilong-url",
            "http://127.0.0.1:1",
            "--feilong-admin-token",
            "test-admin-token",
            "--timeout",
            "1",
            "--once",
            "--log-level",
            "ERROR",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 1
    assert "zvm_exporter_up 0.0" in completed.stdout
    assert "test-admin-token" not in completed.stdout
    assert "test-admin-token" not in completed.stderr


def test_direct_collector_sample_is_rendered(mock_feilong) -> None:
    config = make_config(mock_feilong.url)
    client = FeilongClient(config.feilong, config.secrets())
    try:
        from zvm_otel_exporter.collector import Collector

        snapshot = Collector(client, config).collect()
    finally:
        client.close()
    assert sample_values(snapshot, "zvm.exporter.up") == [1.0]
