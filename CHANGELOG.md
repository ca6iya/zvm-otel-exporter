# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Optional state-change events. Off by default. The first scrape is a baseline. Later changes become OTLP logs and `zvm.events`, with a per-cycle cap and flap suppression. No extra Feilong or CP calls. A carried or incomplete scrape does not confirm a logon or logoff.
- `ROADMAP.md` for later collector and packaging work.
- A Docker Compose demo for the fixture Feilong server, the exporter, Prometheus, and Grafana. The fixture is synthetic. Image tags are pinned.
- Collector templates for Dynatrace, Grafana Cloud, and Splunk Observability Cloud. They are templates. No tokens, and none of them has been run against a live tenant. The Dynatrace template converts cumulative sums to delta, because Dynatrace does not ingest cumulative counters.

### Changed

- CodeRabbit reviews non-draft pull requests to `main`. Generated dashboard JSON is excluded. The merge rule is in `CONTRIBUTING.md`.

## [0.2.0] - 2026-11-18

### Added

- `zvm.system.info` labels for the z/VM system, LPAR, and CPC. LPAR and CPC fields come from `/proc/sysinfo`. System and host names come from Feilong or an override. OTLP resource attributes use the same keys. `host.id` is not set.
- Dashboard pack under `dashboards/` for Grafana and Dynatrace, with alert rules and `docs/dashboards.md`.
- promtool unit tests for every Prometheus alert rule, run in CI with Prometheus 3.16.0.

### Fixed

- Grafana panel colors are per panel. Byte and count panels have no thresholds. Up, healthy, and CPU headroom treat a high value as good. Overcommit turns yellow at 1.0 and red at 1.5.
- Exporter process down is a separate alert from Feilong down and from SMAPI down. The process alert assumes the Prometheus job name `zvm-otel-exporter`.
- The LPAR dashboard variable is limited to the selected system and is applied to z/VM panels.
- `VM00 Name` is recorded as the exporter guest userid, not as the z/VM system name. `VM01` marks a second-level guest.
- Memory overcommit alerts are warning only. Dynatrace metric events drop the unsupported `severity` field and use the `:avg` fold.

## [0.1.0] - 2026-11-18

### Added

- Feilong REST collector for z/VM host, disk-pool, guest, virtual-switch, and SSI metrics.
- Prometheus exposition on port 9110 and OTLP export over gRPC or HTTP.
- Optional `vmcp` collector for paging, spool, and system CPU utilization.
- Fixture Feilong server and recorded `vmcp` output so tests run without a mainframe.
- Project governance files for a future Open Mainframe Project proposal.

[Unreleased]: https://github.com/ca6iya/zvm-otel-exporter/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/ca6iya/zvm-otel-exporter/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ca6iya/zvm-otel-exporter/releases/tag/v0.1.0
