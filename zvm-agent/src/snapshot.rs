// Copyright 2026 z/VM OTel Exporter contributors
// SPDX-License-Identifier: Apache-2.0

use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::contract::{
    self, AGENT_UP, HYPFS_GUEST_CPU_TIME, HYPFS_GUEST_MEMORY_LIMIT, HYPFS_GUEST_MEMORY_USAGE,
    LINUX_CPU_TIME, LINUX_DISK_IO, LINUX_MEMORY_LIMIT, LINUX_MEMORY_USAGE, LINUX_NETWORK_IO,
    LINUX_SYSTEM_INFO, MONITOR_GUEST_CPU_TIME,
};
use crate::error::{Error, Result};
use crate::hypfs;
use crate::monitor;
use crate::procfs;
use crate::sysinfo::{self, SYSINFO_CAP};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Counter,
    Gauge,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Point {
    pub name: &'static str,
    pub description: &'static str,
    pub unit: &'static str,
    pub kind: Kind,
    pub attributes: Vec<(String, String)>,
    pub value: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Snapshot {
    pub resource: Vec<(String, String)>,
    pub points: Vec<Point>,
}

#[derive(Clone, Debug)]
pub struct Paths {
    pub sysinfo: PathBuf,
    pub proc_root: PathBuf,
    pub hypfs: PathBuf,
    pub monitor_file: Option<PathBuf>,
    pub host_name: String,
    pub system_name: String,
    pub guest_name: String,
    pub arch: String,
}

impl Default for Paths {
    fn default() -> Self {
        Self {
            sysinfo: PathBuf::from("/proc/sysinfo"),
            proc_root: PathBuf::from("/proc"),
            hypfs: PathBuf::from("/sys/kernel/debug/s390_hypfs/diag_2fc"),
            monitor_file: None,
            host_name: String::new(),
            system_name: String::new(),
            guest_name: String::new(),
            arch: std::env::consts::ARCH.to_string(),
        }
    }
}

pub fn collect(paths: &Paths) -> Result<Snapshot> {
    let stat = read_text(&paths.proc_root.join("stat"), SYSINFO_CAP)?;
    let meminfo = read_text(&paths.proc_root.join("meminfo"), SYSINFO_CAP)?;
    let diskstats = read_text(&paths.proc_root.join("diskstats"), SYSINFO_CAP)?;
    let netdev = read_text(&paths.proc_root.join("net/dev"), SYSINFO_CAP)?;
    let cpus = procfs::parse_stat(&stat)?;
    let memory = procfs::parse_meminfo(&meminfo)?;
    let disks = procfs::parse_diskstats(&diskstats)?;
    let nics = procfs::parse_netdev(&netdev)?;

    let mut identity = if paths.sysinfo.is_file() {
        sysinfo::parse_sysinfo(&read_text(&paths.sysinfo, SYSINFO_CAP)?)
    } else {
        std::collections::BTreeMap::new()
    };
    if !paths.guest_name.is_empty() {
        identity.insert("exporter_guest".to_string(), clip(&paths.guest_name));
    }
    let mut resource = Vec::new();
    push_attr(&mut resource, "host.arch", &paths.arch);
    push_attr(&mut resource, "service.name", "zvm-agent");
    push_attr(&mut resource, "host.name", &paths.host_name);
    push_attr(&mut resource, "zvm.host.name", &paths.host_name);
    push_attr(&mut resource, "zvm.system.name", &paths.system_name);
    for (field, key) in [
        ("lpar_name", "zvm.lpar.name"),
        ("lpar_number", "zvm.lpar.number"),
        ("cpc_type", "zvm.cpc.type"),
        ("cpc_model", "zvm.cpc.model"),
        ("cpc_sequence", "zvm.cpc.sequence"),
        ("cpc_plant", "zvm.cpc.plant"),
        ("hypervisor", "zvm.hypervisor"),
        ("exporter_guest", "zvm.exporter.guest"),
        ("vm_level", "zvm.vm.level"),
    ] {
        if let Some(value) = identity.get(field) {
            push_attr(&mut resource, key, value);
        }
    }
    resource.sort_by(|left, right| left.0.cmp(&right.0));

    let mut points = Vec::new();
    if !resource.is_empty() {
        points.push(Point {
            name: LINUX_SYSTEM_INFO,
            description: "Local guest identity from /proc/sysinfo. Value is always 1.",
            unit: "1",
            kind: Kind::Gauge,
            attributes: resource.clone(),
            value: 1.0,
        });
    }
    points.push(Point {
        name: AGENT_UP,
        description: "1 when zvm-agent built this snapshot.",
        unit: "1",
        kind: Kind::Gauge,
        attributes: Vec::new(),
        value: 1.0,
    });
    for cpu in cpus {
        points.push(Point {
            name: LINUX_CPU_TIME,
            description:
                "CPU time from /proc/stat. cpu.state=steal is Linux steal, not z/VM virtual time.",
            unit: "s",
            kind: Kind::Counter,
            attributes: vec![
                ("cpu".to_string(), cpu.cpu),
                ("cpu.state".to_string(), cpu.state.to_string()),
            ],
            value: cpu.seconds,
        });
    }
    points.push(gauge(
        LINUX_MEMORY_LIMIT,
        "MemTotal from /proc/meminfo.",
        "By",
        memory.limit_bytes,
    ));
    points.push(gauge(
        LINUX_MEMORY_USAGE,
        "MemTotal minus MemAvailable.",
        "By",
        memory.usage_bytes,
    ));
    for disk in disks {
        points.push(counter_dir(
            LINUX_DISK_IO,
            "Bytes read or written from /proc/diskstats.",
            "By",
            "disk.io.direction",
            "read",
            &disk.device,
            "device",
            disk.read_bytes,
        ));
        points.push(counter_dir(
            LINUX_DISK_IO,
            "Bytes read or written from /proc/diskstats.",
            "By",
            "disk.io.direction",
            "write",
            &disk.device,
            "device",
            disk.write_bytes,
        ));
    }
    for nic in nics {
        points.push(counter_dir(
            LINUX_NETWORK_IO,
            "Bytes from /proc/net/dev.",
            "By",
            "network.io.direction",
            "receive",
            &nic.device,
            "network.interface.name",
            nic.receive_bytes,
        ));
        points.push(counter_dir(
            LINUX_NETWORK_IO,
            "Bytes from /proc/net/dev.",
            "By",
            "network.io.direction",
            "transmit",
            &nic.device,
            "network.interface.name",
            nic.transmit_bytes,
        ));
    }

    if paths.hypfs.is_file() {
        let bytes = read_bytes(&paths.hypfs, 2 * 1024 * 1024)?;
        for guest in hypfs::parse_diag_2fc(&bytes)? {
            let attr = vec![("zvm.guest.id".to_string(), guest.id)];
            points.push(Point {
                name: HYPFS_GUEST_CPU_TIME,
                description: "DIAG 2FC used_cpu for one guest, in seconds.",
                unit: "s",
                kind: Kind::Counter,
                attributes: attr.clone(),
                value: guest.cpu_time_seconds,
            });
            points.push(Point {
                name: HYPFS_GUEST_MEMORY_USAGE,
                description: "DIAG 2FC mem_used_kb converted to bytes.",
                unit: "By",
                kind: Kind::Gauge,
                attributes: attr.clone(),
                value: guest.memory_usage_bytes,
            });
            points.push(Point {
                name: HYPFS_GUEST_MEMORY_LIMIT,
                description: "DIAG 2FC mem_max_kb converted to bytes.",
                unit: "By",
                kind: Kind::Gauge,
                attributes: attr,
                value: guest.memory_limit_bytes,
            });
        }
    }

    if let Some(path) = &paths.monitor_file {
        let text = read_text(path, SYSINFO_CAP)?;
        for guest in monitor::parse_fixture(&text)? {
            points.push(Point {
                name: MONITOR_GUEST_CPU_TIME,
                description: "Cumulative virtual CPU seconds from the monitor fixture.",
                unit: "s",
                kind: Kind::Counter,
                attributes: vec![("zvm.guest.id".to_string(), guest.id)],
                value: guest.cpu_time_seconds,
            });
        }
    }

    points.retain(|point| contract::emits(point.name));
    points.sort_by(|left, right| {
        left.name
            .cmp(right.name)
            .then_with(|| left.attributes.cmp(&right.attributes))
    });
    Ok(Snapshot { resource, points })
}

pub fn unix_nanos() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos() as u64)
        .unwrap_or(0)
}

fn gauge(name: &'static str, description: &'static str, unit: &'static str, value: f64) -> Point {
    Point {
        name,
        description,
        unit,
        kind: Kind::Gauge,
        attributes: Vec::new(),
        value,
    }
}

fn counter_dir(
    name: &'static str,
    description: &'static str,
    unit: &'static str,
    direction_key: &str,
    direction: &str,
    device: &str,
    device_key: &str,
    value: f64,
) -> Point {
    let mut attributes = vec![
        (device_key.to_string(), clip(device)),
        (direction_key.to_string(), direction.to_string()),
    ];
    attributes.sort_by(|left, right| left.0.cmp(&right.0));
    Point {
        name,
        description,
        unit,
        kind: Kind::Counter,
        attributes,
        value,
    }
}

fn push_attr(attrs: &mut Vec<(String, String)>, key: &str, value: &str) {
    let value = clip(value);
    if !value.is_empty() {
        attrs.push((key.to_string(), value));
    }
}

fn clip(value: &str) -> String {
    value.trim().chars().take(128).collect()
}

fn read_text(path: &Path, cap: usize) -> Result<String> {
    let bytes = read_bytes(path, cap)?;
    Ok(String::from_utf8_lossy(&bytes).into_owned())
}

fn read_bytes(path: &Path, cap: usize) -> Result<Vec<u8>> {
    let file =
        fs::File::open(path).map_err(|_| Error::new(format!("cannot read {}", path.display())))?;
    let mut reader = std::io::Read::take(file, cap as u64);
    let mut bytes = Vec::new();
    std::io::Read::read_to_end(&mut reader, &mut bytes)
        .map_err(|_| Error::new(format!("cannot read {}", path.display())))?;
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hypfs::HypfsGuest;
    use std::fs;

    #[test]
    fn one_snapshot_keeps_linux_and_monitor_seconds_apart() {
        let root = std::env::temp_dir().join(format!("zvm-agent-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let proc_root = root.join("proc");
        fs::create_dir_all(proc_root.join("net")).unwrap();
        fs::write(proc_root.join("stat"), "cpu0 100 0 0 0 0 0 0 50 0 0\n").unwrap();
        fs::write(
            proc_root.join("meminfo"),
            "MemTotal: 1024 kB\nMemAvailable: 512 kB\n",
        )
        .unwrap();
        fs::write(
            proc_root.join("diskstats"),
            "  94 0 dasda 1 0 2 0 1 0 2 0 0 0 0\n",
        )
        .unwrap();
        fs::write(
            proc_root.join("net/dev"),
            "  eth0: 10 0 0 0 0 0 0 0 4 0 0 0 0 0 0 0\n",
        )
        .unwrap();
        fs::write(
            root.join("sysinfo"),
            "LPAR Name: ZVMLPAR1\nVM00 Name: LINUX1\nVM00 Control Program: z/VM 7.3.0\n",
        )
        .unwrap();
        fs::write(root.join("monitor.txt"), "LINUX1 2000000\n").unwrap();
        let guest = HypfsGuest {
            id: "LINUX1".to_string(),
            cpu_time_seconds: 3.0,
            memory_usage_bytes: 1024.0,
            memory_limit_bytes: 2048.0,
        };
        fs::write(
            root.join("diag_2fc"),
            hypfs::encode_diag_2fc(&[guest]).unwrap(),
        )
        .unwrap();

        let snapshot = collect(&Paths {
            sysinfo: root.join("sysinfo"),
            proc_root,
            hypfs: root.join("diag_2fc"),
            monitor_file: Some(root.join("monitor.txt")),
            host_name: String::new(),
            system_name: String::new(),
            guest_name: String::new(),
            arch: "s390x".to_string(),
        })
        .unwrap();
        let _ = fs::remove_dir_all(&root);

        let linux = point(&snapshot, LINUX_CPU_TIME, "steal");
        assert_eq!(linux.value, 0.5);
        let monitor = snapshot
            .points
            .iter()
            .find(|point| point.name == MONITOR_GUEST_CPU_TIME)
            .unwrap();
        assert_eq!(monitor.value, 2.0);
        let hypfs_cpu = snapshot
            .points
            .iter()
            .find(|point| point.name == HYPFS_GUEST_CPU_TIME)
            .unwrap();
        assert_eq!(hypfs_cpu.value, 3.0);
        assert!(snapshot
            .points
            .iter()
            .all(|point| point.name != "zvm.guest.cpu.time"));
        assert!(snapshot
            .resource
            .iter()
            .any(|(key, value)| key == "zvm.lpar.name" && value == "ZVMLPAR1"));
        assert!(snapshot
            .resource
            .iter()
            .any(|(key, value)| key == "zvm.exporter.guest" && value == "LINUX1"));
        assert!(!snapshot
            .resource
            .iter()
            .any(|(key, _)| key == "zvm.system.name"));
    }

    fn point<'a>(snapshot: &'a Snapshot, name: &str, state: &str) -> &'a Point {
        snapshot
            .points
            .iter()
            .find(|point| {
                point.name == name
                    && point
                        .attributes
                        .iter()
                        .any(|(key, value)| key == "cpu.state" && value == state)
            })
            .unwrap()
    }
}
