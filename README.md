# z/VM OTel exporter

[![CI](https://github.com/ca6iya/zvm-otel-exporter/actions/workflows/ci.yml/badge.svg)](https://github.com/ca6iya/zvm-otel-exporter/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

<!--
OpenSSF Best Practices badge placeholder.
When the project is enrolled at https://www.bestpractices.dev/, replace this
comment with the badge image that site provides. Do not add a passing badge
before enrollment.
-->

Prometheus and OpenTelemetry exporter for [z/VM](https://www.ibm.com/products/zvm) host and guest metrics. It reads the [Feilong](https://github.com/openmainframeproject/feilong) REST API (the maintained z/VM SDK and cloud connector) and publishes one scrape both as a Prometheus `/metrics` endpoint and as OTLP metrics.

This is a successor to [zvm_exporter](https://github.com/zvmexporter/zvm_exporter) (2016–2017). That project scraped xCAT, which is no longer maintained, and exposed CPU, memory, disk, paging, and spool metrics on port **9110**. The [Open Mainframe Project 2020 mentorship](https://mentorship.linuxfoundation.org/programs/open-mainframe-project-2020-mentorship-enhance-zvm-prometheus-exporter) proposed rebuilding it on Feilong. This repository is that rebuild, with OTLP added so the same series can go to an OpenTelemetry Collector or directly to Dynatrace.

It has been tested against a fixture Feilong server. It has not yet been run against a live z/VM system. Treat the unit conversions in the metrics table as a contract to confirm on real hardware.

## System identity

`zvm.system.info` is a gauge that is always 1. The same attribute keys are on that metric and on the OTLP resource. Prometheus label names are those keys with each `.` replaced by `_`. `host.id` is not set. A CPC sequence is shared by every LPAR on the machine, so it stays on `zvm.cpc.sequence` only.

| Attribute on the metric and the resource | Prometheus label | Where the value comes from |
| --- | --- | --- |
| `host.name` | `host_name` | Same value as `zvm.host.name` |
| `host.arch` | `host_arch` | Feilong `architecture`, or an override |
| `deployment.environment.name` | `deployment_environment_name` | Override only |
| `zvm.system.name` | `zvm_system_name` | Feilong `zvm_host`, or an override |
| `zvm.host.name` | `zvm_host_name` | Feilong `hypervisor_hostname`, or an override |
| `zvm.lpar.name` | `zvm_lpar_name` | `/proc/sysinfo` `LPAR Name`, or an override |
| `zvm.lpar.number` | `zvm_lpar_number` | `/proc/sysinfo` `LPAR Number`, or an override |
| `zvm.cpc.type` | `zvm_cpc_type` | `/proc/sysinfo` `Type`, or an override |
| `zvm.cpc.model` | `zvm_cpc_model` | Feilong CEC model when present, otherwise `/proc/sysinfo` `Model` |
| `zvm.cpc.sequence` | `zvm_cpc_sequence` | `/proc/sysinfo` `Sequence Code`, or an override |
| `zvm.cpc.plant` | `zvm_cpc_plant` | `/proc/sysinfo` `Plant`, or an override |
| `zvm.site` | `zvm_site` | Override only |
| `zvm.ssi.name` | `zvm_ssi_name` | Feilong SSI response already collected, or an override |
| `zvm.hypervisor` | `zvm_hypervisor` | `/proc/sysinfo` `VM00 Control Program`, for example `z/VM 7.3.0` |
| `zvm.exporter.guest` | `zvm_exporter_guest` | Userid of the virtual machine running this Linux |
| `zvm.vm.level` | `zvm_vm_level` | `VM00` or `VM01`, the level that supplied the guest userid |

`/proc/sysinfo` is read at startup and then at most every 10 minutes (`identity.interval`, minimum 600 seconds). The read stops at 64 KiB. A non-empty `identity.*` value, or the matching `ZVM_EXPORTER_IDENTITY_*` variable, replaces the discovered value. Empty overrides are ignored.

`VM00` is the hypervisor level closest to the hardware. `VM00 Name` is that level's virtual-machine userid, not the z/VM system name (`QUERY USERID` prints the system name after `AT`). `zvm.hypervisor` is always `VM00 Control Program`. The exporter guest userid is the `Name` at the highest VM level. With only `VM00`, Linux is a first-level guest and that name is the exporter guest. A `VM01` block means Linux is second-level: `zvm.exporter.guest` is `VM01 Name`, `zvm.vm.level` is `VM01`, and `zvm.hypervisor` stays the first-level control program.

vmcp-only mode does not run `QUERY USERID`. Set `identity.system_name` and `identity.host_name` when Feilong is off. If a caller already has a cached `userid AT sysname` line, it can pass that text in. Nothing in the scrape path issues the command.

Resource attributes are taken once, at process start, and do not change afterward. The info metric picks up a later `/proc/sysinfo` read and the Feilong fields from the latest scrape. Empty attributes are omitted from the resource and kept as empty labels on the metric so the Prometheus family stays one shape. `host.type` is not set.

Guest, NIC, and disk series are not stamped with the LPAR label. Join them to `zvm_system_info` on `zvm_host_name`.

## State-change events

`events.enabled` is false by default. When it is true, each scrape is compared with the previous confirmed scrape. The first scrape is a baseline and emits nothing. A change is exported only after it has been seen `events.confirmations` times in a row (default 2), so a single-scrape flap is dropped.

The events are guest logon, guest logoff, guest relocate, SMAPI unhealthy and recovered, Feilong unhealthy and recovered, and an identity-label change. Relocate fires only when a guest stays logged on and an SSI member already present on that guest's stat payload changes. Logon and logoff use the power-state samples the scrape already collected. Nothing here adds a Feilong call or a CP command.

OTLP log records are written only when events and OTLP are both enabled, through the logs SDK that ships with the installed OpenTelemetry packages. Prometheus gains `zvm_events_total{event="..."}`. At most `events.max_per_cycle` records are exported (default 500); the rest are one summary record and a count on `event="zvm.events.suppressed"`.

Memory is the last confirmed view plus at most one pending view, keyed by guest id and by the health flags. That is a few short strings per guest, not a history. See [docs/dashboards.md](docs/dashboards.md) for the Dynatrace log query. Later ideas are listed in [ROADMAP.md](ROADMAP.md).

## Release

The latest release is [0.2.0](https://github.com/ca6iya/zvm-otel-exporter/releases/tag/v0.2.0) (2026-11-18). The package version in `pyproject.toml` and `__version__` is 0.2.0. The change history is [CHANGELOG.md](CHANGELOG.md), in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. How a maintainer cuts a release is in [RELEASE.md](RELEASE.md).

## Usage

Install and run the exporter from the [Quick start](#quick-start) below. Docker, systemd, configuration, and the metrics tables stay in this README.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Project roles and voting are in [GOVERNANCE.md](GOVERNANCE.md). Report security issues privately as described in [SECURITY.md](SECURITY.md).

## Support and discussion

* Bug reports and questions: [GitHub Issues](https://github.com/ca6iya/zvm-otel-exporter/issues).
* Design discussion: [GitHub Discussions](https://github.com/ca6iya/zvm-otel-exporter/discussions).

### Meetings

There are no regular meetings yet. If a meeting series starts, a maintainer will announce the time, the joining instructions, and the agenda link in GitHub Discussions and record them in this section.

## Acknowledgment

Initial contributor: [ca6iya](https://github.com/ca6iya).

## Architecture

```mermaid
flowchart LR
  subgraph zvm [z/VM LPAR]
    Feilong["Feilong REST API"]
  end
  Exporter["zvm-otel-exporter"]
  Prom["Prometheus"]
  Graf["Grafana"]
  Collector["OTel Collector"]
  DT["Dynatrace"]
  Feilong -->|"HTTPS + token"| Exporter
  Exporter -->|"GET /metrics :9110"| Prom
  Prom --> Graf
  Exporter -->|"OTLP gRPC or HTTP"| Collector
  Exporter -->|"OTLP HTTP"| DT
  Collector --> Graf
```

One process scrapes on an interval and keeps the latest snapshot in memory. `/metrics` renders that snapshot. A scrape never starts a new Feilong or CP collection of its own. An optional `vmcp` collector, off by default, adds paging, spool, and system CPU from the local Linux on Z guest.

* The Prometheus registry renders that snapshot when something scrapes `/metrics`. The default listen port is 9110, matching the old exporter.
* When OTLP is enabled, observable instruments read the same snapshot and a periodic reader exports them.
* If Feilong cannot be reached, the process stays up, `/metrics` and `/health` still answer, `zvm.exporter.up` is 0, and the previous z/VM series stay available with `zvm.exporter.scrape.stale` set to 1.

Feilong authentication is the admin-token flow. `POST /token` sends the long-lived token from `/etc/zvmsdk/token.dat` in the `X-Admin-Token` header. Feilong returns a session token in `X-Auth-Token`. The exporter caches that session token and exchanges a new one after a single HTTP 401. Set `auth: none` only when the Feilong server has token checks disabled.

The exporter does not call `GET /guests/{userid}`. That route returns the user directory entry, and Feilong documents that the password is in clear text.

Tokens are accepted from the config file, the environment, or the CLI. They are omitted from `repr` and stripped from log records. HTTP client loggers are pinned to WARNING so they do not echo headers. The process does not honor `HTTP_PROXY` (`trust_env` is off) so a Feilong token is not sent to an ambient proxy.

## Quick start

Requires Python 3.11 or newer. No mainframe is required for the fixture path.

```bash
python -m pip install .
zvm-otel-exporter-mock --port 8080
```

In another shell:

```bash
zvm-otel-exporter \
  --feilong-url http://127.0.0.1:8080 \
  --feilong-admin-token test-admin-token \
  --no-verify-tls \
  --port 9110
curl -s localhost:9110/metrics | head
curl -s localhost:9110/health
```

`test-admin-token` is the mock server's fixture. A real Feilong admin token belongs in the environment, not on the command line of a shared host:

```bash
export ZVM_EXPORTER_FEILONG_URL=https://feilong.example.com:8080
export ZVM_EXPORTER_FEILONG_ADMIN_TOKEN='the-token-from-token.dat'
export ZVM_EXPORTER_FEILONG_CA_FILE=/etc/zvm-exporter/ca.pem
zvm-otel-exporter --config /etc/zvm-exporter/config.yaml
```

`--once` scrapes a single time, writes Prometheus text to stdout, flushes OTLP if it is enabled, and exits 0 when host information was collected.

A ready-to-edit file is in [`examples/config.yaml`](examples/config.yaml). A Prometheus scrape fragment is in [`examples/prometheus-scrape.yaml`](examples/prometheus-scrape.yaml).

### Docker

```bash
docker build -t zvm-otel-exporter .
docker run --rm -p 9110:9110 \
  -e ZVM_EXPORTER_FEILONG_URL=https://feilong.example.com:8080 \
  -e ZVM_EXPORTER_FEILONG_ADMIN_TOKEN \
  -e ZVM_EXPORTER_FEILONG_VERIFY_TLS=true \
  -v /etc/zvm-exporter/config.yaml:/etc/zvm-exporter/config.yaml:ro \
  zvm-otel-exporter
```

The image runs as uid 65534 and expects the config file at `/etc/zvm-exporter/config.yaml`. Prefer passing the admin token with `-e ZVM_EXPORTER_FEILONG_ADMIN_TOKEN` (forwarded from the host environment) or an env file over writing it into the image.

### Fixture demo

[`examples/compose/docker-compose.yaml`](examples/compose/docker-compose.yaml) starts the packaged Feilong fixture, the exporter, Prometheus, and Grafana with the dashboard pack. This is synthetic. It is not a z/VM system. `test-admin-token` is the fixture token. Prometheus `v3.16.0` and Grafana `12.4.15` are pinned.

```bash
docker compose -f examples/compose/docker-compose.yaml up --build
```

* Exporter metrics: <http://127.0.0.1:9110/metrics>
* Prometheus: <http://127.0.0.1:9090>
* Grafana: <http://127.0.0.1:3000> as an anonymous viewer. The image's admin user is unchanged.

The Prometheus job name is `zvm-otel-exporter`, which is what `ZvmExporterProcessDown` matches. Events are enabled. The fixture does not change, so the first scrapes are a baseline and no guest logon or logoff is expected. `vmcp` is off, so paging and spool panels stay empty. Ports listen on `127.0.0.1` only.

### systemd

Create a system user and install the unit from [`examples/systemd/zvm-otel-exporter.service`](examples/systemd/zvm-otel-exporter.service):

```bash
sudo useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin zvm-exporter
sudo install -d -o root -g zvm-exporter -m 0750 /etc/zvm-exporter
sudo install -o root -g zvm-exporter -m 0640 examples/config.yaml /etc/zvm-exporter/config.yaml
sudo install -o root -g zvm-exporter -m 0640 /dev/null /etc/zvm-exporter/environment
# put ZVM_EXPORTER_FEILONG_ADMIN_TOKEN=... into that environment file
sudo install -m 0644 examples/systemd/zvm-otel-exporter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zvm-otel-exporter
```

## Configuration

Precedence is the YAML file, then environment variables, then CLI flags. A later layer replaces a single field. OTLP headers and disk-pool lists are replaced as a whole, not merged key by key.

| Setting | CLI | Environment | Default |
| --- | --- | --- | --- |
| Config file | `--config` | `ZVM_EXPORTER_CONFIG` | none |
| Feilong URL | `--feilong-url` | `ZVM_EXPORTER_FEILONG_URL` | required |
| Admin token | `--feilong-admin-token` | `ZVM_EXPORTER_FEILONG_ADMIN_TOKEN` | required for `auth: token` |
| Session token | `--feilong-auth-token` | `ZVM_EXPORTER_FEILONG_AUTH_TOKEN` | empty |
| Auth mode | `--auth token\|none` | `ZVM_EXPORTER_FEILONG_AUTH` | `token` |
| TLS verify | `--verify-tls` / `--no-verify-tls` | `ZVM_EXPORTER_FEILONG_VERIFY_TLS` | `true` |
| CA bundle | `--ca-file` | `ZVM_EXPORTER_FEILONG_CA_FILE` | system trust |
| Feilong timeout | `--timeout` | `ZVM_EXPORTER_FEILONG_TIMEOUT` | 30 seconds |
| Disk pools | `--disk-pool` (repeatable) | `ZVM_EXPORTER_FEILONG_DISK_POOLS` | Feilong's default pool |
| Listen address | `--listen` | `ZVM_EXPORTER_LISTEN` | `0.0.0.0` |
| Listen port | `--port` | `ZVM_EXPORTER_PORT` | `9110` |
| Scrape interval | `--scrape-interval` | `ZVM_EXPORTER_SCRAPE_INTERVAL` | 60 seconds |
| Prometheus | `--prometheus` / `--no-prometheus` | `ZVM_EXPORTER_PROMETHEUS_ENABLED` | `true` |
| OTLP | `--otlp` / `--no-otlp` | `ZVM_EXPORTER_OTLP_ENABLED` | `false` |
| OTLP endpoint | `--otlp-endpoint` | `ZVM_EXPORTER_OTLP_ENDPOINT` | required when OTLP is on |
| OTLP protocol | `--otlp-protocol grpc\|http` | `ZVM_EXPORTER_OTLP_PROTOCOL` | `grpc` |
| OTLP headers | `--otlp-header Key=Value` | `ZVM_EXPORTER_OTLP_HEADERS` | none |
| OTLP insecure | `--otlp-insecure` | `ZVM_EXPORTER_OTLP_INSECURE` | `false` |
| Log level | `--log-level` | `ZVM_EXPORTER_LOG_LEVEL` | `INFO` |
| Feilong collection | `--feilong` / `--no-feilong` | `ZVM_EXPORTER_FEILONG_ENABLED` | `true` |
| Per-guest call cap | `--per-guest-limit` | `ZVM_EXPORTER_FEILONG_PER_GUEST_LIMIT` | `32` |
| vmcp collector | `--vmcp` / `--no-vmcp` | `ZVM_EXPORTER_VMCP_ENABLED` | `false` |
| vmcp program | `--vmcp-command` | `ZVM_EXPORTER_VMCP_COMMAND` | `vmcp` |
| vmcp interval | `--vmcp-interval` | `ZVM_EXPORTER_VMCP_INTERVAL` | 60 seconds, minimum 30 |
| vmcp timeout | `--vmcp-timeout` | `ZVM_EXPORTER_VMCP_TIMEOUT` | 5 seconds, maximum 10 |
| vmcp host label | `--vmcp-host-name` | `ZVM_EXPORTER_VMCP_HOST_NAME` | Feilong host name, else `local` |

`ZVM_EXPORTER_OTLP_HEADERS` is either a JSON object or comma-separated `Key=Value` pairs. Use JSON when a value contains a comma. Each collector can be toggled with `ZVM_EXPORTER_COLLECTOR_<NAME>`, for example `ZVM_EXPORTER_COLLECTOR_PCIF=true`.

Disk pool names use Feilong's `TYPE:name` form, such as `ECKD:eckdpool1`. With an empty list the exporter calls `GET /host/diskpool` once and lets Feilong use the pool from its own configuration. The `zvm.disk.pool` label is the name you configured, or the pool name embedded in a details response, or `default` when neither is present.

Guest stats and NIC stats are requested in batches (`feilong.batch_size`, default 25). Power state and minidisks are one HTTP call per managed guest, bounded by `feilong.max_guests` (default 500) and `feilong.concurrency` (default 8). Raise the scrape interval before raising those caps on a large system.

## Metrics

OpenTelemetry names are the source of truth. Dots separate the namespace. Prometheus names replace dots with underscores, append a unit suffix (`By` becomes `bytes`, `s` becomes `seconds`, `{cpu}` becomes `cpus`), and add `_total` on counters.

Examples:

| OTel name | Prometheus name |
| --- | --- |
| `zvm.host.cpu.count` | `zvm_host_cpu_count_cpus` |
| `zvm.guest.cpu.time` | `zvm_guest_cpu_time_seconds_total` |
| `zvm.host.memory.usage` | `zvm_host_memory_usage_bytes` |
| `zvm.exporter.up` | `zvm_exporter_up` |

Attribute keys become labels the same way: `zvm.host.name` becomes `zvm_host_name`, `network.io.direction` becomes `network_io_direction`.

Guest CPU time is the useful CPU graph. `rate(zvm_guest_cpu_time_seconds_total[5m])` is approximately the number of cores the guest consumed. Feilong does not return a system-wide busy percentage.

### Host and Feilong

| Metric | Type | Source | Meaning |
| --- | --- | --- | --- |
| `zvm.host.info` | gauge | `GET /host` | Always 1. Labels carry the hypervisor name, z/VM system name, version, CEC model, architecture, IPL time, and the Feilong connector userid. |
| `zvm.host.cpu.count` | gauge | `vcpus` | Logical CPUs (`lpar_cpu_total`). Parity with the old `zvm_system_cpu_count`. |
| `zvm.host.cpu.used` | gauge | `vcpus_used` | Logical CPUs Feilong reports as in use (`lpar_cpu_used`). This is a count, not the old `zvm_system_cpu_in_use` ratio. |
| `zvm.host.memory.limit` | gauge | `memory_mb` | LPAR memory, converted from mebibytes to bytes. Parity with `zvm_system_memory_total`, in bytes. |
| `zvm.host.memory.usage` | gauge | `memory_mb_used` | LPAR memory in use, converted to bytes. Parity with `zvm_system_memory_in_use`. |
| `zvm.host.disk.limit` | gauge | `disk_total` | Sum of Feilong's configured disk pools. Feilong already rounds to whole gigabytes; the exporter multiplies by 1024 cubed. |
| `zvm.host.disk.usage` | gauge | `disk_used` | Same conversion as the limit. |
| `zvm.host.disk.available` | gauge | `disk_available` | Same conversion. Closest pool-level parity with `zvm_disk_space_free`. |
| `zvm.feilong.info` | gauge | `GET /` | Always 1. Labels are the Feilong version and API version. |
| `zvm.smapi.healthy` | gauge | `GET /smapi_health` | 1 when Feilong says SMAPI is healthy. |
| `zvm.smapi.calls` | counter | `totalSuccess`, `totalFail` | Label `zvm.smapi.call.state` is `success` or `fail`. |
| `zvm.smapi.continuous_failures` | gauge | `continuousFail` | Current consecutive SMAPI failure streak. |

`GET /host` includes disk totals only when Feilong itself has `disk_pool` configured. Those numbers are the sum of those pools, not every DASD on the LPAR. Prefer the disk-pool metrics below when you name the pools yourself.

### Disk pools

| Metric | Type | Source | Meaning |
| --- | --- | --- | --- |
| `zvm.disk_pool.limit` | gauge | `GET /host/diskpool` | `disk_total` in bytes, label `zvm.disk.pool`. |
| `zvm.disk_pool.usage` | gauge | same | `disk_used` in bytes. |
| `zvm.disk_pool.available` | gauge | same | `disk_available` in bytes. |
| `zvm.disk_pool.volume.free` | gauge | `details=true` | Per-volume `free_size`. Feilong does not name the unit. On ECKD pools this is cylinders, which is the closest reading of the old per-volume `zvm_disk_space_free`. It is not bytes. |

The details payload in the Feilong docs is a pool-name key whose value is a list of volume records. The parser also accepts a `volumes` list and summary fields beside it. Confirm the shape on a real system; volume series are skipped when `free_size` is absent.

### Guests

| Metric | Type | Source | Meaning |
| --- | --- | --- | --- |
| `zvm.guests` | gauge | `GET /guests`, `GET /host/guests` | Label `zvm.guest.scope` is `managed` (Feilong's database) or `host` (the host list). |
| `zvm.guest.cpu.count` | gauge | `GET /guests/stats` | `guest_cpus`. |
| `zvm.guest.cpu.min` | gauge | `min_cpu_count` | Minimum virtual CPUs Feilong reports. |
| `zvm.guest.cpu.max_limit` | gauge | `max_cpu_limit` | Passed through. The published sample is 10000 for a 2-CPU guest, so do not alert on it as a CPU count. |
| `zvm.guest.cpu.time` | counter | `used_cpu_time_us` | Seconds. Rate is approximate cores used. |
| `zvm.guest.cpu.elapsed_time` | counter | `elapsed_cpu_time_us` | Seconds. |
| `zvm.guest.cpu.samples` | counter | `samples_cpu_in_use`, `samples_cpu_delay` | Label `zvm.cpu.sample.state` is `in_use` or `delay`. Other monitor buckets are not in the API, so this is not a utilization ratio. |
| `zvm.guest.memory.usage` | gauge | `used_mem_kb` | Bytes. |
| `zvm.guest.memory.limit` | gauge | `max_mem_kb` | Bytes. |
| `zvm.guest.memory.min` | gauge | `min_mem_kb` | Bytes. Feilong's prose for this field says "maximum"; the field name is `min`. |
| `zvm.guest.memory.shared` | gauge | `shared_mem_kb` | Bytes. |
| `zvm.guest.memory.total` | gauge | `total_memory` | Bytes, assuming kilobytes. The API does not name the unit. |
| `zvm.guest.memory.available` | gauge | `available_memory` | Bytes, same assumption. |
| `zvm.guest.memory.free` | gauge | `free_memory` | Bytes, same assumption. |
| `zvm.guest.up` | gauge | `GET /guests/{id}/power_state` | 1 when `on`, 0 when `off`. Label `zvm.power.state` repeats the state. | 
| `zvm.guest.location` | gauge | guest stat payload | 1 when the payload already includes `ssi_member`, `member_system_id`, or `host_system`. No series, and no extra call, when the field is absent. |
| `zvm.guest.network.io` | counter | `GET /guests/interfacestats` | Bytes. `network.io.direction` is `receive` or `transmit`. |
| `zvm.guest.network.packets` | counter | `nic_fr_rx`, `nic_fr_tx` | Frames, same direction label. |
| `zvm.guest.network.errors` | counter | `nic_fr_rx_err`, `nic_fr_tx_err` | Frame errors. |
| `zvm.guest.network.dropped` | counter | `nic_fr_rx_dsc`, `nic_fr_tx_dsc` | Discarded frames. |
| `zvm.guest.disk.size` | gauge | `GET /guests/{id}/disks` | Configured minidisk size in `zvm.disk.units` (often cylinders). Off unless `collectors.minidisks` is true. Capacity, not used space. |

NIC series also carry `network.interface.name` (the virtual device) and `zvm.vswitch.name`.

### Virtual switches, SSI, and PCI

| Metric | Type | Source | Meaning |
| --- | --- | --- | --- |
| `zvm.vswitch.up` | gauge | `GET /vswitches/{name}` | 1 when the status text contains "ready". |
| `zvm.vswitch.authorized_users` | gauge | `authorized_users` | Count of authorized userids, not one series per user. |
| `zvm.vswitch.adapters` | gauge | `adapters` | Coupled guest adapters. |
| `zvm.vswitch.uplink_devices` | gauge | `real_devices` | Real OSA devices. |
| `zvm.ssi.member.joined` | gauge | `GET /host/ssi` | 1 when `member_state` is Joined. No series when the response is an empty list, which means the host is not in an SSI cluster. |
| `zvm.pcif.enabled` | gauge | `GET /host/pcif` | 1 when the PCI function state is ENABLED. Off by default. |

### Exporter

| Metric | Type | Meaning |
| --- | --- | --- |
| `zvm.events` | counter | State changes since process start. Label `event` is a fixed set such as `zvm.guest.logon`. No guest id. Emitted only when `events.enabled` is true. |
| `zvm.exporter.info` | gauge | Always 1. Label `service.version`. |
| `zvm.exporter.up` | gauge | 1 when this scrape collected host information. |
| `zvm.exporter.scrape.duration` | gauge | Seconds spent in the scrape. |
| `zvm.exporter.scrape.errors` | counter | Failed Feilong calls since the process started. |
| `zvm.exporter.scrape.stale` | gauge | 1 when host collection failed and older z/VM series are still being served. |
| `zvm.exporter.scrape.last_success` | gauge | Unix time of the last scrape that collected host information. |

### Paging, spool, and system CPU (`vmcp`, off by default)

These series are the parity path for the 2017 paging, spool, and system CPU metrics. They come from three local CP commands, not from Feilong. See Performance impact for the command budget and privilege classes.

| Metric | Type | Source | Meaning |
| --- | --- | --- | --- |
| `zvm.paging.allocated` | gauge | `QUERY ALLOC PAGE` | Pages allocated to paging. Parity with `zvm_page_allocated_total`. |
| `zvm.paging.used` | gauge | `QUERY ALLOC PAGE` | Pages in use. Parity with `zvm_page_used_total`. |
| `zvm.paging.utilization` | gauge | allocated and used | Used divided by allocated, from 0 to 1. |
| `zvm.paging.rate` | gauge | `INDICATE LOAD` | Instantaneous `PAGING-n/SEC`, in pages per second. |
| `zvm.spool.allocated` | gauge | `QUERY ALLOC SPOOL` | Pages allocated to spool. Parity with `zvm_spool_allocated_total`. |
| `zvm.spool.used` | gauge | `QUERY ALLOC SPOOL` | Pages in use. Parity with `zvm_spool_used_total`. |
| `zvm.spool.utilization` | gauge | allocated and used | Used divided by allocated, from 0 to 1. |
| `zvm.system.cpu.utilization` | gauge | `INDICATE LOAD` `AVGPROC` | System CPU utilization from 0 to 1. Parity with `zvm_system_cpu_in_use`. |
| `zvm.system.cpu.count` | gauge | the count after `AVGPROC` | Processors `INDICATE LOAD` reports. This is not Feilong's `zvm.host.cpu.count`. |
| `zvm.vmcp.up` | gauge | local | 1 when the last pass ran all three commands and every response parsed. |
| `zvm.vmcp.cache_age` | gauge | local | Seconds since that pass. Prometheus and OTLP compute it at read time from a monotonic timestamp, so it climbs between refreshes and resets when the next pass runs. A scrape does not run CP. |
| `zvm.vmcp.command_duration` | gauge | local | Seconds spent in the last pass. |
| `zvm.vmcp.consecutive_failures` | gauge | local | Failure streak. The next attempt waits longer as this grows. |

There is one series per metric. Volume rows and per-processor `PROC` lines are not labels.

## Performance impact

A Prometheus scrape, including many concurrent scrapes, reads the last snapshot. It does not call Feilong and it does not run CP. One background loop collects on `scrape_interval` (default 60 seconds).

### Feilong

A normal scrape is a small fixed set of HTTP calls plus batched guest stats: version, SMAPI health, host, one disk-pool call per configured pool, two guest lists, and `GET /guests/stats` plus `GET /guests/interfacestats` in batches of 25. `max_guests` (default 500) caps that batch list.

Power state and minidisks are the heavy calls: one HTTP request per guest. Minidisks are off by default. Power state stays on, but `feilong.per_guest_limit` (default 32) caps how many guests are queried, the set is sorted so it does not flap, and the thread pool never exceeds 16 workers. Set `collectors.power_state: false` when the batched guest stats are enough. A scrape interval below 30 seconds logs a warning because it multiplies this load. Guest CPU and memory still come from the batched stats call either way.

### vmcp

The collector is off by default. Turn it on only on a Linux on Z guest that is allowed to issue the commands below. When it is on, one pass runs exactly these three commands, sequentially, and then caches the result:

1. `QUERY ALLOC PAGE`
2. `QUERY ALLOC SPOOL`
3. `INDICATE LOAD`

The pass runs at most once per `vmcp.interval` (default 60 seconds). Values below 30 seconds are rejected. Each command has its own hard subprocess timeout (default 5 seconds, maximum 10). Each stream is read only up to 64 KiB. A command that writes more than that is killed, reaped, and counted as a failed pass, so a huge reply cannot be buffered in memory. An HCP message with severity E rejects the output even when a SUMMARY line is mixed in. There is no per-guest CP command, no extra thread, no queue, and no CP Monitor or MONWRITE. The command list is fixed; the config cannot pass an arbitrary CP command.

If a command is missing, times out, is rejected, or cannot be parsed, the next pass waits `interval * 2^n`, capped at 15 minutes. A clean pass resets that wait to the normal interval. `zvm.vmcp.cache_age` is computed when the snapshot is read, from a monotonic timestamp of the last pass, so it climbs between refreshes without another command.

Worst case on a healthy system: three short CP queries a minute, each normally well under a second. The timeout budget is 15 seconds and is spent only if `vmcp` hangs. That is the whole z/VM cost of this collector.

s390 hypfs is not used. `INDICATE LOAD` already returns system CPU utilization in one class G command. hypfs reads DIAG 204 through debugfs, which needs another mount and a heavier diagnose, so it is not the lighter source.

### Privilege classes

`vmcp` comes from s390-tools and talks to `/dev/vmcp`. The guest has to be running under z/VM.

| Command | Privilege class | What it is for |
| --- | --- | --- |
| `QUERY ALLOC PAGE` | D (Spooling Operator) | Paging totals. Class D is what the CP reference and DirMaint require. |
| `QUERY ALLOC SPOOL` | D | Spool totals. |
| `INDICATE LOAD` | G (General User) | `AVGPROC` and the paging rate. |

IBM's performance snapshot tells the operator to log on with class E because that procedure also uses other analyst commands. Class E does not by itself authorize `QUERY ALLOC` unless the installation has redefined command classes. Grant class D and class G, and confirm both on the system. An unauthorized command returns an HCP message. The exporter records the failure, serves the last good samples, and does not retry until the backoff expires.

### Output assumptions to verify on a real system

The fixtures are the examples in the z/VM 7.3 performance snapshot, plus an older `INDICATE LOAD` layout. Confirm these on the system you run:

* Volume rows are `volid rdev start end total in-use high percent`, with an optional note such as `DUMP`.
* When every volume row is an unscaled integer, those rows are summed. On the published examples that sum matches "in use" exactly and is tighter than `SUMMARY`, because CP rounds a large `SUMMARY` with `K` = 1024, `M` = 1024 squared, and `G` = 1024 cubed.
* If the volume list is missing, or a row is already scaled, `SUMMARY`'s first two numbers are allocated and used. `USABLE` is ignored. It can exclude drained or dump space.
* `AVGPROC-nnn% cc` is the system utilization and the processor count. `PROC` lines are not exported.
* `PAGING-nnnn/SEC` is an instantaneous rate, not a counter.

## Gaps relative to the 2017 exporter

Feilong's read API does not expose everything xCAT's SMAPI queries did. The exporter does not invent zeros for a source it cannot see. Paging, spool, and the system CPU ratio are restored only by the optional vmcp collector.

| 2017 metric | Status |
| --- | --- |
| `zvm_system_cpu_count` | Replaced by `zvm.host.cpu.count` from Feilong, and by `zvm.system.cpu.count` from `INDICATE LOAD` when vmcp is enabled. |
| `zvm_system_memory_total`, `zvm_system_memory_in_use` | Replaced by `zvm.host.memory.limit` and `zvm.host.memory.usage`, in bytes. |
| `zvm_disk_space_total`, `zvm_disk_space_free`, `zvm_disk_status` | Partial. Pool totals are in bytes after Feilong's whole-gigabyte rounding. Per-volume free space is in directory-manager units, not bytes, and there is no online/offline status bit. |
| `zvm_page_allocated_total`, `zvm_page_used_total` | Feilong still has no paging API. `zvm.paging.allocated` and `zvm.paging.used` restore the totals when the vmcp collector is enabled. |
| `zvm_spool_allocated_total`, `zvm_spool_used_total` | Feilong still has no spool API. `zvm.spool.allocated` and `zvm.spool.used` restore the totals when the vmcp collector is enabled. |
| `zvm_system_cpu_in_use` | Not available from Feilong. `zvm.system.cpu.utilization` is `INDICATE LOAD` `AVGPROC` when vmcp is enabled. `zvm.host.cpu.used` remains a CPU count. |

Other limits found while reading Feilong 1.6:

* There is no batch power-state route. Power state is capped by `feilong.per_guest_limit` (default 32) and can be turned off.
* `GET /host/pcif` returns an error when the host has no PCI functions, instead of an empty list. Leave that collector off unless you know the LPAR has them.
* `GET /guests/stats` is the batched CPU and memory source. `total_memory`, `available_memory`, and `free_memory` have no unit in the specification. This exporter treats the published sample as kilobytes.
* Guest minidisk size is configured capacity. Feilong does not report bytes used inside a minidisk.
* SSI information is a list of `key = value` strings, not a structured object. The parser follows that format.

## OpenTelemetry Collector

[`examples/otel-collector.yaml`](examples/otel-collector.yaml) receives OTLP/gRPC on 4317 and OTLP/HTTP on 4318 and exposes a Prometheus endpoint on 8889.

Three backend templates sit next to that file. Each one is a template. None of them has been run against a live tenant, and none of them contains a token. Copy the endpoint from the product UI.

* [Dynatrace](examples/otel-collector-dynatrace.yaml) uses `otlphttp`. Set `DT_OTLP_ENDPOINT` to the base URL, with no `/v1/metrics` suffix, and `DT_API_TOKEN` to a token with `metrics.ingest`.
* [Grafana Cloud](examples/otel-collector-grafana.yaml) uses `otlphttp`. Set `GRAFANA_OTLP_ENDPOINT` and `GRAFANA_OTLP_AUTHORIZATION` from the stack's OpenTelemetry tile. The host depends on the stack.
* [Splunk Observability Cloud](examples/otel-collector-splunk.yaml) sends metrics with the `signalfx` exporter, which the core collector does not include. Set `SPLUNK_REALM` and `SPLUNK_ACCESS_TOKEN`. It does not send state-change logs. Splunk's gateway uses HEC for logs, and that path is not in the template.

```bash
zvm-otel-exporter \
  --feilong-url https://feilong.example.com:8080 \
  --feilong-admin-token "$ZVM_EXPORTER_FEILONG_ADMIN_TOKEN" \
  --otlp \
  --otlp-protocol grpc \
  --otlp-endpoint http://otel-collector:4317
```

An `http://` gRPC endpoint is exported without TLS. Use an `https://` endpoint for a collector that presents a certificate, and set `ZVM_EXPORTER_OTLP_INSECURE=false`.

For OTLP/HTTP, a base URL such as `http://otel-collector:4318` is sent to `http://otel-collector:4318/v1/metrics`. A URL that already ends in `/v1/metrics` is left alone.

The SDK exports cumulative sums, which matches Prometheus and Dynatrace's cumulative OTLP intake.

## Dynatrace

You can skip the collector and post OTLP/HTTP straight at a Dynatrace environment. Create an API token with the `metrics.ingest` scope and copy the OTLP URL from the Dynatrace UI rather than guessing a region host. The SaaS metrics path is:

`https://{your-environment-id}.live.dynatrace.com/api/v2/otlp/v1/metrics`

```bash
zvm-otel-exporter \
  --config /etc/zvm-exporter/config.yaml \
  --otlp \
  --otlp-protocol http \
  --otlp-endpoint "https://${DT_ENV_ID}.live.dynatrace.com/api/v2/otlp/v1/metrics" \
  --otlp-header "Authorization=Api-Token ${DT_API_TOKEN}"
```

Prefer `ZVM_EXPORTER_OTLP_HEADERS` as JSON so the token is not in the process list:

```bash
export ZVM_EXPORTER_OTLP_HEADERS='{"Authorization":"Api-Token '"${DT_API_TOKEN}"'"}'
```

gRPC to the same environment uses `https://{your-environment-id}.live.dynatrace.com/api/v2/otlp` and the same `Authorization` header. The collector example has this exporter commented out. This path has not been exercised against a live Dynatrace tenant; confirm the active token scope and the endpoint shown in your environment before relying on it.

Dynatrace keeps the dotted metric names. Dimension cardinality follows guests, NICs, and volumes, so leave minidisks and PCI functions off until you want those series.

## Grafana

Import [`examples/grafana/zvm-dashboard.json`](examples/grafana/zvm-dashboard.json) and choose the Prometheus datasource. The dashboard graphs exporter health, host CPU and memory, disk pools, guest CPU rate, guest memory, NIC throughput, guest power, SMAPI health, and SSI membership. It uses the Prometheus names from this exporter's `/metrics` endpoint. A collector that re-exports OTLP through its Prometheus exporter produces the same names when it applies the standard OpenTelemetry translation.

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest
```

The mock server and fixture live in `src/zvm_otel_exporter/mock.py` and `src/zvm_otel_exporter/fixtures/mock_feilong.json`. CI runs Ruff and pytest on Python 3.11 and 3.12. Alert rules are checked with promtool. See [Testing the alert rules](docs/dashboards.md#testing-the-alert-rules) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Suggested next steps

* Run the exporter against a real Feilong and z/VM pair. Compare `GET /host`, `GET /host/diskpool?details=true`, and `GET /guests/stats` with the conversions in this README, especially disk-pool gigabytes, guest `total_memory`, and `max_cpu_limit`.
* Propose the project to the Open Mainframe Project as a repository next to Feilong, with a maintainer from the Feilong or z/VM community.
* Ask Feilong for the gaps that block parity with the 2017 exporter: paging allocation, spool allocation, and a system CPU utilization figure (or the rest of the monitor sample buckets). A batched power-state route would also remove one request per guest.
* Add a recording of a live scrape to the docs once a z/VM system is available.

## License

Apache License 2.0. See [LICENSE](LICENSE).
