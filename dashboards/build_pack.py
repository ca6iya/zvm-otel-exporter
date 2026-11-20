# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0
"""Write the Grafana and Dynatrace dashboard pack. Not used at runtime."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GRAFANA = ROOT / "grafana"
DYNATRACE = ROOT / "dynatrace"
EVENTS = DYNATRACE / "metric-events"

DS = {"type": "prometheus", "uid": "${DS_PROMETHEUS}"}


def _lpar(expr: str) -> str:
    """Keep series whose host is the selected system and LPAR. Info value is 1."""

    return (
        f"({expr}) * on(zvm_host_name) group_left(zvm_lpar_name) "
        'zvm_system_info{zvm_host_name=~"$system",zvm_lpar_name=~"$lpar"}'
    )


def _steps(marks: str | None) -> dict:
    """Color steps. ``None`` means no numeric threshold (bytes, counts, days)."""

    if marks == "utilization":
        steps = [
            {"color": "green", "value": None},
            {"color": "yellow", "value": 0.7},
            {"color": "red", "value": 0.85},
        ]
    elif marks == "up":
        steps = [
            {"color": "red", "value": None},
            {"color": "green", "value": 1},
        ]
    elif marks == "headroom":
        steps = [
            {"color": "red", "value": None},
            {"color": "yellow", "value": 0.15},
            {"color": "green", "value": 0.30},
        ]
    elif marks == "overcommit":
        steps = [
            {"color": "green", "value": None},
            {"color": "yellow", "value": 1.0},
            {"color": "red", "value": 1.5},
        ]
    else:
        steps = [{"color": "green", "value": None}]
    return {"mode": "absolute", "steps": steps}


def _panel(
    pid: int,
    title: str,
    description: str,
    expr: str,
    *,
    kind: str = "timeseries",
    unit: str = "none",
    x: int = 0,
    y: int = 0,
    w: int = 12,
    h: int = 8,
    legend: str = "{{zvm_host_name}}",
    instant: bool = False,
    marks: str | None = None,
) -> dict:
    target: dict = {"expr": expr, "refId": "A", "legendFormat": legend}
    if instant:
        target["instant"] = True
        target["format"] = "table"
    defaults: dict = {"unit": unit, "thresholds": _steps(marks)}
    if marks != "overcommit":
        defaults["min"] = 0
    return {
        "id": pid,
        "type": kind,
        "title": title,
        "description": description,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
    }


def _dashboard(uid: str, title: str, description: str, panels: list[dict]) -> dict:
    return {
        "uid": uid,
        "title": title,
        "description": description,
        "schemaVersion": 39,
        "tags": ["zvm", "mainframe"],
        "timezone": "browser",
        "refresh": "1m",
        "time": {"from": "now-6h", "to": "now"},
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "links": [],
        "annotations": {
            "list": [
                {
                    "name": "z/VM events",
                    "enable": True,
                    "hide": False,
                    "iconColor": "blue",
                    "datasource": DS,
                    "target": {
                        "expr": "increase(zvm_events_total[5m]) > 0",
                        "refId": "A",
                    },
                }
            ]
        },
        "templating": {
            "list": [
                {
                    "name": "DS_PROMETHEUS",
                    "type": "datasource",
                    "query": "prometheus",
                    "refresh": 1,
                    "current": {},
                },
                {
                    "name": "system",
                    "label": "z/VM system",
                    "type": "query",
                    "datasource": DS,
                    "definition": "label_values(zvm_system_info, zvm_host_name)",
                    "query": {
                        "query": "label_values(zvm_system_info, zvm_host_name)",
                        "refId": "A",
                    },
                    "refresh": 2,
                    "includeAll": True,
                    "allValue": ".*",
                    "multi": False,
                    "current": {},
                    "sort": 1,
                },
                {
                    "name": "lpar",
                    "label": "LPAR",
                    "type": "query",
                    "datasource": DS,
                    "definition": 'label_values(zvm_system_info{zvm_host_name=~"$system"}, zvm_lpar_name)',
                    "query": {
                        "query": 'label_values(zvm_system_info{zvm_host_name=~"$system"}, zvm_lpar_name)',
                        "refId": "A",
                    },
                    "refresh": 2,
                    "includeAll": True,
                    "allValue": ".*",
                    "multi": False,
                    "current": {},
                    "sort": 1,
                },
                {
                    "name": "guest",
                    "label": "Guest",
                    "type": "query",
                    "datasource": DS,
                    "definition": (
                        'label_values((zvm_guest_cpu_count_cpus{zvm_host_name=~"$system"}'
                        ' and on(zvm_host_name) zvm_system_info{zvm_host_name=~"$system",zvm_lpar_name=~"$lpar"}),'
                        " zvm_guest_id)"
                    ),
                    "query": {
                        "query": (
                            'label_values((zvm_guest_cpu_count_cpus{zvm_host_name=~"$system"}'
                            ' and on(zvm_host_name) zvm_system_info{zvm_host_name=~"$system",zvm_lpar_name=~"$lpar"}),'
                            " zvm_guest_id)"
                        ),
                        "refId": "A",
                    },
                    "refresh": 2,
                    "includeAll": True,
                    "allValue": ".*",
                    "multi": True,
                    "current": {},
                    "sort": 1,
                },
                {
                    "name": "linux_instance",
                    "label": "Linux on Z",
                    "type": "query",
                    "datasource": DS,
                    "definition": "label_values(node_uname_info, instance)",
                    "query": {"query": "label_values(node_uname_info, instance)", "refId": "A"},
                    "refresh": 2,
                    "includeAll": True,
                    "allValue": ".*",
                    "multi": True,
                    "current": {},
                    "sort": 1,
                },
            ]
        },
        "panels": panels,
    }


FLEET = [
    _panel(
        1,
        "Systems reporting",
        "Count of zvm_system_info series for the selected system and LPAR. The series exists while Prometheus is scraping that exporter. zvm_exporter_up itself has no host label, so it cannot be split by LPAR.",
        'count(zvm_system_info{zvm_host_name=~"$system",zvm_lpar_name=~"$lpar"})',
        kind="stat",
        x=0,
        y=0,
        w=6,
        h=4,
        legend="up",
    ),
    _panel(
        2,
        "Fleet CPU",
        "INDICATE LOAD average processor utilization for the selected system and LPAR. Green under 70 percent, yellow under 85, red at or above 85. Sustained red is a capacity conversation, not a page-space alarm.",
        _lpar('zvm_system_cpu_utilization{zvm_host_name=~"$system"}'),
        unit="percentunit",
        marks="utilization",
        x=6,
        y=0,
        w=18,
        h=8,
    ),
    _panel(
        3,
        "Exporter up",
        "1 when Feilong host collection succeeded. 0 means the process is up but Feilong failed. This series has no zvm_host_name label, so the LPAR variable does not filter it. A dead process is the Prometheus up metric, not this one.",
        "zvm_exporter_up",
        kind="stat",
        marks="up",
        x=0,
        y=4,
        w=6,
        h=4,
        legend="{{instance}}",
    ),
    _panel(
        4,
        "Identity",
        "One row per exporter for the selected system and LPAR. zvm_lpar_name, CPC type, and site are only on this series. Other panels join it on zvm_host_name.",
        'zvm_system_info{zvm_host_name=~"$system",zvm_lpar_name=~"$lpar"}',
        kind="table",
        instant=True,
        x=0,
        y=8,
        w=24,
        h=8,
        legend="",
    ),
    _panel(
        5,
        "Host memory used",
        "Feilong memory_mb_used divided by memory_mb. This is LPAR memory the hypervisor reports, not Linux MemAvailable.",
        _lpar(
            'zvm_host_memory_usage_bytes{zvm_host_name=~"$system"}'
            ' / zvm_host_memory_limit_bytes{zvm_host_name=~"$system"}'
        ),
        unit="percentunit",
        marks="utilization",
        x=0,
        y=16,
        w=12,
        h=8,
        legend="{{zvm_host_name}}",
    ),
    _panel(
        6,
        "Paging space used",
        "Pages in use divided by pages allocated, from QUERY ALLOC PAGE. Trend this. A high value is a warning, not a page-fault outage by itself.",
        _lpar('zvm_paging_utilization{zvm_host_name=~"$system"}'),
        unit="percentunit",
        marks="utilization",
        x=12,
        y=16,
        w=12,
        h=8,
    ),
    _panel(
        7,
        "Spool space used",
        "Spool pages in use divided by spool pages allocated. Watch the slope. Do not page someone for a single sample.",
        _lpar('zvm_spool_utilization{zvm_host_name=~"$system"}'),
        unit="percentunit",
        marks="utilization",
        x=0,
        y=24,
        w=12,
        h=8,
    ),
    _panel(
        8,
        "SMAPI healthy",
        "1 when Feilong reports the SMAPI layer healthy. 0 means guest stats may be missing while host info still arrives. This series has no host label, so the LPAR variable does not filter it.",
        "zvm_smapi_healthy",
        kind="stat",
        marks="up",
        x=12,
        y=24,
        w=12,
        h=8,
        legend="smapi",
    ),
    _panel(
        9,
        "Events since start",
        "Cumulative zvm_events_total by event name. The series exists only when events.enabled is true. Guest ids are not labels. A rise is a logon, logoff, relocate, or health change, not a capacity alarm.",
        "zvm_events_total",
        x=0,
        y=32,
        w=24,
        h=8,
        legend="{{event}}",
    ),
]

DIAGNOSIS = [
    _panel(
        1,
        "z/VM CPU utilization",
        "System-wide AVGPROC from INDICATE LOAD, as a ratio. If this is high and guest steal is high, the LPAR is out of CPU. If this is low and steal is high, look at shares and other LPARs on the CPC, which this exporter does not see.",
        _lpar('zvm_system_cpu_utilization{zvm_host_name=~"$system"}'),
        unit="percentunit",
        marks="utilization",
        x=0,
        y=0,
        w=8,
        h=8,
        legend="z/VM",
    ),
    _panel(
        2,
        "Guest CPU time",
        "Rate of virtual CPU seconds. A value of 2 means about two cores of guest CPU. Compare with zvm_guest_cpu_count_cpus. A guest using a small fraction of its defined CPUs is an oversized-CPU candidate, not a steal problem.",
        _lpar(
            'rate(zvm_guest_cpu_time_seconds_total{zvm_host_name=~"$system",zvm_guest_id=~"$guest"}[5m])'
        ),
        unit="short",
        x=8,
        y=0,
        w=8,
        h=8,
        legend="{{zvm_guest_id}}",
    ),
    _panel(
        3,
        "Linux CPU steal",
        "node_exporter steal time for the selected Linux on Z instances. Steal is time the guest was runnable and the hypervisor ran something else. High steal with high z/VM CPU means the system is busy. High steal with low z/VM CPU means look outside this LPAR.",
        'avg by (instance) (rate(node_cpu_seconds_total{mode="steal",instance=~"$linux_instance"}[5m]))',
        unit="percentunit",
        marks="utilization",
        x=16,
        y=0,
        w=8,
        h=8,
        legend="{{instance}}",
    ),
    _panel(
        4,
        "Linux load",
        "node_load1 from node_exporter. Load above the number of online Linux CPUs, together with steal, means the guest is waiting. Load without steal means the guest is busy inside Linux.",
        'node_load1{instance=~"$linux_instance"}',
        x=0,
        y=8,
        w=8,
        h=8,
        legend="{{instance}}",
    ),
    _panel(
        5,
        "Defined guest CPUs",
        "Virtual CPUs Feilong reports for the guest. This is capacity, not usage. Pair it with Guest CPU time to see idle cores.",
        _lpar('zvm_guest_cpu_count_cpus{zvm_host_name=~"$system",zvm_guest_id=~"$guest"}'),
        x=8,
        y=8,
        w=8,
        h=8,
        legend="{{zvm_guest_id}}",
    ),
    _panel(
        6,
        "Guest memory in use",
        "Feilong used_mem_kb for the guest, in bytes. This is the z/VM view of the guest, not Linux MemAvailable.",
        _lpar('zvm_guest_memory_usage_bytes{zvm_host_name=~"$system",zvm_guest_id=~"$guest"}'),
        unit="bytes",
        x=16,
        y=8,
        w=8,
        h=8,
        legend="{{zvm_guest_id}}",
    ),
    _panel(
        7,
        "Linux memory available",
        "node_memory_MemAvailable_bytes from node_exporter. Low available memory with low steal is a Linux sizing issue. Low available memory with high steal can be the guest paging because it is not being dispatched.",
        'node_memory_MemAvailable_bytes{instance=~"$linux_instance"}',
        unit="bytes",
        x=0,
        y=16,
        w=12,
        h=8,
        legend="{{instance}}",
    ),
    _panel(
        8,
        "Linux memory size",
        "node_memory_MemTotal_bytes. Compare with the z/VM guest memory total on the capacity dashboard. A large MemTotal that sits idle is an oversized guest.",
        'node_memory_MemTotal_bytes{instance=~"$linux_instance"}',
        unit="bytes",
        x=12,
        y=16,
        w=12,
        h=8,
        legend="{{instance}}",
    ),
]

CAPACITY = [
    _panel(
        1,
        "Memory overcommit",
        "Sum of guest-reported total memory (Feilong total_memory, treated as kilobytes) divided by LPAR memory. Above 1 means guests are defined with more memory than the LPAR has. This is not Linux usage. max_mem is a ceiling and is not used here because it overstates what is defined.",
        _lpar(
            'sum by (zvm_host_name) (zvm_guest_memory_total_bytes{zvm_host_name=~"$system"})'
            ' / zvm_host_memory_limit_bytes{zvm_host_name=~"$system"}'
        ),
        unit="short",
        marks="overcommit",
        x=0,
        y=0,
        w=8,
        h=8,
        legend="overcommit",
    ),
    _panel(
        2,
        "CPU headroom",
        "One minus INDICATE LOAD utilization. Headroom near zero means little room for a new guest or a CPU spike. It is not a forecast.",
        _lpar('1 - zvm_system_cpu_utilization{zvm_host_name=~"$system"}'),
        unit="percentunit",
        marks="headroom",
        x=8,
        y=0,
        w=8,
        h=8,
        legend="headroom",
    ),
    _panel(
        3,
        "Guest memory used ratio",
        "used_mem divided by max_mem. A guest with a large limit and a ratio near zero is a right-sizing candidate. max_mem is the Feilong ceiling, so confirm the directory definition before shrinking a guest.",
        _lpar(
            'zvm_guest_memory_usage_bytes{zvm_host_name=~"$system"}'
            ' / zvm_guest_memory_limit_bytes{zvm_host_name=~"$system"}'
        ),
        unit="percentunit",
        marks="utilization",
        x=16,
        y=0,
        w=8,
        h=8,
        legend="{{zvm_guest_id}}",
    ),
    _panel(
        4,
        "Guest CPU used vs defined",
        "CPU-seconds per second over 1 hour, divided by defined virtual CPUs. A ratio near zero for many hours is an idle or oversized CPU definition.",
        _lpar(
            'rate(zvm_guest_cpu_time_seconds_total{zvm_host_name=~"$system"}[1h])'
            ' / zvm_guest_cpu_count_cpus{zvm_host_name=~"$system"}'
        ),
        unit="percentunit",
        marks="utilization",
        x=0,
        y=8,
        w=12,
        h=8,
        legend="{{zvm_guest_id}}",
    ),
    _panel(
        5,
        "Paging in 7 days",
        "predict_linear of paging utilization over the last 6 hours, projected 7 days ahead. A value above 1 means the straight line crosses full. Negative slope means usage is falling. This is a sketch, not a capacity plan.",
        _lpar('predict_linear(zvm_paging_utilization{zvm_host_name=~"$system"}[6h], 86400 * 7)'),
        unit="percentunit",
        marks="utilization",
        x=12,
        y=8,
        w=12,
        h=8,
        legend="paging",
    ),
    _panel(
        6,
        "Spool in 7 days",
        "Same linear projection for spool utilization. Use it to schedule spool cleanup. Do not treat a single projection as an incident.",
        _lpar('predict_linear(zvm_spool_utilization{zvm_host_name=~"$system"}[6h], 86400 * 7)'),
        unit="percentunit",
        marks="utilization",
        x=0,
        y=16,
        w=12,
        h=8,
        legend="spool",
    ),
    _panel(
        7,
        "Days until paging reaches 90 percent",
        "Remaining distance to 0.9 divided by the 6-hour derivative, in days. Ignore negative or huge values: the slope is flat or downward. Alerting uses a 7-day projection instead of this raw number.",
        _lpar(
            '(0.9 - zvm_paging_utilization{zvm_host_name=~"$system"})'
            ' / deriv(zvm_paging_utilization{zvm_host_name=~"$system"}[6h]) / 86400'
        ),
        unit="d",
        x=12,
        y=16,
        w=12,
        h=8,
        legend="days",
    ),
]

ALERTS = """\
# SPDX-License-Identifier: Apache-2.0
# The job label below is the Prometheus scrape job. Name the job
# zvm-otel-exporter, or edit this matcher to the job you actually use.
groups:
  - name: zvm.exporter
    rules:
      - alert: ZvmExporterProcessDown
        expr: up{job="zvm-otel-exporter"} == 0 or absent(zvm_exporter_up)
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: z/VM exporter process is not being scraped
          description: Prometheus is not scraping the exporter. This rule assumes the scrape job label is zvm-otel-exporter. Change the job matcher if your configuration uses another name. up == 0 fires per target while Prometheus still remembers it. absent(zvm_exporter_up) fires when no exporter series exist at all. It does not mean Feilong failed.
      - alert: ZvmFeilongDown
        expr: zvm_exporter_up == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: Feilong host collection is failing
          description: The exporter process is being scraped and zvm_exporter_up has been 0 for 5 minutes. Feilong is unreachable or host collection failed. This is not a dead process. A dead process is ZvmExporterProcessDown.
      - alert: ZvmSmapiDown
        expr: zvm_smapi_healthy == 0
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: SMAPI is reported unhealthy
          description: zvm_smapi_healthy has been 0 for 15 minutes. Guest stats may be missing. The exporter process and Feilong host collection can still be up.
      - alert: ZvmExporterStale
        expr: zvm_exporter_scrape_stale == 1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: z/VM exporter is serving a stale snapshot
          description: Host collection failed and previous series are still being served. Check Feilong before trusting the dashboard.
      - alert: ZvmVmcpDown
        expr: zvm_vmcp_up == 0
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: vmcp commands are failing
          description: The last vmcp pass did not succeed. Paging, spool, and system CPU utilization are missing or old. Privilege class D is required for QUERY ALLOC.
      - alert: ZvmVmcpCacheStale
        expr: zvm_vmcp_cache_age_seconds > 900
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: vmcp cache is older than 15 minutes
          description: Cache age stayed above 900 seconds. The command pass is backing off or not running.
      - alert: ZvmVmcpFailures
        expr: zvm_vmcp_consecutive_failures > 2
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: vmcp has failed more than twice in a row
          description: Consecutive failures remain above 2. Read the exporter log for timeout, overflow, or an HCP error.
      - alert: ZvmVmcpSlow
        expr: zvm_vmcp_command_duration_seconds > 10
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: vmcp command pass is slow
          description: The last pass took more than 10 seconds. That is close to the timeout budget and adds load. Check that vmcp is not hanging.
  - name: zvm.capacity
    rules:
      - alert: ZvmCpuHigh
        expr: zvm_system_cpu_utilization > 0.85
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: z/VM CPU utilization above 85 percent
          description: INDICATE LOAD stayed above 85 percent for 15 minutes. Look at guest CPU time and Linux steal before adding CPUs.
      - alert: ZvmCpuCritical
        expr: zvm_system_cpu_utilization > 0.95
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: z/VM CPU utilization above 95 percent
          description: INDICATE LOAD stayed above 95 percent for 15 minutes. The LPAR has almost no CPU headroom.
      - alert: ZvmLinuxStealHigh
        expr: avg by (instance) (rate(node_cpu_seconds_total{mode="steal"}[5m])) > 0.10
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: Linux CPU steal above 10 percent
          description: node_exporter reports steal above 10 percent for 15 minutes. Compare with z/VM CPU utilization on the same system. This rule does nothing until node_exporter is scraped.
      - alert: ZvmLinuxStealCritical
        expr: avg by (instance) (rate(node_cpu_seconds_total{mode="steal"}[5m])) > 0.25
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: Linux CPU steal above 25 percent
          description: Steal stayed above 25 percent. The guest is waiting on the hypervisor often enough to explain application latency.
      - alert: ZvmMemoryOvercommitHigh
        expr: sum by (zvm_host_name) (zvm_guest_memory_total_bytes) / zvm_host_memory_limit_bytes > 1.5
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: Guest memory is more than 1.5 times LPAR memory
          description: Sum of guest-reported total memory exceeds 1.5 times the LPAR. Confirm total_memory units on a real system before acting.
      - alert: ZvmMemoryOvercommitCritical
        expr: sum by (zvm_host_name) (zvm_guest_memory_total_bytes) / zvm_host_memory_limit_bytes > 3
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: Guest memory is more than 3 times LPAR memory
          description: Defined guest memory is far above real LPAR memory. Warning only, same policy as paging and spool. This does not page.
      - alert: ZvmPagingForecast
        expr: predict_linear(zvm_paging_utilization[6h], 86400 * 7) > 0.9
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: Paging space is forecast to pass 90 percent within 7 days
          description: A straight line through the last 6 hours of paging utilization crosses 0.9 inside a week. This is warning only.
      - alert: ZvmSpoolForecast
        expr: predict_linear(zvm_spool_utilization[6h], 86400 * 7) > 0.9
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: Spool space is forecast to pass 90 percent within 7 days
          description: A straight line through the last 6 hours of spool utilization crosses 0.9 inside a week. This is warning only.
      - alert: ZvmPagingHigh
        expr: zvm_paging_utilization > 0.8
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: Paging space is above 80 percent
          description: Paging utilization stayed above 80 percent. Warning only. Look at the 7-day projection before adding volumes.
      - alert: ZvmSpoolHigh
        expr: zvm_spool_utilization > 0.8
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: Spool space is above 80 percent
          description: Spool utilization stayed above 80 percent. Warning only. Clean spool before treating this as an outage.
"""


def _dyn_var(key: str, query: str) -> dict:
    return {
        "version": 2,
        "key": key,
        "type": "query",
        "visible": True,
        "editable": True,
        "multiple": True,
        "defaultValue": ["*"],
        "input": query,
    }


def _scoped_dql(metric: str, *, guest: bool = False) -> str:
    """Timeseries filtered by the dashboard system and LPAR variables.

    z/VM metric dimensions do not all carry zvm.lpar.name. The lookup keeps
    hosts whose zvm.system.info row matches the selected LPAR.
    """

    by = "{zvm.host.name, zvm.guest.id}" if guest else "{zvm.host.name}"
    guest_filter = "\n| filter in(zvm.guest.id, array($guest))" if guest else ""
    return (
        f"timeseries avg({metric}), by:{by}\n"
        "| lookup [\n"
        "    timeseries avg(zvm.system.info), by:{zvm.host.name, zvm.lpar.name}\n"
        "    | filter in(zvm.lpar.name, array($lpar))\n"
        "  ], sourceField:zvm.host.name, lookupField:zvm.host.name\n"
        "| filter in(zvm.host.name, array($system))"
        f"{guest_filter}"
    )


def _dyn_dashboard(title: str, summary: str, tiles: list[dict]) -> dict:
    """Dynatrace Dashboards document, schema version 21.

    Upload this file from Dashboards, Upload. It is the document content
    (version, variables, tiles, layouts), which is what Download writes.
    """

    body_tiles: dict[str, dict] = {
        "0": {
            "type": "markdown",
            "content": (
                f"# {title}\n\n{summary}\n\n"
                "State-change logs, when events are enabled: "
                '`fetch logs | filter startsWith(event.name, "zvm.")`'
            ),
        }
    }
    layouts: dict[str, dict] = {"0": {"x": 0, "y": 0, "w": 24, "h": 3}}
    for index, tile in enumerate(tiles, start=1):
        key = str(index)
        body_tiles[key] = {
            "type": "data",
            "title": tile["title"],
            "description": tile["description"],
            "query": tile["query"],
            "visualization": tile["visualization"],
        }
        layouts[key] = {"x": tile["x"], "y": tile["y"], "w": tile["w"], "h": tile["h"]}
    return {
        "version": 21,
        "variables": [
            _dyn_var(
                "system",
                "timeseries avg(zvm.system.info), by:{zvm.host.name}"
                " | fields zvm.host.name | dedup zvm.host.name",
            ),
            _dyn_var(
                "lpar",
                "timeseries avg(zvm.system.info), by:{zvm.host.name, zvm.lpar.name}"
                " | filter in(zvm.host.name, array($system))"
                " | fields zvm.lpar.name | dedup zvm.lpar.name",
            ),
            _dyn_var(
                "guest",
                "timeseries avg(zvm.guest.cpu.count), by:{zvm.host.name, zvm.guest.id}"
                " | lookup ["
                " timeseries avg(zvm.system.info), by:{zvm.host.name, zvm.lpar.name}"
                " | filter in(zvm.lpar.name, array($lpar))"
                " ], sourceField:zvm.host.name, lookupField:zvm.host.name"
                " | filter in(zvm.host.name, array($system))"
                " | fields zvm.guest.id | dedup zvm.guest.id",
            ),
        ],
        "tiles": body_tiles,
        "layouts": layouts,
        "settings": {
            "defaultTimeframe": {"enabled": True, "value": {"from": "now()-6h", "to": "now()"}}
        },
    }


def _tile(title: str, description: str, query: str, x: int, y: int, w: int, h: int) -> dict:
    return {
        "title": title,
        "description": description,
        "query": query,
        "visualization": "lineChart",
        "x": x,
        "y": y,
        "w": w,
        "h": h,
    }


def _event(
    name: str,
    summary: str,
    description: str,
    selector: str,
    threshold: float,
    severity: str,
    samples: int,
    violating: int,
    condition: str = "ABOVE",
    alert_on_no_data: bool = False,
) -> dict:
    return {
        "schemaId": "builtin:anomaly-detection.metric-events",
        "scope": "environment",
        "value": {
            "enabled": True,
            "summary": summary,
            "queryDefinition": {"type": "METRIC_SELECTOR", "metricSelector": selector},
            "modelProperties": {
                "type": "STATIC_THRESHOLD",
                "threshold": threshold,
                "alertOnNoData": alert_on_no_data,
                "alertCondition": condition,
                "violatingSamples": violating,
                "samples": samples,
                "dealertingSamples": samples,
            },
            "eventTemplate": {
                "title": summary,
                "description": description,
                "eventType": "AVAILABILITY" if severity == "critical" else "RESOURCE_CONTENTION",
                "davisMerge": True,
            },
        },
        "fileName": name,
    }


EVENTS_SPEC = [
    _event(
        "zvm-exporter-missing.json",
        "z/VM exporter metrics are missing",
        "No zvm.exporter.up samples arrived. The process stopped sending OTLP. This is not a Feilong failure. alertOnNoData is set and the threshold is below any real value so a present 0 does not fire this event.",
        "zvm.exporter.up:avg",
        -1,
        "critical",
        5,
        3,
        "BELOW",
        True,
    ),
    _event(
        "zvm-feilong-down.json",
        "Feilong host collection is failing",
        "zvm.exporter.up is present and below 1, so the process is exporting and Feilong host collection failed. alertOnNoData is false so a dead process does not also raise this event.",
        "zvm.exporter.up:avg",
        1,
        "critical",
        5,
        3,
        "BELOW",
        False,
    ),
    _event(
        "zvm-smapi-down.json",
        "SMAPI is unhealthy",
        "zvm.smapi.healthy is present and below 1. Guest stats may be missing while the process and Feilong host collection are still up.",
        "zvm.smapi.healthy:avg",
        1,
        "warning",
        5,
        3,
        "BELOW",
        False,
    ),
    _event(
        "zvm-overcommit-high.json",
        "Guest memory exceeds LPAR memory",
        "Sum of zvm.guest.memory.total divided by zvm.host.memory.limit is above 1.5. Warning only, same policy as paging and spool. There is no critical overcommit event.",
        "(zvm.guest.memory.total:sum)/(zvm.host.memory.limit:avg)",
        1.5,
        "warning",
        5,
        3,
    ),
    _event(
        "zvm-cpu-high.json",
        "z/VM CPU above 85 percent",
        "zvm.system.cpu.utilization stayed above 0.85. Compare with guest CPU and host steal.",
        "zvm.system.cpu.utilization:avg",
        0.85,
        "warning",
        5,
        3,
    ),
    _event(
        "zvm-cpu-critical.json",
        "z/VM CPU above 95 percent",
        "zvm.system.cpu.utilization stayed above 0.95.",
        "zvm.system.cpu.utilization:avg",
        0.95,
        "critical",
        5,
        3,
    ),
    _event(
        "zvm-steal-high.json",
        "Linux CPU steal above 10 percent",
        "OneAgent host CPU steal stayed above 10 percent. Requires the host to be monitored by OneAgent.",
        "builtin:host.cpu.steal:avg",
        10,
        "warning",
        5,
        3,
    ),
    _event(
        "zvm-paging-high.json",
        "z/VM paging space above 80 percent",
        "zvm.paging.utilization stayed above 0.8. Warning only.",
        "zvm.paging.utilization:avg",
        0.8,
        "warning",
        5,
        3,
    ),
    _event(
        "zvm-spool-high.json",
        "z/VM spool space above 80 percent",
        "zvm.spool.utilization stayed above 0.8. Warning only.",
        "zvm.spool.utilization:avg",
        0.8,
        "warning",
        5,
        3,
    ),
]


def main() -> None:
    GRAFANA.mkdir(parents=True, exist_ok=True)
    EVENTS.mkdir(parents=True, exist_ok=True)
    dashboards = {
        "zvm-fleet.json": _dashboard(
            "zvm-fleet",
            "z/VM fleet",
            "One glance across z/VM systems. Green, yellow, and red on CPU use the 70 and 85 percent marks.",
            FLEET,
        ),
        "zvm-diagnosis.json": _dashboard(
            "zvm-diagnosis",
            "z/VM and Linux diagnosis",
            "z/VM CPU, guest CPU, and Linux steal and memory on one board. Use it to decide whether the guest waited on the hypervisor.",
            DIAGNOSIS,
        ),
        "zvm-capacity.json": _dashboard(
            "zvm-capacity",
            "z/VM capacity",
            "Overcommit, idle guests, CPU headroom, and a 7-day linear sketch of paging and spool. Not a replacement for a capacity study.",
            CAPACITY,
        ),
    }
    for name, body in dashboards.items():
        (GRAFANA / name).write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    (GRAFANA / "alerts.yml").write_text(ALERTS, encoding="utf-8")
    (GRAFANA / "provisioning.yaml").write_text(
        "# SPDX-License-Identifier: Apache-2.0\n"
        "apiVersion: 1\n"
        "providers:\n"
        "  - name: zvm\n"
        "    folder: z/VM\n"
        "    type: file\n"
        "    options:\n"
        "      path: /var/lib/grafana/dashboards/zvm\n",
        encoding="utf-8",
    )
    dyn = {
        "zvm-fleet.json": _dyn_dashboard(
            "z/VM fleet",
            "Fleet status from OTLP metrics. The system variable lists hosts. The LPAR variable lists LPARs on those hosts. Host tiles keep a host only when zvm.system.info matches both. Exporter up has no host attribute, so that tile is not filtered.",
            [
                _tile(
                    "CPU by system",
                    "Average INDICATE LOAD utilization for the selected system and LPAR. High CPU plus high steal means the LPAR is busy.",
                    _scoped_dql("zvm.system.cpu.utilization"),
                    0,
                    3,
                    12,
                    8,
                ),
                _tile(
                    "Exporter up",
                    "1 when the last Feilong host scrape worked. 0 means Feilong failed while the process was still exporting. zvm.exporter.up has no host attribute, so this tile is not split by host or LPAR. A missing series is the separate missing-data event.",
                    "timeseries avg(zvm.exporter.up)",
                    12,
                    3,
                    12,
                    8,
                ),
                _tile(
                    "Paging utilization",
                    "Paging pages in use over pages allocated for the selected system and LPAR. Trend, not an outage signal.",
                    _scoped_dql("zvm.paging.utilization"),
                    0,
                    11,
                    12,
                    8,
                ),
                _tile(
                    "Spool utilization",
                    "Spool pages in use over pages allocated for the selected system and LPAR.",
                    _scoped_dql("zvm.spool.utilization"),
                    12,
                    11,
                    12,
                    8,
                ),
            ],
        ),
        "zvm-diagnosis.json": _dyn_dashboard(
            "z/VM and Linux diagnosis",
            "Put z/VM CPU next to OneAgent steal so a slow application can be split into guest wait versus guest work. OneAgent tiles are not filtered by the z/VM LPAR variable.",
            [
                _tile(
                    "z/VM CPU",
                    "zvm.system.cpu.utilization for the selected system and LPAR.",
                    _scoped_dql("zvm.system.cpu.utilization"),
                    0,
                    3,
                    12,
                    8,
                ),
                _tile(
                    "Guest CPU time",
                    "Cumulative guest CPU counter for the selected guest, system, and LPAR. Apply a rate in the tile if you need cores. DQL timeseries does not take a PromQL rate().",
                    _scoped_dql("zvm.guest.cpu.time", guest=True),
                    12,
                    3,
                    12,
                    8,
                ),
                _tile(
                    "OneAgent CPU steal",
                    "builtin:host.cpu.steal from OneAgent, percent. Empty until the Linux guest is monitored by OneAgent. This tile does not use the z/VM LPAR variable.",
                    "timeseries avg(builtin:host.cpu.steal), by:{dt.entity.host}",
                    0,
                    11,
                    12,
                    8,
                ),
                _tile(
                    "OneAgent CPU usage",
                    "builtin:host.cpu.usage. Compare with steal. Usage without steal is work inside Linux. This tile does not use the z/VM LPAR variable.",
                    "timeseries avg(builtin:host.cpu.usage), by:{dt.entity.host}",
                    12,
                    11,
                    12,
                    8,
                ),
            ],
        ),
        "zvm-capacity.json": _dyn_dashboard(
            "z/VM capacity",
            "Memory overcommit is guest total over host limit. Forecast tiles append the DQL forecast command. All four tiles follow the system and LPAR variables.",
            [
                _tile(
                    "Host memory",
                    "LPAR memory usage from Feilong, in bytes, for the selected system and LPAR.",
                    _scoped_dql("zvm.host.memory.usage"),
                    0,
                    3,
                    12,
                    8,
                ),
                _tile(
                    "Guest memory total",
                    "Guest-reported total memory for the selected system and LPAR. Divide by host memory limit for overcommit.",
                    _scoped_dql("zvm.guest.memory.total"),
                    12,
                    3,
                    12,
                    8,
                ),
                _tile(
                    "Paging forecast",
                    "DQL forecast of paging utilization. A rising forecast through 0.9 inside a week is a warning, not an incident.",
                    _scoped_dql("zvm.paging.utilization") + "\n| forecast",
                    0,
                    11,
                    12,
                    8,
                ),
                _tile(
                    "Spool forecast",
                    "DQL forecast of spool utilization. Warning only.",
                    _scoped_dql("zvm.spool.utilization") + "\n| forecast",
                    12,
                    11,
                    12,
                    8,
                ),
            ],
        ),
    }
    for name, body in dyn.items():
        (DYNATRACE / name).write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    for event in EVENTS_SPEC:
        name = event.pop("fileName")
        (EVENTS / name).write_text(json.dumps(event, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
