// Copyright 2026 z/VM OTel Exporter contributors
// SPDX-License-Identifier: Apache-2.0

//! Guest OS counters from `/proc`. These describe this Linux, not other guests.

use crate::error::{Error, Result};

/// `/proc/stat` reports ticks of `USER_HZ`, which is 100 on Linux including s390x.
pub const USER_HZ: f64 = 100.0;

pub const CPU_STATES: [&str; 8] = [
    "user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal",
];

#[derive(Debug, PartialEq)]
pub struct CpuTime {
    pub cpu: String,
    pub state: &'static str,
    pub seconds: f64,
}

#[derive(Debug, PartialEq)]
pub struct Memory {
    pub limit_bytes: f64,
    pub usage_bytes: f64,
}

#[derive(Debug, PartialEq)]
pub struct DiskIo {
    pub device: String,
    pub read_bytes: f64,
    pub write_bytes: f64,
}

#[derive(Debug, PartialEq)]
pub struct NetIo {
    pub device: String,
    pub receive_bytes: f64,
    pub transmit_bytes: f64,
}

pub fn parse_stat(text: &str) -> Result<Vec<CpuTime>> {
    let mut out = Vec::new();
    for raw in text.lines() {
        let mut fields = raw.split_whitespace();
        let Some(name) = fields.next() else {
            continue;
        };
        if !(name.starts_with("cpu")
            && name[3..].chars().all(|ch| ch.is_ascii_digit())
            && !name[3..].is_empty())
        {
            continue;
        }
        let ticks: Vec<f64> = fields
            .map(|field| {
                field
                    .parse::<u64>()
                    .map(|value| value as f64)
                    .map_err(|_| Error::new(format!("/proc/stat field is not a counter: {raw}")))
            })
            .collect::<Result<Vec<_>>>()?;
        for (index, state) in CPU_STATES.iter().enumerate() {
            let seconds = ticks.get(index).copied().unwrap_or(0.0) / USER_HZ;
            out.push(CpuTime {
                cpu: name.to_string(),
                state,
                seconds,
            });
        }
    }
    if out.is_empty() {
        return Err(Error::new("/proc/stat has no per-cpu lines"));
    }
    Ok(out)
}

pub fn parse_meminfo(text: &str) -> Result<Memory> {
    let mut total_kb = None;
    let mut available_kb = None;
    for raw in text.lines() {
        let Some((key, rest)) = raw.split_once(':') else {
            continue;
        };
        let kib = rest.split_whitespace().next().unwrap_or("");
        let Ok(value) = kib.parse::<u64>() else {
            continue;
        };
        match key.trim() {
            "MemTotal" => total_kb = Some(value),
            "MemAvailable" => available_kb = Some(value),
            _ => {}
        }
    }
    let total_kb = total_kb.ok_or_else(|| Error::new("/proc/meminfo has no MemTotal"))?;
    let available_kb =
        available_kb.ok_or_else(|| Error::new("/proc/meminfo has no MemAvailable"))?;
    let usage_kb = total_kb.saturating_sub(available_kb);
    Ok(Memory {
        limit_bytes: (total_kb as f64) * 1024.0,
        usage_bytes: (usage_kb as f64) * 1024.0,
    })
}

pub fn parse_diskstats(text: &str) -> Result<Vec<DiskIo>> {
    let mut out = Vec::new();
    for raw in text.lines() {
        let fields: Vec<&str> = raw.split_whitespace().collect();
        if fields.len() < 10 {
            continue;
        }
        let device = fields[2];
        if device.is_empty() {
            continue;
        }
        let read_sectors: u64 = fields[5]
            .parse()
            .map_err(|_| Error::new(format!("diskstats read sectors: {raw}")))?;
        let write_sectors: u64 = fields[9]
            .parse()
            .map_err(|_| Error::new(format!("diskstats write sectors: {raw}")))?;
        out.push(DiskIo {
            device: device.to_string(),
            read_bytes: (read_sectors as f64) * 512.0,
            write_bytes: (write_sectors as f64) * 512.0,
        });
    }
    Ok(out)
}

pub fn parse_netdev(text: &str) -> Result<Vec<NetIo>> {
    let mut out = Vec::new();
    for raw in text.lines() {
        let Some((name, rest)) = raw.split_once(':') else {
            continue;
        };
        let device = name.trim();
        if device.is_empty() || device == "lo" || device.contains(' ') {
            continue;
        }
        let fields: Vec<&str> = rest.split_whitespace().collect();
        if fields.len() < 9 {
            continue;
        }
        let receive: u64 = fields[0]
            .parse()
            .map_err(|_| Error::new(format!("net/dev receive bytes: {raw}")))?;
        let transmit: u64 = fields[8]
            .parse()
            .map_err(|_| Error::new(format!("net/dev transmit bytes: {raw}")))?;
        out.push(NetIo {
            device: device.to_string(),
            receive_bytes: receive as f64,
            transmit_bytes: transmit as f64,
        });
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stat_converts_user_hz_and_keeps_steal() {
        let text = "\
cpu  100 0 0 0 0 0 0 0 0 0
cpu0 200 0 50 1000 0 0 0 25 0 0
";
        let parsed = parse_stat(text).unwrap();
        let user = parsed
            .iter()
            .find(|row| row.cpu == "cpu0" && row.state == "user")
            .unwrap();
        assert_eq!(user.seconds, 2.0);
        let steal = parsed
            .iter()
            .find(|row| row.cpu == "cpu0" && row.state == "steal")
            .unwrap();
        assert_eq!(steal.seconds, 0.25);
        assert!(parsed.iter().all(|row| row.cpu != "cpu"));
    }

    #[test]
    fn memory_usage_is_total_minus_available() {
        let text = "MemTotal: 2048 kB\nMemAvailable: 512 kB\n";
        let memory = parse_meminfo(text).unwrap();
        assert_eq!(memory.limit_bytes, 2_097_152.0);
        assert_eq!(memory.usage_bytes, 1_572_864.0);
    }

    #[test]
    fn disk_sectors_are_512_byte_units() {
        let text = "  94       0 dasda 2 0 8 0 1 0 4 0 0 0 0 0 0 0 0\n";
        let disks = parse_diskstats(text).unwrap();
        assert_eq!(disks[0].device, "dasda");
        assert_eq!(disks[0].read_bytes, 4096.0);
        assert_eq!(disks[0].write_bytes, 2048.0);
    }

    #[test]
    fn live_proc_stat_includes_steal() {
        let Ok(text) = std::fs::read_to_string("/proc/stat") else {
            return;
        };
        let parsed = parse_stat(&text).unwrap();
        assert!(parsed.iter().any(|row| row.state == "steal"));
    }

    #[test]
    fn netdev_skips_loopback() {
        let text = "\
 face |bytes packets
    lo: 9 0 0 0 0 0 0 0 9 0 0 0 0 0 0 0
  eth0: 100 0 0 0 0 0 0 0 40 0 0 0 0 0 0 0
";
        let nics = parse_netdev(text).unwrap();
        assert_eq!(nics.len(), 1);
        assert_eq!(nics[0].device, "eth0");
        assert_eq!(nics[0].receive_bytes, 100.0);
        assert_eq!(nics[0].transmit_bytes, 40.0);
    }
}
