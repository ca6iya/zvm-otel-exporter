// Copyright 2026 z/VM OTel Exporter contributors
// SPDX-License-Identifier: Apache-2.0

//! Process totals for Java, Tomcat, WebLogic, and an HTTP server.
//!
//! Classification uses the process name and the command line. The command line
//! is not exported: it can contain passwords and file paths. Heap, sessions,
//! and request rates are not here. Those come from the application, not from
//! `/proc`.

use std::fs;
use std::path::Path;

use crate::procfs::USER_HZ;

const MAX_PIDS: usize = 4096;
const CMDLINE_CAP: usize = 4096;
const PAGE_SIZE: f64 = 4096.0;

const RUNTIMES: [&str; 4] = ["java", "tomcat", "weblogic", "http"];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Runtime {
    Java,
    Tomcat,
    Weblogic,
    Http,
}

impl Runtime {
    fn index(self) -> usize {
        match self {
            Runtime::Java => 0,
            Runtime::Tomcat => 1,
            Runtime::Weblogic => 2,
            Runtime::Http => 3,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct RuntimeTotals {
    pub runtime: &'static str,
    pub processes: u64,
    pub cpu_seconds: f64,
    pub memory_bytes: f64,
    pub threads: u64,
}

#[derive(Clone, Copy, Default)]
struct Acc {
    processes: u64,
    cpu_ticks: u64,
    rss_pages: u64,
    threads: u64,
}

pub fn scan(proc_root: &Path) -> Vec<RuntimeTotals> {
    let mut acc = [Acc::default(); 4];
    let mut pids: Vec<u32> = Vec::new();
    if let Ok(entries) = fs::read_dir(proc_root) {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let Some(name) = name.to_str() else {
                continue;
            };
            let Ok(pid) = name.parse::<u32>() else {
                continue;
            };
            pids.push(pid);
        }
    }
    pids.sort_unstable();
    pids.truncate(MAX_PIDS);
    for pid in pids {
        let dir = proc_root.join(pid.to_string());
        let Some(kind) = classify(&read_comm(&dir), &read_cmdline(&dir)) else {
            continue;
        };
        let Some((cpu_ticks, rss_pages, stat_threads)) = read_stat(&dir) else {
            continue;
        };
        let threads = read_threads(&dir).unwrap_or(stat_threads);
        let slot = &mut acc[kind.index()];
        slot.processes += 1;
        slot.cpu_ticks += cpu_ticks;
        slot.rss_pages += rss_pages;
        slot.threads += threads;
    }
    RUNTIMES
        .iter()
        .enumerate()
        .map(|(index, runtime)| RuntimeTotals {
            runtime,
            processes: acc[index].processes,
            cpu_seconds: (acc[index].cpu_ticks as f64) / USER_HZ,
            memory_bytes: (acc[index].rss_pages as f64) * PAGE_SIZE,
            threads: acc[index].threads,
        })
        .collect()
}

fn classify(comm: &str, cmdline: &str) -> Option<Runtime> {
    let comm = comm.trim();
    let lower = cmdline.to_ascii_lowercase();
    if lower.contains("weblogic.server") {
        return Some(Runtime::Weblogic);
    }
    if lower.contains("org.apache.catalina.startup.bootstrap")
        || lower.contains("catalina.home")
        || lower.contains("catalina.base")
    {
        return Some(Runtime::Tomcat);
    }
    if matches!(comm, "httpd" | "nginx" | "apache2") {
        return Some(Runtime::Http);
    }
    if comm == "java" || lower.contains("/bin/java") || lower.starts_with("java ") {
        return Some(Runtime::Java);
    }
    None
}

fn read_comm(dir: &Path) -> String {
    fs::read_to_string(dir.join("comm"))
        .unwrap_or_default()
        .trim()
        .to_string()
}

fn read_cmdline(dir: &Path) -> String {
    let mut bytes = Vec::new();
    let Ok(file) = fs::File::open(dir.join("cmdline")) else {
        return String::new();
    };
    let mut reader = std::io::Read::take(file, CMDLINE_CAP as u64);
    if std::io::Read::read_to_end(&mut reader, &mut bytes).is_err() {
        return String::new();
    }
    for byte in &mut bytes {
        if *byte == 0 {
            *byte = b' ';
        }
    }
    String::from_utf8_lossy(&bytes).into_owned()
}

fn read_stat(dir: &Path) -> Option<(u64, u64, u64)> {
    let text = fs::read_to_string(dir.join("stat")).ok()?;
    let end = text.rfind(')')?;
    let fields: Vec<&str> = text[end + 1..].split_whitespace().collect();
    let utime: u64 = fields.get(11)?.parse().ok()?;
    let stime: u64 = fields.get(12)?.parse().ok()?;
    let threads: u64 = fields
        .get(17)
        .and_then(|value| value.parse().ok())
        .unwrap_or(0);
    let rss: u64 = fields
        .get(21)
        .and_then(|value| value.parse().ok())
        .unwrap_or(0);
    Some((utime.saturating_add(stime), rss, threads))
}

fn read_threads(dir: &Path) -> Option<u64> {
    let text = fs::read_to_string(dir.join("status")).ok()?;
    for line in text.lines() {
        let rest = line.strip_prefix("Threads:")?;
        return rest.trim().parse().ok();
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_the_four_runtimes_and_drops_the_command_line() {
        let root = std::env::temp_dir().join(format!("zvm-agent-runtime-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        write_proc(
            &root,
            10,
            "java",
            "java -Dpassword=secret org.apache.catalina.startup.Bootstrap",
            200,
            4,
        );
        write_proc(
            &root,
            11,
            "java",
            "java -Dweblogic.password=secret weblogic.Server",
            100,
            8,
        );
        write_proc(&root, 12, "java", "java -jar /opt/app.jar", 50, 2);
        write_proc(&root, 13, "nginx", "nginx: master process", 10, 1);
        write_proc(&root, 14, "bash", "bash", 1, 1);
        let totals = scan(&root);
        let _ = fs::remove_dir_all(&root);
        let tomcat = totals.iter().find(|row| row.runtime == "tomcat").unwrap();
        assert_eq!(tomcat.processes, 1);
        assert_eq!(tomcat.cpu_seconds, 2.0);
        assert_eq!(tomcat.memory_bytes, 4.0 * PAGE_SIZE);
        assert_eq!(tomcat.threads, 3);
        assert_eq!(
            totals
                .iter()
                .find(|row| row.runtime == "weblogic")
                .unwrap()
                .processes,
            1
        );
        assert_eq!(
            totals
                .iter()
                .find(|row| row.runtime == "java")
                .unwrap()
                .processes,
            1
        );
        assert_eq!(
            totals
                .iter()
                .find(|row| row.runtime == "http")
                .unwrap()
                .processes,
            1
        );
        let rendered = format!("{totals:?}");
        assert!(!rendered.contains("secret"));
    }

    fn write_proc(root: &Path, pid: u32, comm: &str, cmdline: &str, cpu_ticks: u64, rss: u64) {
        let dir = root.join(pid.to_string());
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("comm"), format!("{comm}\n")).unwrap();
        let mut raw = cmdline.replace(' ', "\0");
        raw.push('\0');
        fs::write(dir.join("cmdline"), raw).unwrap();
        // utime is field 14, num_threads field 20, rss field 24.
        let stat =
            format!("{pid} ({comm}) S 1 1 1 0 -1 0 0 0 0 0 {cpu_ticks} 0 0 0 20 0 3 0 0 0 {rss}\n");
        fs::write(dir.join("stat"), stat).unwrap();
        fs::write(dir.join("status"), "Threads:\t3\n").unwrap();
    }
}
