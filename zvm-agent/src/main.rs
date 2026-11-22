// Copyright 2026 z/VM OTel Exporter contributors
// SPDX-License-Identifier: Apache-2.0

use std::env;
use std::process::ExitCode;
use std::thread;
use std::time::{Duration, Instant};

use zvm_agent::contract::{self, Origin};
use zvm_agent::monitor::MONREADER_ABSENT;
use zvm_agent::otlp;
use zvm_agent::snapshot::{self, Paths};

fn main() -> ExitCode {
    match run(env::args().skip(1).collect()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            eprintln!("zvm-agent: {err}");
            ExitCode::from(1)
        }
    }
}

fn run(args: Vec<String>) -> zvm_agent::error::Result<()> {
    if args
        .iter()
        .any(|arg| arg == "--monreader" || arg == "--help" || arg == "-h")
    {
        if args.iter().any(|arg| arg == "--monreader") {
            return Err(zvm_agent::error::Error::new(MONREADER_ABSENT));
        }
        println!("{}", help());
        return Ok(());
    }
    if args.first().map(String::as_str) == Some("contract") {
        print_contract();
        return Ok(());
    }
    let mut paths = Paths::default();
    let mut once = false;
    let mut print = false;
    let mut endpoint = None;
    let mut interval = None;
    let mut index = 0;
    while index < args.len() {
        let arg = args[index].as_str();
        match arg {
            "--once" => once = true,
            "--print" => print = true,
            "--otlp-endpoint" => endpoint = Some(need(&args, &mut index, arg)?),
            "--interval" => {
                let text = need(&args, &mut index, arg)?;
                let seconds: u64 = text.parse().map_err(|_| {
                    zvm_agent::error::Error::new("--interval must be a whole number of seconds")
                })?;
                if seconds == 0 {
                    return Err(zvm_agent::error::Error::new(
                        "--interval must be at least 1 second",
                    ));
                }
                interval = Some(Duration::from_secs(seconds));
            }
            "--sysinfo" => paths.sysinfo = need(&args, &mut index, arg)?.into(),
            "--proc-root" => paths.proc_root = need(&args, &mut index, arg)?.into(),
            "--hypfs" => paths.hypfs = need(&args, &mut index, arg)?.into(),
            "--monitor-file" => paths.monitor_file = Some(need(&args, &mut index, arg)?.into()),
            "--host-name" => paths.host_name = need(&args, &mut index, arg)?,
            "--system-name" => paths.system_name = need(&args, &mut index, arg)?,
            "--guest-name" => paths.guest_name = need(&args, &mut index, arg)?,
            "--light" => paths.runtimes = false,
            other => {
                return Err(zvm_agent::error::Error::new(format!(
                    "unknown argument {other}. {HELP_HINT}"
                )))
            }
        }
        index += 1;
    }
    if endpoint.is_none() {
        print = true;
    }
    let mut unknown_starts = snapshot::UnknownStarts::default();
    loop {
        let began = Instant::now();
        let mut snapshot = snapshot::collect(&paths)?;
        let now = snapshot::unix_nanos();
        unknown_starts.rebase(&mut snapshot, now);
        let body = otlp::metrics_json(&snapshot, now);
        if print {
            println!("{body}");
        }
        if let Some(endpoint) = &endpoint {
            otlp::post_metrics(endpoint, &body, Duration::from_secs(10))?;
        }
        if once || interval.is_none() {
            return Ok(());
        }
        let pause = interval.unwrap_or(Duration::from_secs(10));
        let spent = began.elapsed();
        if pause > spent {
            thread::sleep(pause - spent);
        }
    }
}

fn need(args: &[String], index: &mut usize, flag: &str) -> zvm_agent::error::Result<String> {
    *index += 1;
    args.get(*index)
        .cloned()
        .ok_or_else(|| zvm_agent::error::Error::new(format!("{flag} needs a value")))
}

fn print_contract() {
    println!("name\torigin\tunit\tnote");
    for series in contract::contract() {
        let origin = match series.origin {
            Origin::GuestFile => "guest-file",
            Origin::MonitorFixture => "monitor-fixture",
            Origin::FeilongExporter => "feilong-exporter",
        };
        println!(
            "{}\t{origin}\t{}\t{}",
            series.name, series.unit, series.note
        );
    }
}

const HELP_HINT: &str = "Run zvm-agent --help.";

fn help() -> &'static str {
    "\
zvm-agent reads this Linux guest and exports OTLP metrics.

  zvm-agent [--once] [--print] [--otlp-endpoint http://host:4318]
            [--interval SECONDS] [--proc-root PATH] [--sysinfo PATH]
            [--hypfs PATH] [--monitor-file PATH]
            [--host-name NAME] [--system-name NAME] [--guest-name USERID]
            [--light]
  zvm-agent contract

--proc-root defaults to /proc. Missing /proc/sysinfo and a missing hypfs
file are skipped. --monitor-file is a fixture of 'USERID MICROSECONDS' lines,
not a CP Monitor stream. --monreader is rejected. --light skips the Java,
Tomcat, WebLogic, and HTTP process scan and keeps the guest file metrics.

zvm.linux.cpu.time is /proc/stat. zvm.linux.hypfs.guest.cpu.time is DIAG 2FC.
zvm.monitor.guest.cpu.time is the fixture. zvm.guest.cpu.time stays in the
Feilong exporter."
}
