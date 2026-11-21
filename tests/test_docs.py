# SPDX-License-Identifier: Apache-2.0
"""Documentation stays aligned with the catalog."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from zvm_otel_exporter import __version__
from zvm_otel_exporter.catalog import CATALOG

ROOT = Path(__file__).resolve().parents[1]


def test_readme_lists_every_metric_and_the_gaps() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [name for name in CATALOG if f"`{name}`" not in readme]
    assert not missing
    for phrase in ("paging", "spool", "Dynatrace", "Feilong", "9110", "xCAT"):
        assert phrase in readme


def test_license_and_contributing() -> None:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in license_text
    assert "Version 2.0" in license_text
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "pytest" in contributing
    assert "Signed-off-by" in contributing
    assert "CodeRabbit" in contributing
    assert ".coderabbit.yaml" in contributing
    assert "rate-limited" in contributing
    assert "does not count" in contributing


def test_coderabbit_skips_generated_dashboards() -> None:
    config = yaml.safe_load((ROOT / ".coderabbit.yaml").read_text(encoding="utf-8"))
    reviews = config["reviews"]
    filters = reviews["path_filters"]
    assert "!dashboards/grafana/*.json" in filters
    assert "!dashboards/dynatrace/**/*.json" in filters
    assert reviews["auto_review"]["enabled"] is True
    assert reviews["auto_review"]["drafts"] is False
    assert reviews["auto_review"]["auto_pause_after_reviewed_commits"] == 0
    paths = [item["path"] for item in reviews["path_instructions"]]
    assert "src/**" in paths
    assert "dashboards/**" in paths


def test_grafana_dashboard_and_examples() -> None:
    dashboard = json.loads((ROOT / "examples" / "grafana" / "zvm-dashboard.json").read_text())
    blob = json.dumps(dashboard)
    assert "zvm_host_cpu_count_cpus" in blob
    assert "zvm_guest_cpu_time_seconds_total" in blob
    assert dashboard["title"]
    collector = (ROOT / "examples" / "otel-collector.yaml").read_text(encoding="utf-8")
    assert "otlp" in collector
    assert "dynatrace" in collector.lower()
    unit = (ROOT / "examples" / "systemd" / "zvm-otel-exporter.service").read_text()
    assert "9110" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert "zvm-otel-exporter" in unit
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pytest" in workflow
    assert "ruff check" in workflow


def test_version_matches_metadata() -> None:
    from importlib.metadata import version

    assert version("zvm-otel-exporter") == __version__
