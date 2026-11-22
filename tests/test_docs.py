# SPDX-License-Identifier: Apache-2.0
"""Documentation stays aligned with the catalog."""

from __future__ import annotations

import json
import re
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
    assert "earlier commit" in contributing
    assert "latest commit" in contributing


def _glob_match(pattern: str, path: str) -> bool:
    """Match one CodeRabbit path glob. `**` crosses directories. `*` does not."""
    regex: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            regex.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            regex.append(".*")
            index += 2
        elif pattern[index] == "*":
            regex.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            regex.append("[^/]")
            index += 1
        else:
            regex.append(re.escape(pattern[index]))
            index += 1
    return re.fullmatch("".join(regex), path) is not None


def _filter_includes(path: str, filters: list[str]) -> bool:
    """Match CodeRabbit path filters. A positive pattern limits the set. With
    none, every path starts included. An exclusion then drops a path, in any
    order.
    """
    positives = [item for item in filters if not item.startswith("!")]
    negatives = [item[1:] for item in filters if item.startswith("!")]
    if positives and not any(_glob_match(pattern, path) for pattern in positives):
        return False
    return not any(_glob_match(pattern, path) for pattern in negatives)


def test_coderabbit_skips_generated_dashboards() -> None:
    config = yaml.safe_load((ROOT / ".coderabbit.yaml").read_text(encoding="utf-8"))
    reviews = config["reviews"]
    filters = reviews["path_filters"]
    assert reviews["auto_review"]["enabled"] is True
    assert reviews["auto_review"]["drafts"] is False
    assert reviews["auto_review"]["auto_pause_after_reviewed_commits"] == 0
    paths = [item["path"] for item in reviews["path_instructions"]]
    assert "src/**" in paths
    assert "dashboards/**" in paths

    included = (
        "src/zvm_otel_exporter/cli.py",
        "README.md",
        "tests/test_docs.py",
        "dashboards/grafana/alerts.yml",
        "dashboards/build_pack.py",
    )
    excluded = (
        "dashboards/grafana/zvm.json",
        "dashboards/dynatrace/x/y.json",
    )
    for path in included:
        assert _filter_includes(path, filters), path
    for path in excluded:
        assert not _filter_includes(path, filters), path

    narrowed = ["src/**" if item == "**" else item for item in filters]
    assert _filter_includes("src/zvm_otel_exporter/cli.py", narrowed)
    assert not _filter_includes("README.md", narrowed)
    assert not _filter_includes("tests/test_docs.py", narrowed)
    assert not _filter_includes("dashboards/grafana/alerts.yml", narrowed)

    reordered = [item for item in filters if item != "**"] + ["**"]
    assert not _filter_includes("dashboards/grafana/zvm.json", reordered)
    assert _filter_includes("README.md", reordered)
    exclusions_only = [item for item in filters if item.startswith("!")]
    assert _filter_includes("README.md", exclusions_only)
    assert not _filter_includes("dashboards/grafana/zvm.json", exclusions_only)


def test_grafana_dashboard_and_examples() -> None:
    dashboard = json.loads((ROOT / "examples" / "grafana" / "zvm-dashboard.json").read_text())
    blob = json.dumps(dashboard)
    assert "zvm_host_cpu_count_cpus" in blob
    assert "zvm_guest_cpu_time_seconds_total" in blob
    assert dashboard["title"]
    collector = (ROOT / "examples" / "otel-collector.yaml").read_text(encoding="utf-8")
    assert "otlp" in collector
    assert "dynatrace" in collector.lower()
    assert "otel-collector-dynatrace.yaml" in collector
    assert "otel-collector-grafana.yaml" in collector
    assert "otel-collector-splunk.yaml" in collector
    unit = (ROOT / "examples" / "systemd" / "zvm-otel-exporter.service").read_text()
    assert "9110" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert "zvm-otel-exporter" in unit
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pytest" in workflow
    assert "ruff check" in workflow


def test_collector_templates_keep_tokens_in_the_environment() -> None:
    names = {
        "otel-collector-dynatrace.yaml": ("otlphttp/dynatrace", "${env:DT_OTLP_ENDPOINT}"),
        "otel-collector-grafana.yaml": ("otlphttp/grafana", "${env:GRAFANA_OTLP_ENDPOINT}"),
        "otel-collector-splunk.yaml": ("signalfx", "${env:SPLUNK_REALM}"),
    }
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for name, (exporter, placeholder) in names.items():
        text = (ROOT / "examples" / name).read_text(encoding="utf-8")
        parsed = yaml.safe_load(text)
        assert exporter in parsed["exporters"]
        assert parsed["service"]["pipelines"]["metrics"]["exporters"] == [exporter]
        assert placeholder in text
        assert "not been exercised" in text
        assert "Api-Token dt" not in text
        assert "Basic dGVzd" not in text
        assert name in readme
    dynatrace = yaml.safe_load(
        (ROOT / "examples" / "otel-collector-dynatrace.yaml").read_text(encoding="utf-8")
    )
    # Wiring only. CI does not run a collector, so this does not show that
    # cumulative values 10 and 15 become a delta of 5.
    assert dynatrace["service"]["pipelines"]["metrics"]["processors"] == [
        "cumulativetodelta",
        "batch",
    ]
    assert dynatrace["processors"]["cumulativetodelta"]["initial_value"] == "drop"
    assert "cumulative OTLP intake" not in readme
    assert "does not ingest a cumulative counter" in readme


def test_version_matches_metadata() -> None:
    from importlib.metadata import version

    assert version("zvm-otel-exporter") == __version__
