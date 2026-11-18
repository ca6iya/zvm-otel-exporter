# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""Command line interface."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from urllib.parse import urlsplit, urlunsplit

from zvm_otel_exporter import __version__
from zvm_otel_exporter.app import ExporterApp
from zvm_otel_exporter.config import ConfigError, load_config
from zvm_otel_exporter.logging_setup import setup_logging

log = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="zvm-otel-exporter",
        description=(
            "Export z/VM host and guest metrics from the Feilong REST API "
            "to Prometheus and OpenTelemetry."
        ),
    )
    parser.add_argument("--config", help="YAML config file")
    parser.add_argument("--feilong-url", help="Feilong base URL, for example https://host:8080")
    parser.add_argument(
        "--feilong-admin-token",
        help="Long-lived Feilong admin token (X-Admin-Token). Prefer the environment variable.",
    )
    parser.add_argument(
        "--feilong-auth-token",
        help="Existing Feilong session token (X-Auth-Token). Skips token exchange when set alone.",
    )
    parser.add_argument("--auth", choices=("token", "none"), help="Feilong authentication mode")
    parser.add_argument(
        "--verify-tls",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Verify the Feilong TLS certificate (default: true)",
    )
    parser.add_argument("--ca-file", help="CA bundle used to verify Feilong")
    parser.add_argument("--timeout", type=float, help="Feilong HTTP timeout in seconds")
    parser.add_argument(
        "--disk-pool",
        action="append",
        dest="disk_pool",
        help="Disk pool to query, for example ECKD:eckdpool1. Repeat for more than one.",
    )
    parser.add_argument("--listen", help="Prometheus listen address (default 0.0.0.0)")
    parser.add_argument("--port", type=int, help="Prometheus listen port (default 9110)")
    parser.add_argument("--scrape-interval", type=float, help="Seconds between Feilong scrapes")
    parser.add_argument(
        "--prometheus",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Serve the Prometheus /metrics endpoint (default: true)",
    )
    parser.add_argument(
        "--otlp",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Export metrics over OTLP (default: false)",
    )
    parser.add_argument("--otlp-endpoint", help="OTLP gRPC or HTTP endpoint")
    parser.add_argument("--otlp-protocol", choices=("grpc", "http"), help="OTLP protocol")
    parser.add_argument(
        "--otlp-header",
        action="append",
        dest="otlp_header",
        help="OTLP header as Key=Value. Repeat for more than one. Values are not logged.",
    )
    parser.add_argument(
        "--otlp-insecure",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Disable TLS for the OTLP gRPC exporter",
    )
    parser.add_argument("--otlp-timeout", type=float, help="OTLP export timeout in seconds")
    parser.add_argument("--log-level", help="DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Scrape once, write Prometheus text to stdout, flush OTLP, and exit",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    setup_logging(config.log_level, config.secrets())
    otlp_state = "off"
    if config.otlp.enabled:
        otlp_state = f"{config.otlp.protocol} {safe_url(config.otlp.endpoint)}"
    log.info(
        "zvm-otel-exporter %s starting; feilong=%s prometheus=%s otlp=%s header_count=%s",
        __version__,
        safe_url(config.feilong.url),
        config.prometheus_enabled,
        otlp_state,
        len(config.otlp.headers),
    )
    app = ExporterApp(config)
    if args.once:
        try:
            return app.run_once()
        except Exception as exc:
            log.error("scrape failed: %s", exc)
            app.shutdown()
            return 1

    def _stop(signum: int, _frame: object) -> None:
        log.info("received signal %s, shutting down", signum)
        app.stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        app.start()
        app.wait()
    finally:
        app.shutdown()
    return 0


def safe_url(url: str) -> str:
    """Drop userinfo so a misconfigured URL cannot land in a log line."""

    parts = urlsplit(url)
    if not parts.username and not parts.password:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))
