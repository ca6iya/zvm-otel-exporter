// Copyright 2026 z/VM OTel Exporter contributors
// SPDX-License-Identifier: Apache-2.0

/// Where a series is produced. The names stay distinct so a board can tell a
/// Linux `/proc` second from a hypervisor second.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Origin {
    /// This process, from files the guest already has.
    GuestFile,
    /// This process, from the monitor fixture. `/dev/monreader` is not opened.
    MonitorFixture,
    /// `zvm-otel-exporter`. This process does not emit the series.
    FeilongExporter,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Series {
    pub name: &'static str,
    pub origin: Origin,
    pub unit: &'static str,
    pub note: &'static str,
}

pub const LINUX_CPU_TIME: &str = "zvm.linux.cpu.time";
pub const LINUX_MEMORY_LIMIT: &str = "zvm.linux.memory.limit";
pub const LINUX_MEMORY_USAGE: &str = "zvm.linux.memory.usage";
pub const LINUX_DISK_IO: &str = "zvm.linux.disk.io";
pub const LINUX_NETWORK_IO: &str = "zvm.linux.network.io";
pub const HYPFS_GUEST_CPU_TIME: &str = "zvm.linux.hypfs.guest.cpu.time";
pub const HYPFS_GUEST_MEMORY_USAGE: &str = "zvm.linux.hypfs.guest.memory.usage";
pub const HYPFS_GUEST_MEMORY_LIMIT: &str = "zvm.linux.hypfs.guest.memory.limit";
pub const LINUX_SYSTEM_INFO: &str = "zvm.linux.system.info";
pub const RUNTIME_UP: &str = "zvm.linux.runtime.up";
pub const RUNTIME_PROCESSES: &str = "zvm.linux.runtime.processes";
pub const RUNTIME_CPU_TIME: &str = "zvm.linux.runtime.cpu.time";
pub const RUNTIME_MEMORY: &str = "zvm.linux.runtime.memory.usage";
pub const RUNTIME_THREADS: &str = "zvm.linux.runtime.threads";
pub const AGENT_UP: &str = "zvm.agent.up";
pub const MONITOR_GUEST_CPU_TIME: &str = "zvm.monitor.guest.cpu.time";

pub fn contract() -> &'static [Series] {
    &[
        Series {
            name: LINUX_CPU_TIME,
            origin: Origin::GuestFile,
            unit: "s",
            note: "Linux /proc/stat, including steal. This is guest OS time, not z/VM virtual CPU time.",
        },
        Series {
            name: LINUX_MEMORY_LIMIT,
            origin: Origin::GuestFile,
            unit: "By",
            note: "MemTotal from /proc/meminfo.",
        },
        Series {
            name: LINUX_MEMORY_USAGE,
            origin: Origin::GuestFile,
            unit: "By",
            note: "MemTotal minus MemAvailable, from /proc/meminfo.",
        },
        Series {
            name: LINUX_DISK_IO,
            origin: Origin::GuestFile,
            unit: "By",
            note: "/proc/diskstats sectors, converted as 512-byte units.",
        },
        Series {
            name: LINUX_NETWORK_IO,
            origin: Origin::GuestFile,
            unit: "By",
            note: "/proc/net/dev byte counters. The loopback device is omitted.",
        },
        Series {
            name: HYPFS_GUEST_CPU_TIME,
            origin: Origin::GuestFile,
            unit: "s",
            note: "DIAG 2FC used_cpu from s390 hypfs diag_2fc, converted from microseconds. Guests this virtual machine is allowed to query.",
        },
        Series {
            name: HYPFS_GUEST_MEMORY_USAGE,
            origin: Origin::GuestFile,
            unit: "By",
            note: "DIAG 2FC mem_used_kb converted to bytes.",
        },
        Series {
            name: HYPFS_GUEST_MEMORY_LIMIT,
            origin: Origin::GuestFile,
            unit: "By",
            note: "DIAG 2FC mem_max_kb converted to bytes.",
        },
        Series {
            name: LINUX_SYSTEM_INFO,
            origin: Origin::GuestFile,
            unit: "1",
            note: "Always 1. Attributes are this guest's /proc/sysinfo identity.",
        },
        Series {
            name: RUNTIME_UP,
            origin: Origin::GuestFile,
            unit: "1",
            note: "1 when this guest has a Java, Tomcat, WebLogic, or HTTP server process. The label runtime is one of those four names.",
        },
        Series {
            name: RUNTIME_PROCESSES,
            origin: Origin::GuestFile,
            unit: "{process}",
            note: "Process count for that runtime. Command lines are not labels.",
        },
        Series {
            name: RUNTIME_CPU_TIME,
            origin: Origin::GuestFile,
            unit: "s",
            note: "Current sum of CPU seconds for running processes of that runtime. A gauge, because it drops when a process exits.",
        },
        Series {
            name: RUNTIME_MEMORY,
            origin: Origin::GuestFile,
            unit: "By",
            note: "Sum of VmRSS. This is not JVM heap.",
        },
        Series {
            name: RUNTIME_THREADS,
            origin: Origin::GuestFile,
            unit: "{thread}",
            note: "Sum of Threads from /proc/pid/status.",
        },
        Series {
            name: AGENT_UP,
            origin: Origin::GuestFile,
            unit: "1",
            note: "1 when this process built a snapshot. No Feilong call.",
        },
        Series {
            name: MONITOR_GUEST_CPU_TIME,
            origin: Origin::MonitorFixture,
            unit: "s",
            note: "Cumulative virtual CPU from the monitor fixture. Not /dev/monreader.",
        },
        Series {
            name: "zvm.guest.cpu.time",
            origin: Origin::FeilongExporter,
            unit: "s",
            note: "Feilong guest CPU time. Left in zvm-otel-exporter until a live comparison.",
        },
        Series {
            name: "zvm.paging.allocated",
            origin: Origin::FeilongExporter,
            unit: "{page}",
            note: "vmcp QUERY ALLOC PAGE in zvm-otel-exporter. Monitor paging is later.",
        },
        Series {
            name: "zvm.system.cpu.utilization",
            origin: Origin::FeilongExporter,
            unit: "1",
            note: "INDICATE LOAD AVGPROC, a ratio, not a counter of seconds.",
        },
    ]
}

pub fn emits(name: &str) -> bool {
    contract()
        .iter()
        .any(|series| series.name == name && series.origin != Origin::FeilongExporter)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn linux_seconds_and_hypervisor_seconds_have_different_names() {
        let names: Vec<_> = contract().iter().map(|series| series.name).collect();
        assert!(names.contains(&LINUX_CPU_TIME));
        assert!(names.contains(&HYPFS_GUEST_CPU_TIME));
        assert!(names.contains(&MONITOR_GUEST_CPU_TIME));
        assert!(names.contains(&"zvm.guest.cpu.time"));
        assert_eq!(
            contract()
                .iter()
                .find(|series| series.name == "zvm.guest.cpu.time")
                .unwrap()
                .origin,
            Origin::FeilongExporter
        );
        assert!(!emits("zvm.guest.cpu.time"));
        assert!(emits(LINUX_CPU_TIME));
    }
}
