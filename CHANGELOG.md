# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `zvm.system.info` labels for the z/VM system, LPAR, and CPC, from `/proc/sysinfo`, data already collected from Feilong, and config overrides. OTLP resource attributes carry the same identity at process start.
- Dashboard pack under `dashboards/` for Grafana and Dynatrace, with alert rules and `docs/dashboards.md`.

## [0.1.0] - 2026-11-18

### Added

- Feilong REST collector for z/VM host, disk-pool, guest, virtual-switch, and SSI metrics.
- Prometheus exposition on port 9110 and OTLP export over gRPC or HTTP.
- Optional `vmcp` collector for paging, spool, and system CPU utilization.
- Fixture Feilong server and recorded `vmcp` output so tests run without a mainframe.
- Project governance files for a future Open Mainframe Project proposal.

[Unreleased]: https://github.com/ca6iya/zvm-otel-exporter/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ca6iya/zvm-otel-exporter/releases/tag/v0.1.0
