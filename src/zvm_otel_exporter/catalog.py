# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""Metric catalog.

Names follow OpenTelemetry instrument naming: dotted, lowercase, and prefixed
with ``zvm``. Units use UCUM (``By`` bytes, ``s`` seconds) or annotation units
such as ``{cpu}``. Prometheus names are derived from these definitions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDef:
    name: str
    description: str
    type: str
    unit: str
    labels: tuple[str, ...] = ()


def _g(
    name: str,
    description: str,
    unit: str,
    labels: tuple[str, ...] = (),
) -> MetricDef:
    return MetricDef(name, description, "gauge", unit, labels)


def _c(
    name: str,
    description: str,
    unit: str,
    labels: tuple[str, ...] = (),
) -> MetricDef:
    return MetricDef(name, description, "counter", unit, labels)


_HOST = ("zvm.host.name",)
_GUEST = ("zvm.host.name", "zvm.guest.id")
_POOL = ("zvm.host.name", "zvm.disk.pool")
_NIC = (
    "zvm.host.name",
    "zvm.guest.id",
    "network.interface.name",
    "zvm.vswitch.name",
    "network.io.direction",
)

CATALOG: dict[str, MetricDef] = {
    item.name: item
    for item in (
        _g(
            "zvm.host.info",
            "z/VM hypervisor identity reported by Feilong GET /host. Value is always 1.",
            "1",
            (
                "zvm.host.name",
                "zvm.system.name",
                "hypervisor.type",
                "hypervisor.version",
                "host.arch",
                "zvm.cec.model",
                "zvm.ipl.time",
                "zvm.connector.userid",
            ),
        ),
        _g(
            "zvm.host.cpu.count",
            "Logical CPUs on the z/VM LPAR (Feilong vcpus / lpar_cpu_total).",
            "{cpu}",
            _HOST,
        ),
        _g(
            "zvm.host.cpu.used",
            "Logical CPUs Feilong reports as vcpus_used (lpar_cpu_used). "
            "This is a CPU count, not a utilization ratio.",
            "{cpu}",
            _HOST,
        ),
        _g(
            "zvm.host.memory.limit",
            "LPAR memory Feilong reports as memory_mb, converted to bytes.",
            "By",
            _HOST,
        ),
        _g(
            "zvm.host.memory.usage",
            "LPAR memory Feilong reports as memory_mb_used, converted to bytes.",
            "By",
            _HOST,
        ),
        _g(
            "zvm.host.disk.limit",
            "Sum of Feilong-configured disk pools (disk_total), converted from "
            "whole gigabytes to bytes.",
            "By",
            _HOST,
        ),
        _g(
            "zvm.host.disk.usage",
            "Used space in Feilong-configured disk pools (disk_used), converted "
            "from whole gigabytes to bytes.",
            "By",
            _HOST,
        ),
        _g(
            "zvm.host.disk.available",
            "Free space in Feilong-configured disk pools (disk_available), "
            "converted from whole gigabytes to bytes.",
            "By",
            _HOST,
        ),
        _g(
            "zvm.feilong.info",
            "Feilong build reported by GET /. Value is always 1.",
            "1",
            ("feilong.version", "feilong.api.version"),
        ),
        _g(
            "zvm.smapi.healthy",
            "1 when Feilong reports the SMAPI layer healthy, otherwise 0.",
            "1",
        ),
        _c(
            "zvm.smapi.calls",
            "SMAPI calls Feilong has counted since its counters were reset.",
            "{request}",
            ("zvm.smapi.call.state",),
        ),
        _g(
            "zvm.smapi.continuous_failures",
            "Current streak of consecutive SMAPI failures reported by Feilong.",
            "{request}",
        ),
        _g(
            "zvm.disk_pool.limit",
            "Disk pool size (disk_total) converted from whole gigabytes to bytes.",
            "By",
            _POOL,
        ),
        _g(
            "zvm.disk_pool.usage",
            "Disk pool used space (disk_used) converted from whole gigabytes to bytes.",
            "By",
            _POOL,
        ),
        _g(
            "zvm.disk_pool.available",
            "Disk pool free space (disk_available) converted from whole gigabytes to bytes.",
            "By",
            _POOL,
        ),
        _g(
            "zvm.disk_pool.volume.free",
            "Free space of one directory-manager volume. Feilong does not name the "
            "unit; on ECKD pools the value is cylinders.",
            "1",
            ("zvm.host.name", "zvm.disk.pool", "zvm.volume.name", "zvm.device.type"),
        ),
        _g(
            "zvm.guests",
            "Guest count. Scope managed is the Feilong database; scope host is GET /host/guests.",
            "{guest}",
            ("zvm.host.name", "zvm.guest.scope"),
        ),
        _g(
            "zvm.guest.cpu.count",
            "Virtual CPUs defined for the guest (guest_cpus).",
            "{cpu}",
            _GUEST,
        ),
        _g(
            "zvm.guest.cpu.min",
            "Minimum virtual CPUs Feilong reports for the guest (min_cpu_count).",
            "{cpu}",
            _GUEST,
        ),
        _g(
            "zvm.guest.cpu.max_limit",
            "Feilong max_cpu_limit, passed through unchanged. The API text calls this "
            "a maximum CPU count, but live samples are often a large limit or share "
            "value. Use zvm.guest.cpu.count for the defined CPU count.",
            "1",
            _GUEST,
        ),
        _c(
            "zvm.guest.cpu.time",
            "Virtual CPU time consumed by the guest. Feilong reports microseconds; "
            "the exporter converts to seconds. The per-second rate is approximate CPU cores used.",
            "s",
            _GUEST,
        ),
        _c(
            "zvm.guest.cpu.elapsed_time",
            "Elapsed CPU time Feilong reports for the guest, converted from microseconds to seconds.",
            "s",
            _GUEST,
        ),
        _c(
            "zvm.guest.cpu.samples",
            "z/VM monitor CPU samples Feilong reports. State is in_use or delay. "
            "Other sample buckets are not in the API, so these counts are not a utilization ratio.",
            "{sample}",
            ("zvm.host.name", "zvm.guest.id", "zvm.cpu.sample.state"),
        ),
        _g(
            "zvm.guest.memory.usage",
            "Guest memory in use (used_mem_kb), converted to bytes.",
            "By",
            _GUEST,
        ),
        _g(
            "zvm.guest.memory.limit",
            "Maximum memory the guest may use (max_mem_kb), converted to bytes.",
            "By",
            _GUEST,
        ),
        _g(
            "zvm.guest.memory.min",
            "Minimum memory Feilong reports (min_mem_kb), converted to bytes. "
            "Feilong's own text for this field says maximum; the field name is min.",
            "By",
            _GUEST,
        ),
        _g(
            "zvm.guest.memory.shared",
            "Shared guest memory (shared_mem_kb), converted to bytes.",
            "By",
            _GUEST,
        ),
        _g(
            "zvm.guest.memory.total",
            "Guest-reported total memory (total_memory). Feilong does not name the unit; "
            "the published sample matches kilobytes, which this exporter converts to bytes.",
            "By",
            _GUEST,
        ),
        _g(
            "zvm.guest.memory.available",
            "Guest-reported available memory (available_memory), treated as kilobytes "
            "and converted to bytes.",
            "By",
            _GUEST,
        ),
        _g(
            "zvm.guest.memory.free",
            "Guest-reported free memory (free_memory), treated as kilobytes and converted to bytes.",
            "By",
            _GUEST,
        ),
        _g(
            "zvm.guest.up",
            "1 when the guest power state is on, 0 when it is off.",
            "1",
            ("zvm.host.name", "zvm.guest.id", "zvm.power.state"),
        ),
        _c(
            "zvm.guest.network.io",
            "Bytes received or transmitted on a guest NIC (nic_rx / nic_tx).",
            "By",
            _NIC,
        ),
        _c(
            "zvm.guest.network.packets",
            "Frames received or transmitted on a guest NIC (nic_fr_rx / nic_fr_tx).",
            "{packet}",
            _NIC,
        ),
        _c(
            "zvm.guest.network.errors",
            "NIC frames Feilong reports as errors (nic_fr_rx_err / nic_fr_tx_err).",
            "{error}",
            _NIC,
        ),
        _c(
            "zvm.guest.network.dropped",
            "NIC frames Feilong reports as discarded (nic_fr_rx_dsc / nic_fr_tx_dsc).",
            "{packet}",
            _NIC,
        ),
        _g(
            "zvm.guest.disk.size",
            "Configured minidisk size (device_size) in the unit given by zvm.disk.units. "
            "This is capacity, not used space.",
            "1",
            (
                "zvm.host.name",
                "zvm.guest.id",
                "zvm.device.id",
                "zvm.volume.name",
                "zvm.device.type",
                "zvm.disk.units",
                "zvm.disk.access",
            ),
        ),
        _g(
            "zvm.vswitch.up",
            "1 when the vswitch status text contains 'ready', otherwise 0.",
            "1",
            (
                "zvm.host.name",
                "zvm.vswitch.name",
                "zvm.vswitch.status",
                "zvm.vswitch.type",
                "zvm.vswitch.transport",
            ),
        ),
        _g(
            "zvm.vswitch.authorized_users",
            "Number of userids authorized on the vswitch.",
            "{guest}",
            ("zvm.host.name", "zvm.vswitch.name"),
        ),
        _g(
            "zvm.vswitch.adapters",
            "Number of guest adapters coupled to the vswitch.",
            "{adapter}",
            ("zvm.host.name", "zvm.vswitch.name"),
        ),
        _g(
            "zvm.vswitch.uplink_devices",
            "Number of real OSA devices backing the vswitch.",
            "{device}",
            ("zvm.host.name", "zvm.vswitch.name"),
        ),
        _g(
            "zvm.ssi.member.joined",
            "1 when an SSI member state is Joined, otherwise 0. "
            "No series are emitted when the host is not in an SSI cluster.",
            "1",
            (
                "zvm.ssi.name",
                "zvm.ssi.mode",
                "zvm.ssi.member",
                "zvm.ssi.slot",
                "zvm.ssi.member.state",
            ),
        ),
        _g(
            "zvm.pcif.enabled",
            "1 when a PCI function is ENABLED, otherwise 0. "
            "Feilong returns an error when the host has no PCI functions, so this "
            "collector is off unless enabled.",
            "1",
            (
                "zvm.host.name",
                "zvm.pcif.id",
                "zvm.pcif.status",
                "zvm.pcif.state",
                "zvm.pcif.type",
                "zvm.guest.id",
            ),
        ),
        _g(
            "zvm.exporter.info",
            "Exporter build information. Value is always 1.",
            "1",
            ("service.version",),
        ),
        _g(
            "zvm.exporter.up",
            "1 when this scrape collected host information, otherwise 0. "
            "The process keeps serving metrics while Feilong is unreachable.",
            "1",
        ),
        _g(
            "zvm.exporter.scrape.duration",
            "Wall time spent collecting the latest scrape.",
            "s",
        ),
        _c(
            "zvm.exporter.scrape.errors",
            "Feilong API calls that failed since this process started.",
            "{error}",
        ),
        _g(
            "zvm.exporter.scrape.stale",
            "1 when host collection failed and previously collected z/VM series are still being served.",
            "1",
        ),
        _g(
            "zvm.exporter.scrape.last_success",
            "Unix timestamp of the last scrape that collected host information. 0 if none yet.",
            "s",
        ),
        _g(
            "zvm.paging.allocated",
            "Paging pages allocated on the z/VM system (QUERY ALLOC PAGE). "
            "Parity with the 2017 zvm_page_allocated_total series.",
            "{page}",
            _HOST,
        ),
        _g(
            "zvm.paging.used",
            "Paging pages in use (QUERY ALLOC PAGE). "
            "Parity with the 2017 zvm_page_used_total series.",
            "{page}",
            _HOST,
        ),
        _g(
            "zvm.paging.utilization",
            "Paging pages in use divided by paging pages allocated.",
            "1",
            _HOST,
        ),
        _g(
            "zvm.paging.rate",
            "Instantaneous paging rate from INDICATE LOAD (PAGING-n/SEC), in pages per second.",
            "{page}/s",
            _HOST,
        ),
        _g(
            "zvm.spool.allocated",
            "Spool pages allocated on the z/VM system (QUERY ALLOC SPOOL). "
            "Parity with the 2017 zvm_spool_allocated_total series.",
            "{page}",
            _HOST,
        ),
        _g(
            "zvm.spool.used",
            "Spool pages in use (QUERY ALLOC SPOOL). "
            "Parity with the 2017 zvm_spool_used_total series.",
            "{page}",
            _HOST,
        ),
        _g(
            "zvm.spool.utilization",
            "Spool pages in use divided by spool pages allocated.",
            "1",
            _HOST,
        ),
        _g(
            "zvm.system.cpu.utilization",
            "System CPU utilization from INDICATE LOAD AVGPROC, as a ratio from 0 to 1. "
            "Parity with the 2017 zvm_system_cpu_in_use series.",
            "1",
            _HOST,
        ),
        _g(
            "zvm.system.cpu.count",
            "Processor count reported beside AVGPROC on INDICATE LOAD.",
            "{cpu}",
            _HOST,
        ),
        _g(
            "zvm.vmcp.up",
            "1 when the last vmcp pass ran all three CP commands successfully.",
            "1",
            _HOST,
        ),
        _g(
            "zvm.vmcp.cache_age",
            "Seconds since the last vmcp command pass, read from a monotonic timestamp "
            "when Prometheus or OTLP exports the snapshot. Scrapes within the interval do not run CP.",
            "s",
            _HOST,
        ),
        _g(
            "zvm.vmcp.command_duration",
            "Seconds spent in the last vmcp command pass, including timeouts.",
            "s",
            _HOST,
        ),
        _g(
            "zvm.vmcp.consecutive_failures",
            "Consecutive vmcp passes that had a command or parse failure. Resets after a clean pass.",
            "1",
            _HOST,
        ),
    )
}


def prometheus_label(name: str) -> str:
    """Translate an OTel attribute key to a Prometheus label name."""

    return name.replace(".", "_")


_UNIT_SUFFIX = {
    "1": "",
    "By": "bytes",
    "s": "seconds",
    "{cpu}": "cpus",
    "{guest}": "guests",
    "{request}": "requests",
    "{packet}": "packets",
    "{error}": "errors",
    "{sample}": "samples",
    "{adapter}": "adapters",
    "{device}": "devices",
    "{page}": "pages",
    "{page}/s": "pages_per_second",
}


def prometheus_name(defn: MetricDef) -> str:
    """Derive the Prometheus exposition name for a catalog metric.

    Dots become underscores, the UCUM unit is appended, and counters gain the
    ``_total`` suffix. This matches the OpenTelemetry Prometheus translation
    closely enough that a collector re-export and this endpoint use the same names.
    """

    base = defn.name.replace(".", "_")
    suffix = _UNIT_SUFFIX.get(defn.unit, "")
    if suffix and not base.endswith("_" + suffix):
        base = f"{base}_{suffix}"
    if defn.type == "counter" and not base.endswith("_total"):
        base = f"{base}_total"
    return base
