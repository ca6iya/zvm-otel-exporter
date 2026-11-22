# zvm-agent

In-process reader for one Linux guest. It aggregates `/proc`, `/proc/sysinfo`, and (on z/VM) the s390 hypfs `diag_2fc` file, then exports OTLP. An optional text fixture stands in for CP Monitor user CPU until a test LPAR can supply real monitor records.

This crate does not call Feilong or SMAPI, and it does not open `/dev/monreader`. `zvm-otel-exporter` remains the Feilong forwarder.

CPU seconds from different sources keep different names:

| Metric | Source | What a second means |
| --- | --- | --- |
| `zvm.linux.cpu.time` | `/proc/stat` | Time this Linux charged, including `cpu.state=steal` |
| `zvm.linux.hypfs.guest.cpu.time` | hypfs `diag_2fc` `used_cpu` | Hypervisor CPU time for a guest this virtual machine may query |
| `zvm.monitor.guest.cpu.time` | `--monitor-file` fixture | Cumulative microseconds from the fixture, not from CP Monitor |
| `zvm.guest.cpu.time` | Feilong, other process | Not emitted here |

`zvm-agent contract` prints that split.

## Run

Fixture data, no hypervisor:

```bash
cargo run --manifest-path zvm-agent/Cargo.toml -- --once --print \
  --proc-root zvm-agent/fixtures/proc \
  --sysinfo zvm-agent/fixtures/sysinfo.txt \
  --monitor-file zvm-agent/fixtures/monitor.txt
```

This guest's own `/proc`, and OTLP to a collector that speaks HTTP:

```bash
cargo run --manifest-path zvm-agent/Cargo.toml -- --interval 10 \
  --otlp-endpoint http://127.0.0.1:4318
```

`--otlp-endpoint` is `http://` only. Put TLS and tokens on the collector in front of Grafana or Dynatrace. With no endpoint, the process prints one OTLP JSON document and exits.

`--sysinfo` defaults to `/proc/sysinfo`. A missing file is skipped. `VM00` is the hypervisor closest to this Linux. `VM00 Name` becomes `zvm.exporter.guest` and `VM00 Control Program` becomes `zvm.hypervisor`. A higher VM level is an outer hypervisor, not this guest. The userid is not copied into `zvm.system.name`. Pass `--system-name` and `--host-name` when those are known. `--guest-name` overrides the userid from sysinfo.

CPU counters from `/proc/stat` keep their absolute values. Their OTLP start time is `btime`, which is when those counters reset. Disk, network, hypfs, and monitor counters can reset without a reboot, so the first sample in the process is an offset and later samples export the increase. A raw value below the previous sample starts a new interval at 0. A one-shot print of those series is therefore 0. The absolute microseconds stay in the fixture file.

`--monitor-file` must be a regular file. A read that would pass its cap returns an error instead of a short parse.

`--hypfs` defaults to `/sys/kernel/debug/s390_hypfs/diag_2fc`. The file is the kernel image of DIAGNOSE X'2FC': a 64-byte big-endian header, then `struct diag2fc_data` records (112 bytes in Linux 6.12). `used_cpu` is treated as microseconds. `guest_name` is IBM037. A record shorter than 112 bytes is rejected. A missing file is skipped.

The monitor fixture is one `USERID MICROSECONDS` pair per line. `#` starts a comment. `--monreader` exits with an error.

## Tests

```bash
cargo test --manifest-path zvm-agent/Cargo.toml
```

The suite includes a live read of `/proc/stat` when that file exists. It does not claim a z/VM result. `diag_2fc` is tested with a constructed big-endian fixture.
