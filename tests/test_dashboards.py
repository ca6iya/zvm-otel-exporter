# SPDX-License-Identifier: Apache-2.0
"""Dashboard pack only names metrics the exporter or node_exporter expose."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from zvm_otel_exporter.catalog import CATALOG, prometheus_label, prometheus_name

ROOT = Path(__file__).resolve().parents[1]
GRAFANA = ROOT / "dashboards" / "grafana"
DYNATRACE = ROOT / "dashboards" / "dynatrace"

NODE_METRICS = {
    "node_cpu_seconds_total",
    "node_load1",
    "node_memory_MemAvailable_bytes",
    "node_memory_MemTotal_bytes",
    "node_uname_info",
}
ONEAGENT_METRICS = {
    "builtin:host.cpu.steal",
    "builtin:host.cpu.usage",
}
_METRIC = re.compile(r"\b(zvm_[a-z0-9_]+|node_[A-Za-z0-9_]+)\b(?!\s*(?:=~|!~|=\"|=\$))")
_OTEL = re.compile(r"\b(zvm(?:\.[a-z0-9_]+)+)\b")
_BUILTIN = re.compile(r"\bbuiltin:host\.[a-z0-9.]+\b")


def _prom_names() -> set[str]:
    return {prometheus_name(defn) for defn in CATALOG.values()} | NODE_METRICS


def _label_names() -> set[str]:
    names = {prometheus_label(label) for defn in CATALOG.values() for label in defn.labels}
    names.update({"instance", "mode", "job"})
    return names


def test_grafana_dashboards_are_described_and_reference_real_metrics() -> None:
    allowed = _prom_names()
    files = sorted(GRAFANA.glob("zvm-*.json"))
    assert len(files) == 3
    seen: set[str] = set()
    for path in files:
        body = json.loads(path.read_text(encoding="utf-8"))
        assert body["schemaVersion"] == 39
        assert body["title"]
        assert body["panels"]
        names = {item["name"] for item in body["templating"]["list"]}
        assert {"system", "lpar", "guest", "linux_instance"} <= names
        for panel in body["panels"]:
            assert panel["title"]
            assert len(panel["description"]) > 40
            for target in panel["targets"]:
                for name in _METRIC.findall(target["expr"]):
                    assert name in allowed, f"{path.name} {panel['title']} uses {name}"
                    seen.add(name)
    assert "zvm_system_info" in seen
    assert "zvm_system_cpu_utilization" in seen
    assert "node_cpu_seconds_total" in seen
    assert "zvm_paging_utilization" in seen


def test_prometheus_alerts_have_severity_and_duration() -> None:
    rules = yaml.safe_load((GRAFANA / "alerts.yml").read_text(encoding="utf-8"))
    alerts = [rule for group in rules["groups"] for rule in group["rules"]]
    assert alerts
    labels = _label_names()
    for alert in alerts:
        assert alert["for"]
        assert alert["labels"]["severity"] in {"warning", "critical"}
        assert alert["annotations"]["description"]
        for name in _METRIC.findall(alert["expr"]):
            if name in labels:
                continue
            assert name in _prom_names(), name
    paging = [alert for alert in alerts if "Paging" in alert["alert"] or "Spool" in alert["alert"]]
    assert paging
    assert all(alert["labels"]["severity"] == "warning" for alert in paging)
    promtool = shutil.which("promtool")
    if promtool:
        subprocess.run([promtool, "check", "rules", str(GRAFANA / "alerts.yml")], check=True)


def test_dynatrace_queries_use_catalog_or_oneagent_metrics() -> None:
    catalog = set(CATALOG)
    dimensions = {"zvm.host.name", "zvm.lpar.name", "zvm.guest.id", "dt.entity.host"}
    for path in sorted((DYNATRACE).glob("zvm-*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        assert body["tiles"]
        for tile in body["tiles"]:
            assert len(tile["description"]) > 20
            for name in _OTEL.findall(tile["dql"]):
                assert name in catalog or name in dimensions, name
            for name in _BUILTIN.findall(tile["dql"]):
                assert name in ONEAGENT_METRICS, name
    for path in sorted((DYNATRACE / "metric-events").glob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        selector = body["value"]["queryDefinition"]["metricSelector"]
        if selector.startswith("builtin:"):
            metric = ":".join(selector.split(":")[:2])
            assert metric in ONEAGENT_METRICS
        else:
            metric = selector.split(":", 1)[0]
            assert metric in catalog
        assert body["value"]["eventTemplate"]["severity"] in {"warning", "critical"}
        assert body["value"]["modelProperties"]["violatingSamples"] >= 3


def test_dashboard_doc_mentions_perfkit_and_prerequisites() -> None:
    text = (ROOT / "docs" / "dashboards.md").read_text(encoding="utf-8")
    assert "PerfKit" in text
    assert "node_exporter" in text
    assert "OneAgent" in text
    assert "zvm_system_info" in text
