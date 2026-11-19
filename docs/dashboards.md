# Dashboard pack

This pack is a thin view over the exporter plus Linux guest metrics you already collect. It does not read CP Monitor. It does not replace PerfKit, OMEGAMON, or a capacity study.

## What you need

| Source | Metrics used here | Required |
| --- | --- | --- |
| This exporter, Feilong | `zvm_exporter_up`, `zvm_system_info`, `zvm_host_memory_usage_bytes`, `zvm_host_memory_limit_bytes`, `zvm_guest_cpu_time_seconds_total`, `zvm_guest_cpu_count_cpus`, `zvm_guest_memory_usage_bytes`, `zvm_guest_memory_limit_bytes`, `zvm_guest_memory_total_bytes`, `zvm_smapi_healthy` | Feilong URL. Guest series need the guests collector. |
| This exporter, vmcp | `zvm_system_cpu_utilization`, `zvm_paging_utilization`, `zvm_spool_utilization`, `zvm_vmcp_up`, `zvm_vmcp_cache_age_seconds`, `zvm_vmcp_command_duration_seconds`, `zvm_vmcp_consecutive_failures` | `vmcp` enabled on a Linux on Z guest with class D and class G. Panels stay empty when it is off. |
| node_exporter on Linux guests | `node_cpu_seconds_total`, `node_load1`, `node_memory_MemAvailable_bytes`, `node_memory_MemTotal_bytes`, `node_uname_info` | Grafana diagnosis and the steal alerts. Not used by the exporter. |
| Dynatrace OneAgent | `builtin:host.cpu.steal`, `builtin:host.cpu.usage` | Dynatrace diagnosis tile and the steal metric event. Confirm the keys in your tenant. |

`zvm_guest_memory_total_bytes` is Feilong `total_memory` converted as kilobytes. That unit is an assumption. Check it on a real system before you trust the overcommit ratio. `zvm_guest_memory_limit_bytes` is the Feilong maximum, not the directory definition, so the used/limit ratio can look smaller than the guest's real footprint.

There is no separate "defined memory" or "real frames" counter. Overcommit is guest-reported total memory divided by LPAR memory.

## Grafana

Import each file in `dashboards/grafana/zvm-*.json`, or copy them to the path in `dashboards/grafana/provisioning.yaml` and point Grafana at that provisioning file.

Pick the Prometheus datasource when asked. Variables:

| Variable | Selects |
| --- | --- |
| `system` | `zvm_host_name` from `zvm_system_info`. All is `.*`. |
| `lpar` | `zvm_lpar_name` on that system only. All is `.*`. |
| `guest` | `zvm_guest_id` on that system, and only when the system's info series matches the LPAR. |
| `linux_instance` | `instance` from `node_uname_info`. Not tied to the LPAR. |

z/VM panels multiply by `zvm_system_info{zvm_host_name=~"$system",zvm_lpar_name=~"$lpar"}` so the LPAR variable drops other hosts. `zvm_exporter_up` and `zvm_smapi_healthy` have no host label, so those two panels stay unfiltered. Linux panels use `linux_instance` only.

Load `dashboards/grafana/alerts.yml` into Prometheus (`rule_files`) or an equivalent ruler. Grafana then shows the alerts from that Prometheus. The `for` values are the hysteresis: a single spike does not fire.

`ZvmExporterProcessDown` assumes the Prometheus job label is `zvm-otel-exporter`. That is the scrape job name, not a label the exporter emits. If your job is named something else, change the `job` matcher. `up == 0` fires for a target Prometheus still remembers. `absent(zvm_exporter_up)` fires when no exporter series exist. `ZvmFeilongDown` is the case where the process is scraped and host collection failed. `ZvmSmapiDown` is narrower still: SMAPI is unhealthy.

JSON dashboard files have no SPDX line because JSON comments are not valid. The YAML files in this directory start with an SPDX header. The generator is `dashboards/build_pack.py`.

### Panels

| Dashboard | Panel | What to do with it |
| --- | --- | --- |
| z/VM fleet | Systems reporting | If the count drops, an exporter stopped. Fix that before reading capacity. |
| z/VM fleet | Fleet CPU | Red for 15 minutes matches the warning alert at 85 percent. |
| z/VM fleet | Exporter up | Traffic light for Feilong host collection. Green at 1. Not filtered by LPAR. |
| z/VM fleet | Identity | LPAR and CPC labels. Join other metrics on `zvm_host_name`. |
| z/VM fleet | Host memory used | LPAR memory pressure from Feilong, not Linux free memory. |
| z/VM fleet | Paging space used | Trend. Warning only above 80 percent. |
| z/VM fleet | Spool space used | Trend. Warning only above 80 percent. |
| z/VM fleet | SMAPI healthy | Guest stats can vanish while host info still works. |
| z/VM and Linux diagnosis | z/VM CPU utilization | Denominator for the steal question. |
| z/VM and Linux diagnosis | Guest CPU time | Cores the guest actually consumed. |
| z/VM and Linux diagnosis | Linux CPU steal | Time the guest waited on the hypervisor. |
| z/VM and Linux diagnosis | Linux load | Busy inside Linux when steal is low. |
| z/VM and Linux diagnosis | Defined guest CPUs | Capacity, not usage. |
| z/VM and Linux diagnosis | Guest memory in use | z/VM view of the guest. |
| z/VM and Linux diagnosis | Linux memory available | Linux view. Compare with steal before blaming the guest. |
| z/VM and Linux diagnosis | Linux memory size | Large and idle means the guest may be oversized. |
| z/VM capacity | Memory overcommit | Yellow at 1.0, red at 1.5. |
| z/VM capacity | CPU headroom | What is left of INDICATE LOAD. High is green. |
| z/VM capacity | Guest memory used ratio | Low ratio and a large limit is a right-sizing candidate. |
| z/VM capacity | Guest CPU used vs defined | Low ratio over an hour is idle CPU definition. |
| z/VM capacity | Paging in 7 days | Linear sketch. Do not treat it as a forecast model. |
| z/VM capacity | Spool in 7 days | Same sketch for spool. |
| z/VM capacity | Days until paging reaches 90 percent | Ignore negative numbers. The slope is flat or down. |

### Alert defaults

| Alert | Severity | For | Fires when |
| --- | --- | --- | --- |
| ZvmExporterProcessDown | critical | 5m | `up{job="zvm-otel-exporter"} == 0` or `absent(zvm_exporter_up)` |
| ZvmFeilongDown | critical | 5m | `zvm_exporter_up == 0` while the process is still scraped |
| ZvmSmapiDown | warning | 15m | `zvm_smapi_healthy == 0` |
| ZvmExporterStale | warning | 10m | stale snapshot |
| ZvmVmcpDown | warning | 15m | `zvm_vmcp_up == 0` |
| ZvmVmcpCacheStale | warning | 10m | cache age above 15 minutes |
| ZvmVmcpFailures | warning | 15m | more than two consecutive vmcp failures |
| ZvmVmcpSlow | warning | 15m | command pass longer than 10 seconds |
| ZvmCpuHigh | warning | 15m | system CPU above 85 percent |
| ZvmCpuCritical | critical | 15m | system CPU above 95 percent |
| ZvmLinuxStealHigh | warning | 15m | steal above 10 percent |
| ZvmLinuxStealCritical | critical | 15m | steal above 25 percent |
| ZvmMemoryOvercommitHigh | warning | 30m | guest total memory over 1.5 times the LPAR |
| ZvmMemoryOvercommitCritical | warning | 30m | guest total memory over 3 times the LPAR |
| ZvmPagingForecast | warning | 1h | 7-day projection of paging above 90 percent |
| ZvmSpoolForecast | warning | 1h | 7-day projection of spool above 90 percent |
| ZvmPagingHigh | warning | 30m | paging above 80 percent |
| ZvmSpoolHigh | warning | 30m | spool above 80 percent |

Paging, spool, and memory overcommit alerts are warning only. They are not availability incidents. The 3x overcommit rule is still named `ZvmMemoryOvercommitCritical`, and its severity is warning.

## Dynatrace

Send OTLP metrics to `https://{env}.live.dynatrace.com/api/v2/otlp/v1/metrics` with an API token that has `metrics.ingest`. The exporter's OTel names are the metric keys (`zvm.system.cpu.utilization`, not the Prometheus underscore form). Resource attributes from process start use the same keys as `zvm.system.info`, including `host.name`, `host.arch`, `deployment.environment.name`, and `zvm.lpar.name`. `host.id` is not set.

The files in `dashboards/dynatrace/zvm-*.json` are Dynatrace Dashboards documents, schema version 21: `version`, `variables`, `tiles`, and `layouts`. That is the JSON Download writes from the Dashboards app. To import one, open Dashboards and select Upload, then choose the file. Each data tile has `type` `data`, a DQL `query`, and `visualization`. Empty `visualizationSettings` and `querySettings` objects are omitted. Variable defaults are `*`, not a tenant id. A markdown tile at the top is the title, because the document content has no separate name field. The upload uses the file as the dashboard. Variables `system`, `lpar`, and `guest` are query variables. `lpar` depends on `system`. z/VM tiles look up `zvm.system.info` so a host remains only when its LPAR is selected. OneAgent tiles are not filtered by LPAR. The guest CPU tile is the cumulative counter. Apply a rate in the tile if you need cores.

`dashboards/dynatrace/metric-events/*.json` follows the Settings schema `builtin:anomaly-detection.metric-events`. Load them with the Settings API or Monaco (`POST /api/v2/settings/objects`). `violatingSamples` is at least 3 out of `samples`. Selectors use the `:avg` fold. The schema has no `severity` field. `eventType` is `AVAILABILITY` or `RESOURCE_CONTENTION`. `zvm-exporter-missing.json` sets `alertOnNoData` to true and a threshold below any real value, so it fires when the metric stops arriving and does not fire when the value is 0. `zvm-feilong-down.json` fires when `zvm.exporter.up` is present and its average is below 1, with `alertOnNoData` false. `zvm-smapi-down.json` is the SMAPI warning. `zvm-overcommit-high.json` is the guest-total over host-limit ratio above 1.5, and it is `RESOURCE_CONTENTION` only. Confirm `builtin:host.cpu.steal` in your metric browser before enabling the steal event. Paging, spool, and overcommit events are warning.

## Comparison

PerfKit and OMEGAMON read CP Monitor and show device-level and user-level detail this pack does not have. Rocket Data Pump already draws Grafana charts from that same monitor stream. This pack does not replace those products.

What it adds, when you already run this exporter:

* One board for several z/VM systems, with the LPAR name on `zvm_system_info` instead of a per-product screen.
* z/VM CPU, guest CPU, and Linux steal in one row, which is the question capacity talks are asking. PerfKit can show steal. It does not sit on the same panel as node_exporter or OneAgent.
* A memory overcommit ratio and a 7-day line for paging and spool, with warning-level alerts. It will not tell you which minidisk or which user is paging.
* Exporter health, including vmcp cache age, so a blank CPU panel is explained.

Use PerfKit or OMEGAMON when you need monitor records. Use this pack when you want the same Prometheus or Dynatrace tenant that already holds Linux metrics to show the hypervisor next to them.
