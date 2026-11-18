# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""Map Feilong JSON payloads onto catalog samples.

Conversions documented here are part of the exporter contract:

* Feilong memory_mb values are treated as mebibytes (1024*1024).
* Feilong disk pool gigabytes are whole numbers already rounded by Feilong,
  and are converted with 1024**3.
* Guest used_mem_kb, max_mem_kb, min_mem_kb and shared_mem_kb are kibibytes.
* total_memory, available_memory and free_memory are not given a unit by the
  API. The published sample is the same magnitude as the kibibyte fields, so
  they are converted as kibibytes.
* CPU times are microseconds and are converted to seconds.
"""

from __future__ import annotations

from collections.abc import Mapping

from zvm_otel_exporter.models import Sample

_KIB = 1024.0
_MIB = 1024.0**2
_GIB = 1024.0**3
_US = 1e-6


def number(value: object) -> float | None:
    """Parse a Feilong number. Booleans are rejected so JSON true is not 1."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _add(
    samples: list[Sample],
    name: str,
    raw: object,
    attributes: Mapping[str, str],
    scale: float = 1.0,
    *,
    counter: bool = False,
) -> None:
    parsed = number(raw)
    if parsed is None:
        return
    value = parsed * scale
    if counter and value < 0:
        return
    samples.append(Sample(name, value, dict(attributes)))


def host_samples(output: Mapping[str, object]) -> tuple[str, list[Sample]]:
    cpu_info = output.get("cpu_info")
    if not isinstance(cpu_info, Mapping):
        cpu_info = {}
    host = str(output.get("hypervisor_hostname") or output.get("zvm_host") or "unknown")
    base = {"zvm.host.name": host}
    samples = [
        Sample(
            "zvm.host.info",
            1.0,
            {
                "zvm.host.name": host,
                "zvm.system.name": str(output.get("zvm_host") or ""),
                "hypervisor.type": str(output.get("hypervisor_type") or ""),
                "hypervisor.version": str(output.get("hypervisor_version") or ""),
                "host.arch": str(cpu_info.get("architecture") or ""),
                "zvm.cec.model": str(cpu_info.get("cec_model") or ""),
                "zvm.ipl.time": str(output.get("ipl_time") or ""),
                "zvm.connector.userid": str(output.get("zcc_userid") or ""),
            },
        )
    ]
    _add(samples, "zvm.host.cpu.count", output.get("vcpus"), base)
    _add(samples, "zvm.host.cpu.used", output.get("vcpus_used"), base)
    _add(samples, "zvm.host.memory.limit", output.get("memory_mb"), base, _MIB)
    _add(samples, "zvm.host.memory.usage", output.get("memory_mb_used"), base, _MIB)
    _add(samples, "zvm.host.disk.limit", output.get("disk_total"), base, _GIB)
    _add(samples, "zvm.host.disk.usage", output.get("disk_used"), base, _GIB)
    _add(samples, "zvm.host.disk.available", output.get("disk_available"), base, _GIB)
    return host, samples


def version_samples(output: object) -> list[Sample]:
    if not isinstance(output, Mapping):
        return []
    return [
        Sample(
            "zvm.feilong.info",
            1.0,
            {
                "feilong.version": str(output.get("version") or ""),
                "feilong.api.version": str(output.get("api_version") or ""),
            },
        )
    ]


def smapi_samples(output: object) -> list[Sample]:
    if not isinstance(output, Mapping):
        return []
    samples: list[Sample] = []
    healthy = as_bool(output.get("healthy"))
    if healthy is not None:
        samples.append(Sample("zvm.smapi.healthy", 1.0 if healthy else 0.0, {}))
    success = number(output.get("totalSuccess"))
    if success is not None and success >= 0:
        samples.append(Sample("zvm.smapi.calls", success, {"zvm.smapi.call.state": "success"}))
    failed = number(output.get("totalFail"))
    if failed is not None and failed >= 0:
        samples.append(Sample("zvm.smapi.calls", failed, {"zvm.smapi.call.state": "fail"}))
    _add(samples, "zvm.smapi.continuous_failures", output.get("continuousFail"), {})
    return samples


def _volume_records(value: object) -> list[Mapping[str, object]]:
    if isinstance(value, list) and value and all(isinstance(item, Mapping) for item in value):
        if any("free_size" in item for item in value):
            return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        found: list[Mapping[str, object]] = []
        for inner in value.values():
            found.extend(_volume_records(inner))
        return found
    return []


def split_diskpool(
    output: object,
) -> tuple[dict[str, object], list[Mapping[str, object]], str]:
    """Separate a disk-pool payload into summary fields, volumes, and a pool name."""

    summary: dict[str, object] = {}
    volumes: list[Mapping[str, object]] = []
    embedded = ""
    if not isinstance(output, Mapping):
        return summary, volumes, embedded
    for key, value in output.items():
        if key in {"disk_total", "disk_used", "disk_available"}:
            summary[key] = value
            continue
        records = _volume_records(value)
        if records:
            if not embedded:
                embedded = str(key)
            volumes.extend(records)
    return summary, volumes, embedded


def diskpool_samples(host: str, output: object, pool_label: str | None) -> list[Sample]:
    summary, volumes, embedded = split_diskpool(output)
    label = pool_label or embedded or "default"
    base = {"zvm.host.name": host, "zvm.disk.pool": label}
    samples: list[Sample] = []
    _add(samples, "zvm.disk_pool.limit", summary.get("disk_total"), base, _GIB)
    _add(samples, "zvm.disk_pool.usage", summary.get("disk_used"), base, _GIB)
    _add(samples, "zvm.disk_pool.available", summary.get("disk_available"), base, _GIB)
    for volume in volumes:
        free = number(volume.get("free_size"))
        if free is None:
            continue
        samples.append(
            Sample(
                "zvm.disk_pool.volume.free",
                free,
                {
                    "zvm.host.name": host,
                    "zvm.disk.pool": str(volume.get("dasd_group") or label),
                    "zvm.volume.name": str(volume.get("volume_name") or ""),
                    "zvm.device.type": str(volume.get("device_type") or ""),
                },
            )
        )
    return samples


def parse_id_list(output: object) -> list[str] | None:
    if not isinstance(output, list):
        return None
    return [str(item) for item in output]


def guest_stat_samples(host: str, stats: object) -> list[Sample]:
    if not isinstance(stats, Mapping):
        return []
    samples: list[Sample] = []
    for userid, raw in stats.items():
        if not isinstance(raw, Mapping):
            continue
        base = {"zvm.host.name": host, "zvm.guest.id": str(userid)}
        _add(samples, "zvm.guest.cpu.count", raw.get("guest_cpus"), base)
        _add(samples, "zvm.guest.cpu.min", raw.get("min_cpu_count"), base)
        _add(samples, "zvm.guest.cpu.max_limit", raw.get("max_cpu_limit"), base)
        _add(samples, "zvm.guest.cpu.time", raw.get("used_cpu_time_us"), base, _US, counter=True)
        _add(
            samples,
            "zvm.guest.cpu.elapsed_time",
            raw.get("elapsed_cpu_time_us"),
            base,
            _US,
            counter=True,
        )
        for field, state in (
            ("samples_cpu_in_use", "in_use"),
            ("samples_cpu_delay", "delay"),
        ):
            parsed = number(raw.get(field))
            if parsed is None or parsed < 0:
                continue
            samples.append(
                Sample(
                    "zvm.guest.cpu.samples",
                    parsed,
                    {**base, "zvm.cpu.sample.state": state},
                )
            )
        _add(samples, "zvm.guest.memory.usage", raw.get("used_mem_kb"), base, _KIB)
        _add(samples, "zvm.guest.memory.limit", raw.get("max_mem_kb"), base, _KIB)
        _add(samples, "zvm.guest.memory.min", raw.get("min_mem_kb"), base, _KIB)
        _add(samples, "zvm.guest.memory.shared", raw.get("shared_mem_kb"), base, _KIB)
        _add(samples, "zvm.guest.memory.total", raw.get("total_memory"), base, _KIB)
        _add(samples, "zvm.guest.memory.available", raw.get("available_memory"), base, _KIB)
        _add(samples, "zvm.guest.memory.free", raw.get("free_memory"), base, _KIB)
    return samples


def _direction(
    samples: list[Sample], name: str, raw: object, common: Mapping[str, str], direction: str
) -> None:
    parsed = number(raw)
    if parsed is None or parsed < 0:
        return
    attributes = dict(common)
    attributes["network.io.direction"] = direction
    samples.append(Sample(name, parsed, attributes))


def interface_samples(host: str, payload: object) -> list[Sample]:
    if not isinstance(payload, Mapping):
        return []
    samples: list[Sample] = []
    for userid, nics in payload.items():
        if isinstance(nics, Mapping):
            nic_list: list[object] = [nics]
        elif isinstance(nics, list):
            nic_list = list(nics)
        else:
            continue
        for nic in nic_list:
            if not isinstance(nic, Mapping):
                continue
            common = {
                "zvm.host.name": host,
                "zvm.guest.id": str(userid),
                "network.interface.name": str(nic.get("nic_vdev") or ""),
                "zvm.vswitch.name": str(nic.get("vswitch_name") or ""),
            }
            pairs = (
                ("zvm.guest.network.io", "nic_rx", "nic_tx"),
                ("zvm.guest.network.packets", "nic_fr_rx", "nic_fr_tx"),
                ("zvm.guest.network.errors", "nic_fr_rx_err", "nic_fr_tx_err"),
                ("zvm.guest.network.dropped", "nic_fr_rx_dsc", "nic_fr_tx_dsc"),
            )
            for name, received, transmitted in pairs:
                _direction(samples, name, nic.get(received), common, "receive")
                _direction(samples, name, nic.get(transmitted), common, "transmit")
    return samples


def parse_power(output: object) -> str | None:
    if isinstance(output, str):
        value = output
    elif isinstance(output, Mapping):
        value = str(output.get("power_state") or "")
    else:
        return None
    normalized = value.strip().lower()
    if normalized in {"on", "off"}:
        return normalized
    return None


def power_samples(host: str, states: Mapping[str, str]) -> list[Sample]:
    samples: list[Sample] = []
    for guest, state in states.items():
        normalized = state.strip().lower()
        if normalized not in {"on", "off"}:
            continue
        samples.append(
            Sample(
                "zvm.guest.up",
                1.0 if normalized == "on" else 0.0,
                {
                    "zvm.host.name": host,
                    "zvm.guest.id": guest,
                    "zvm.power.state": normalized,
                },
            )
        )
    return samples


def minidisk_samples(host: str, guest: str, output: object) -> list[Sample]:
    if isinstance(output, Mapping):
        disks = output.get("minidisks", output.get("disks", []))
    elif isinstance(output, list):
        disks = output
    else:
        return []
    if not isinstance(disks, list):
        return []
    samples: list[Sample] = []
    for disk in disks:
        if not isinstance(disk, Mapping):
            continue
        size = number(disk.get("device_size"))
        if size is None:
            continue
        samples.append(
            Sample(
                "zvm.guest.disk.size",
                size,
                {
                    "zvm.host.name": host,
                    "zvm.guest.id": guest,
                    "zvm.device.id": str(disk.get("vdev") or ""),
                    "zvm.volume.name": str(disk.get("volume_label") or ""),
                    "zvm.device.type": str(disk.get("device_type") or ""),
                    "zvm.disk.units": str(disk.get("device_units") or ""),
                    "zvm.disk.access": str(disk.get("access_type") or ""),
                },
            )
        )
    return samples


def vswitch_samples(host: str, detail: object) -> list[Sample]:
    if not isinstance(detail, Mapping):
        return []
    name = str(detail.get("switch_name") or "")
    status = str(detail.get("switch_status") or "")
    base = {"zvm.host.name": host, "zvm.vswitch.name": name}
    samples = [
        Sample(
            "zvm.vswitch.up",
            1.0 if "ready" in status.lower() else 0.0,
            {
                **base,
                "zvm.vswitch.status": status,
                "zvm.vswitch.type": str(detail.get("switch_type") or ""),
                "zvm.vswitch.transport": str(detail.get("transport_type") or ""),
            },
        )
    ]
    users = detail.get("authorized_users")
    if isinstance(users, Mapping):
        samples.append(Sample("zvm.vswitch.authorized_users", float(len(users)), base))
    adapters = detail.get("adapters")
    if isinstance(adapters, Mapping):
        samples.append(Sample("zvm.vswitch.adapters", float(len(adapters)), base))
    devices = detail.get("real_devices")
    if isinstance(devices, Mapping):
        samples.append(Sample("zvm.vswitch.uplink_devices", float(len(devices)), base))
    return samples


def parse_ssi_lines(lines: list[object]) -> list[dict[str, str]]:
    """Parse Feilong's SSI text records into one dict per member.

    GET /host/ssi returns a list of ``key = value`` strings. Header fields
    apply to every member. A blank line separates members.
    """

    header: dict[str, str] = {}
    current: dict[str, str] = {}
    members: list[dict[str, str]] = []
    for line in lines:
        if not isinstance(line, str) or not line.strip():
            if current:
                members.append({**header, **current})
                current = {}
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key.startswith("member_"):
            current[key] = value
        else:
            header[key] = value
    if current:
        members.append({**header, **current})
    return members


def ssi_samples(output: object) -> list[Sample]:
    if not isinstance(output, list) or not output:
        return []
    if isinstance(output[0], Mapping):
        members = [dict(item) for item in output if isinstance(item, Mapping)]
    else:
        members = parse_ssi_lines(output)
    samples: list[Sample] = []
    for member in members:
        state = str(member.get("member_state") or "")
        samples.append(
            Sample(
                "zvm.ssi.member.joined",
                1.0 if state.lower() == "joined" else 0.0,
                {
                    "zvm.ssi.name": str(member.get("ssi_name") or ""),
                    "zvm.ssi.mode": str(member.get("ssi_mode") or ""),
                    "zvm.ssi.member": str(member.get("member_system_id") or ""),
                    "zvm.ssi.slot": str(member.get("member_slot") or ""),
                    "zvm.ssi.member.state": state,
                },
            )
        )
    return samples


def pcif_samples(host: str, output: object) -> list[Sample]:
    if not isinstance(output, list):
        return []
    samples: list[Sample] = []
    for item in output:
        if not isinstance(item, Mapping):
            continue
        state = str(item.get("state") or "")
        samples.append(
            Sample(
                "zvm.pcif.enabled",
                1.0 if state.upper() == "ENABLED" else 0.0,
                {
                    "zvm.host.name": host,
                    "zvm.pcif.id": str(item.get("pcif") or ""),
                    "zvm.pcif.status": str(item.get("status") or ""),
                    "zvm.pcif.state": state,
                    "zvm.pcif.type": str(item.get("type") or ""),
                    "zvm.guest.id": str(item.get("userid") or ""),
                },
            )
        )
    return samples
