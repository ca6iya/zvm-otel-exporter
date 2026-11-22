# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

# Roadmap

These items are proposals. Each one is to be validated on a test system before it is treated as a supported feature. Effort describes which components would change, not a calendar estimate. Privilege notes are the CP or directory authority a design would need. They are not instructions for obtaining that authority.

The current release line is 0.2.x. State-change events are on main and are the 0.3.0 change. They are not in the 0.2.0 release.

| Item | Status | Tracking |
| --- | --- | --- |
| CP system records via `vmlogrdr` | proposed | [#6](https://github.com/ca6iya/zvm-otel-exporter/issues/6) |
| Operator console messages | proposed, design first | [#7](https://github.com/ca6iya/zvm-otel-exporter/issues/7) |
| State-change events | merged on main, fixture only | [#5](https://github.com/ca6iya/zvm-otel-exporter/pull/5) |
| `QUERY OVERCOMMIT` on z/VM 7.5 | proposed | [#8](https://github.com/ca6iya/zvm-otel-exporter/issues/8) |
| CP Monitor via `monreader` | proposed, separate component | [#9](https://github.com/ca6iya/zvm-otel-exporter/issues/9) |
| Right-sizing report | proposed | [#10](https://github.com/ca6iya/zvm-otel-exporter/issues/10) |
| PyPI, RPM, and Ansible packaging | proposed | [#11](https://github.com/ca6iya/zvm-otel-exporter/issues/11) |
| OpenTelemetry Collector reference configs | templates, not live | [#12](https://github.com/ca6iya/zvm-otel-exporter/issues/12) |
| Docker Compose demo | demo, fixture only | [#13](https://github.com/ca6iya/zvm-otel-exporter/issues/13) |

The issues use the `enhancement` label. A `roadmap` label could not be created with the token available to this change (the labels API returned 403). A maintainer can add that label later.

## 1. CP system records via the Linux vmlogrdr driver

Status: proposed. To be validated on a test system.

Rationale: `*LOGREC`, `*ACCOUNT`, and `*SYMPTOM` are already written by CP. The Linux `vmlogrdr` driver can present them to a guest that is authorized for IUCV. As OpenTelemetry logs they would sit next to the state-change events, not in the metric scrape.

Effort: a new optional reader process or thread, a parser per record type, and log export. It is not a change to the Feilong scrape. `*ACCOUNT` is the record that would make per-guest chargeback possible.

Risks: IUCV authorization is easy to get wrong, the record formats need a real sample, and a busy reader can add guest CPU that the metric exporter was built to avoid. The reader must stay off unless configured, with a bounded buffer.

Privileges: the guest directory needs IUCV statements that allow the virtual machine to connect to `*LOGREC`, `*ACCOUNT`, and `*SYMPTOM`. That authorization is a directory change, not a class on the exporter's existing `vmcp` commands.

## 2. Operator console messages

Status: proposed. Design discussion first. To be validated on a test system.

Rationale: PROP routing or a secondary console user can forward operator messages. Parsing the HCP message id into a severity, with an allowlist, would explain incidents that metrics only hint at.

Effort: a design note, then a filtered reader and a severity map. No metric cardinality change if the result is logs.

Risks: console text can contain userids, commands, and other operational detail. That is why this stays a design discussion until the filter list and the retention story are agreed. A missed filter is a data leak, not just a noisy dashboard.

Privileges: whatever the chosen route needs. PROP is an operator facility. A secondary user is a directory and operations choice. Neither is assumed to be available to the guest that runs this exporter today.

## 3. State-change events

Status: merged on main in [#5](https://github.com/ca6iya/zvm-otel-exporter/pull/5). Not in the 0.2.0 release. The unit tests and the fixture exercise it. A test z/VM system has not, so it is not a supported feature yet.

Rationale: logon, logoff, SSI relocate, SMAPI or Feilong health, and identity changes can be derived by comparing two scrapes the exporter already stored.

Effort: a diff of the previous view, an optional OTLP log export, and one Prometheus counter with a fixed label set.

Risks: a flap on power state, and a cap so one scrape cannot emit an unbounded number of log records. The first scrape is a baseline. Guest ids are not Prometheus labels.

Privileges: none beyond the Feilong and `vmcp` access the process already has. Relocate is emitted only when a member or host field is already present on a collected guest payload.

## 4. QUERY OVERCOMMIT on z/VM 7.5

Status: proposed. To be validated on a test system.

Rationale: z/VM 7.5 can report memory overcommit with `QUERY OVERCOMMIT`. The dashboard pack currently estimates overcommit from Feilong guest totals divided by LPAR memory, and that estimate needs confirmation.

Effort: one more optional `vmcp` command, cached on the same interval as the existing pass, off by default.

Risks: the command is privilege class B. Adding it to the default pass would fail on guests that only have class D and class G. It stays out of the default command list.

Privileges: class B for `QUERY OVERCOMMIT`. Class D and class G, which the current paging and load commands use, are not sufficient for this command.

## 5. CP Monitor via the Linux monreader driver

Status: proposed as a separate optional component. To be validated on a test system.

Rationale: monitor records are what PerfKit and Data Pump already use. A `monreader` reader would let this project offer the same class of data to Prometheus, Grafana, and OpenTelemetry. It complements those products. It does not replace them.

Effort: a separate package or entry point. The scrape exporter stays as it is. Monitor records are a stream, not a poll of three CP commands.

Risks: this is the heavy option. Domain selection, sample rate, and guest CPU have to be bounded before it can be enabled anywhere. Shipping it inside the default process would break the performance limits in the README.

Privileges: the guest must be allowed to connect to `*MONITOR` through IUCV, and CP monitor domains must be enabled for the data the reader asks for. Those are directory and operator choices.

## 6. Right-sizing report

Status: proposed. To be validated on a test system.

Rationale: capacity conversations ask which guests are defined far above the CPU and memory they use. A 30-day report of defined versus used, per guest, is that list.

Effort: a query or a small recorder over `zvm_guest_cpu_count_cpus`, `zvm_guest_cpu_time_seconds_total`, and the guest memory gauges. It can live in the dashboard pack or in a notebook. It does not need a new collector if the existing series are retained for 30 days.

Risks: retention and guest cardinality belong to the metrics backend. The exporter must not keep 30 days of per-guest samples in process memory.

Privileges: none beyond the collectors that already produce those series.

## 7. Packaging

Status: proposed. To be validated on a test system.

Rationale: a PyPI release, an RPM, and an Ansible role are how an operator installs the exporter without cloning the repository.

Effort: a publish workflow, a spec file, and a role that templates the config and the systemd unit. The systemd unit in `examples/systemd/` is the starting point.

Risks: publishing to PyPI is a maintainer action with a project name that must stay available. An RPM has to target the enterprise Linux versions used on the guests. Secrets must stay out of the role's defaults.

Privileges: none on z/VM. The publisher needs the package-repository credentials.

## 8. OpenTelemetry Collector reference configs

Status: templates next to [`examples/otel-collector.yaml`](examples/otel-collector.yaml). They have not been run against a live Dynatrace, Grafana, or Splunk tenant.

Rationale: most sites will send OTLP to a collector and then to Dynatrace, Grafana, or Splunk. A commented config for each backend makes that path copyable.

Effort: three small YAML examples next to `examples/otel-collector.yaml`, plus a note in the README. No exporter code.

Risks: vendor endpoints and token headers change. The examples must say they are templates and must not contain real tokens.

Privileges: none.

## 9. Docker Compose demo

Status: demo in [`examples/compose/docker-compose.yaml`](examples/compose/docker-compose.yaml). The fixture is synthetic. It has not been run on a test z/VM system, and it is not a supported install method.

Rationale: a compose file that starts the fixture Feilong server, the exporter, Prometheus, and Grafana with the dashboard pack lets someone see the boards without a mainframe.

Effort: a compose file, a Prometheus scrape config, and Grafana provisioning that mounts `dashboards/grafana/`. The fixture server already exists.

Risks: the fixture is not a z/VM system. The README must keep saying the demo is synthetic. Image tags should be pinned.

Privileges: none.
