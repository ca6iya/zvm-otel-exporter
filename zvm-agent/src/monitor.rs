// Copyright 2026 z/VM OTel Exporter contributors
// SPDX-License-Identifier: Apache-2.0

//! Fixture stand-in for CP Monitor user-domain CPU time.
//!
//! One guest per line: `USERID MICROSECONDS`. `#` comments are ignored.
//! The number is a cumulative counter, the same shape a later monreader
//! decoder would hand the aggregator. This parser does not read monitor
//! records, and nothing in this crate opens `/dev/monreader`.

use crate::error::{Error, Result};

#[derive(Debug, PartialEq)]
pub struct MonitorGuest {
    pub id: String,
    pub cpu_time_seconds: f64,
}

pub fn parse_fixture(text: &str) -> Result<Vec<MonitorGuest>> {
    let mut guests = Vec::new();
    for (line_no, raw) in text.lines().enumerate() {
        let line = raw.split('#').next().unwrap_or("").trim();
        if line.is_empty() {
            continue;
        }
        let mut parts = line.split_whitespace();
        let id = parts.next().unwrap_or("");
        let micros = parts.next().unwrap_or("");
        if parts.next().is_some() || !valid_userid(id) {
            return Err(Error::new(format!(
                "monitor fixture line {} must be USERID MICROSECONDS",
                line_no + 1
            )));
        }
        let micros: u64 = micros.parse().map_err(|_| {
            Error::new(format!(
                "monitor fixture line {} microseconds are not an integer",
                line_no + 1
            ))
        })?;
        guests.push(MonitorGuest {
            id: id.to_string(),
            cpu_time_seconds: (micros as f64) / 1_000_000.0,
        });
    }
    Ok(guests)
}

fn valid_userid(id: &str) -> bool {
    (1..=8).contains(&id.len())
        && id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'$' | b'#' | b'@'))
}

pub const MONREADER_ABSENT: &str = "\
/dev/monreader is not read by this process. CP Monitor stays off until a test \
LPAR provides records. Use --monitor-file with a fixture of cumulative microseconds.";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn microseconds_become_seconds() {
        let parsed = parse_fixture("# sample\nLINUX1 1500000\n\nLINUX2 500000\n").unwrap();
        assert_eq!(parsed[0].id, "LINUX1");
        assert_eq!(parsed[0].cpu_time_seconds, 1.5);
        assert_eq!(parsed[1].cpu_time_seconds, 0.5);
    }

    #[test]
    fn extra_fields_are_rejected() {
        assert!(parse_fixture("LINUX1 10 extra\n").is_err());
    }
}
