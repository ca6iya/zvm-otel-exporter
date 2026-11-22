// Copyright 2026 z/VM OTel Exporter contributors
// SPDX-License-Identifier: Apache-2.0

//! OTLP/HTTP JSON metrics. Cumulative sums and gauges, no trace or log payload.
//! HTTPS is left to a local collector. This client speaks plain HTTP so the
//! process has no TLS stack and no token handling.

use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::Duration;

use crate::error::{Error, Result};
use crate::snapshot::{Kind, Point, Snapshot};

pub fn metrics_json(snapshot: &Snapshot, start_ns: u64, now_ns: u64) -> String {
    let mut metrics = String::new();
    let mut index = 0;
    while index < snapshot.points.len() {
        let name = snapshot.points[index].name;
        let end = snapshot.points[index..]
            .iter()
            .position(|point| point.name != name)
            .map(|offset| index + offset)
            .unwrap_or(snapshot.points.len());
        if !metrics.is_empty() {
            metrics.push(',');
        }
        metrics.push_str(&metric_json(&snapshot.points[index..end], start_ns, now_ns));
        index = end;
    }
    format!(
        "{{\"resourceMetrics\":[{{\"resource\":{{\"attributes\":[{attrs}]}},\"scopeMetrics\":[{{\"scope\":{{\"name\":\"zvm-agent\",\"version\":\"{version}\"}},\"metrics\":[{metrics}]}}]}}]}}",
        attrs = attributes_json(&snapshot.resource),
        version = env!("CARGO_PKG_VERSION"),
        metrics = metrics,
    )
}

pub fn post_metrics(endpoint: &str, body: &str, timeout: Duration) -> Result<()> {
    let url = parse_http(endpoint)?;
    let mut stream = TcpStream::connect((url.host.as_str(), url.port))
        .map_err(|_| Error::new(format!("cannot connect to {}:{}", url.host, url.port)))?;
    stream
        .set_read_timeout(Some(timeout))
        .map_err(|_| Error::new("cannot set read timeout"))?;
    stream
        .set_write_timeout(Some(timeout))
        .map_err(|_| Error::new("cannot set write timeout"))?;
    let request = format!(
        "POST {path} HTTP/1.1\r\nHost: {host}:{port}\r\nContent-Type: application/json\r\nContent-Length: {len}\r\nConnection: close\r\n\r\n{body}",
        path = url.path,
        host = url.host,
        port = url.port,
        len = body.len(),
        body = body,
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|_| Error::new("cannot write OTLP request"))?;
    let mut response = String::new();
    stream
        .take(2048)
        .read_to_string(&mut response)
        .map_err(|_| Error::new("cannot read OTLP response"))?;
    let status = response.split_whitespace().nth(1).unwrap_or("0");
    if !status.starts_with('2') {
        return Err(Error::new(format!("OTLP export returned HTTP {status}")));
    }
    Ok(())
}

struct HttpUrl {
    host: String,
    port: u16,
    path: String,
}

fn parse_http(endpoint: &str) -> Result<HttpUrl> {
    let rest = endpoint
        .strip_prefix("http://")
        .ok_or_else(|| Error::new("OTLP endpoint must be http://host:port"))?;
    if rest.contains('@') {
        return Err(Error::new("OTLP endpoint must not include user info"));
    }
    let (authority, path) = rest.split_once('/').unwrap_or((rest, ""));
    let path = if path.is_empty() {
        "/v1/metrics".to_string()
    } else {
        format!("/{path}")
    };
    let (host, port) = if let Some((host, port)) = authority.rsplit_once(':') {
        let port: u16 = port
            .parse()
            .map_err(|_| Error::new("OTLP port is not a number"))?;
        (host.to_string(), port)
    } else {
        (authority.to_string(), 4318)
    };
    if host.is_empty() || host.contains('/') {
        return Err(Error::new("OTLP endpoint is missing a host"));
    }
    Ok(HttpUrl { host, port, path })
}

fn metric_json(points: &[Point], start_ns: u64, now_ns: u64) -> String {
    let first = &points[0];
    let data_points: Vec<String> = points
        .iter()
        .map(|point| data_point(point, start_ns, now_ns))
        .collect();
    let body = match first.kind {
        Kind::Counter => format!(
            "\"sum\":{{\"aggregationTemporality\":2,\"isMonotonic\":true,\"dataPoints\":[{}]}}",
            data_points.join(",")
        ),
        Kind::Gauge => format!("\"gauge\":{{\"dataPoints\":[{}]}}", data_points.join(",")),
    };
    format!(
        "{{\"name\":\"{}\",\"description\":\"{}\",\"unit\":\"{}\",{}}}",
        escape(first.name),
        escape(first.description),
        escape(first.unit),
        body
    )
}

fn data_point(point: &Point, start_ns: u64, now_ns: u64) -> String {
    let start = if point.kind == Kind::Counter {
        format!(",\"startTimeUnixNano\":\"{start_ns}\"")
    } else {
        String::new()
    };
    format!(
        "{{\"attributes\":[{}],\"timeUnixNano\":\"{now}\",\"asDouble\":{value}{start}}}",
        attributes_json(&point.attributes),
        now = now_ns,
        value = format_double(point.value),
        start = start,
    )
}

fn attributes_json(attributes: &[(String, String)]) -> String {
    attributes
        .iter()
        .map(|(key, value)| {
            format!(
                "{{\"key\":\"{}\",\"value\":{{\"stringValue\":\"{}\"}}}}",
                escape(key),
                escape(value)
            )
        })
        .collect::<Vec<_>>()
        .join(",")
}

fn escape(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            ch if (ch as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", ch as u32)),
            ch => out.push(ch),
        }
    }
    out
}

fn format_double(value: f64) -> String {
    if value.fract() == 0.0 && value.abs() < 1e15 {
        format!("{value:.1}")
    } else {
        format!("{value}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::{LINUX_CPU_TIME, MONITOR_GUEST_CPU_TIME};
    use crate::snapshot::{Kind, Point, Snapshot};
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::thread;

    #[test]
    fn json_names_both_cpu_seconds_and_the_lpar() {
        let snapshot = Snapshot {
            resource: vec![("zvm.lpar.name".to_string(), "ZVMLPAR1".to_string())],
            points: vec![
                Point {
                    name: LINUX_CPU_TIME,
                    description: "proc",
                    unit: "s",
                    kind: Kind::Counter,
                    attributes: vec![("cpu.state".to_string(), "steal".to_string())],
                    value: 0.25,
                },
                Point {
                    name: MONITOR_GUEST_CPU_TIME,
                    description: "fixture",
                    unit: "s",
                    kind: Kind::Counter,
                    attributes: vec![("zvm.guest.id".to_string(), "LINUX1".to_string())],
                    value: 2.0,
                },
            ],
        };
        let json = metrics_json(&snapshot, 10, 20);
        assert!(json.contains("\"name\":\"zvm.linux.cpu.time\""));
        assert!(json.contains("\"name\":\"zvm.monitor.guest.cpu.time\""));
        assert!(json.contains("ZVMLPAR1"));
        assert!(json.contains("\"aggregationTemporality\":2"));
        assert!(!json.contains("zvm.guest.cpu.time"));
    }

    #[test]
    fn post_reaches_a_local_collector() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            let mut buf = [0_u8; 1024];
            let n = socket.read(&mut buf).unwrap();
            let text = String::from_utf8_lossy(&buf[..n]);
            assert!(text.contains("POST /v1/metrics"));
            socket
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                .unwrap();
        });
        post_metrics(
            &format!("http://127.0.0.1:{port}"),
            "{}",
            Duration::from_secs(2),
        )
        .unwrap();
        handle.join().unwrap();
    }
}
