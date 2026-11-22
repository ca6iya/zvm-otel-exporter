# SPDX-License-Identifier: Apache-2.0
"""The compose demo stays synthetic, pinned, and able to scrape the fixture."""

from __future__ import annotations

from pathlib import Path

import yaml

from zvm_otel_exporter.app import ExporterApp
from zvm_otel_exporter.config import load_config
from zvm_otel_exporter.prometheus import render_prometheus

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "examples" / "compose"


def test_compose_demo_is_pinned_and_synthetic() -> None:
    compose = yaml.safe_load((COMPOSE / "docker-compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert services["prometheus"]["image"] == "prom/prometheus:v3.16.0"
    assert services["grafana"]["image"] == "grafana/grafana:12.4.15"
    for service in services.values():
        image = service.get("image", "")
        assert ":latest" not in image
    assert services["feilong"]["image"] == services["exporter"]["image"]
    context = (COMPOSE / services["feilong"]["build"]["context"]).resolve()
    assert (context / "Dockerfile").is_file()

    prometheus = yaml.safe_load((COMPOSE / "prometheus.yml").read_text(encoding="utf-8"))
    jobs = prometheus["scrape_configs"]
    assert jobs[0]["job_name"] == "zvm-otel-exporter"
    assert jobs[0]["static_configs"][0]["targets"] == ["exporter:9110"]

    rendered = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            COMPOSE / "docker-compose.yaml",
            COMPOSE / "exporter.yaml",
            COMPOSE / "prometheus.yml",
            ROOT / "README.md",
        )
    )
    assert "synthetic" in rendered.lower()
    assert "not a z/VM system" in rendered
    assert "test-admin-token" in rendered
    assert "127.0.0.1:9110:9110" in rendered
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "v3.16.0" in readme
    assert "12.4.15" in readme


def test_demo_config_scrapes_the_fixture(mock_feilong) -> None:
    config = load_config(
        environ={
            "ZVM_EXPORTER_CONFIG": str(COMPOSE / "exporter.yaml"),
            "ZVM_EXPORTER_FEILONG_URL": mock_feilong.url,
        }
    )
    assert config.events.enabled is True
    assert config.vmcp.enabled is False
    assert config.feilong.verify_tls is False
    assert config.feilong.admin_token == "test-admin-token"
    assert config.scrape_interval == 30

    app = ExporterApp(config)
    try:
        first = app.collector.collect()
        second = app.collector.collect()
    finally:
        app.shutdown()

    assert first.up is True
    assert second.up is True
    assert app.collector.events.records == ()
    text = render_prometheus(second).decode()
    assert "zvm_system_info" in text
    assert "zvm_exporter_up " in text or "zvm_exporter_up{" in text
    assert 'zvm_events_total{event="zvm.guest.logon"} 0.0' in text
    assert 'zvm_events_total{event="zvm.guest.logoff"} 0.0' in text
