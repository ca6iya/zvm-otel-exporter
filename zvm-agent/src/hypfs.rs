// Copyright 2026 z/VM OTel Exporter contributors
// SPDX-License-Identifier: Apache-2.0

//! s390 hypfs `diag_2fc` file.
//!
//! The kernel writes this file from DIAGNOSE X'2FC' (`arch/s390/hypfs/hypfs_vm.c`
//! in Linux 6.12). The header is 64 bytes, packed, big-endian, because the
//! image is s390x memory. Each record is `struct diag2fc_data`. `used_cpu` is
//! microseconds, the same unit the older hypfs text files published as
//! `cputime`. `guest_name` is EBCDIC (IBM037) in a live file.
//!
//! A record size other than the 112-byte struct is accepted only when it is
//! longer, and only the first 112 bytes are read. A shorter record is rejected
//! rather than guessed.

use crate::error::{Error, Result};

const HEADER_LEN: usize = 64;
const RECORD_LEN: usize = 112;
const NAME_LEN: usize = 8;
const MAX_GUESTS: u64 = 10_000;

#[derive(Debug, PartialEq)]
pub struct HypfsGuest {
    pub id: String,
    pub cpu_time_seconds: f64,
    pub memory_usage_bytes: f64,
    pub memory_limit_bytes: f64,
}

pub fn parse_diag_2fc(bytes: &[u8]) -> Result<Vec<HypfsGuest>> {
    if bytes.len() < HEADER_LEN {
        return Err(Error::new("diag_2fc is shorter than its 64-byte header"));
    }
    let version = u16::from_be_bytes([bytes[8], bytes[9]]);
    if version != 0 {
        return Err(Error::new(format!(
            "diag_2fc header version {version} is not the known version 0"
        )));
    }
    let len = be_u64(bytes, 0);
    let count = be_u64(bytes, 26);
    if count == 0 {
        if len != 0 {
            return Err(Error::new(
                "diag_2fc count is 0 but the buffer length is not",
            ));
        }
        return Ok(Vec::new());
    }
    if count > MAX_GUESTS {
        return Err(Error::new(format!(
            "diag_2fc count {count} exceeds {MAX_GUESTS}"
        )));
    }
    if len % count != 0 {
        return Err(Error::new(
            "diag_2fc buffer length is not a multiple of the guest count",
        ));
    }
    let record_len = usize::try_from(len / count)
        .map_err(|_| Error::new("diag_2fc record is larger than this process can address"))?;
    if record_len < RECORD_LEN {
        return Err(Error::new(format!(
            "diag_2fc record is {record_len} bytes, shorter than the 112-byte struct"
        )));
    }
    let available = bytes.len() - HEADER_LEN;
    if record_len > available {
        return Err(Error::new(
            "diag_2fc record is longer than the bytes after the header",
        ));
    }
    let count_usize = count as usize;
    let Some(needed) = count_usize.checked_mul(record_len) else {
        return Err(Error::new("diag_2fc body length overflows"));
    };
    if needed > available {
        return Err(Error::new("diag_2fc file is shorter than the header says"));
    }
    let mut guests = Vec::with_capacity(count_usize);
    for index in 0..count_usize {
        let start = HEADER_LEN + index * record_len;
        let record = &bytes[start..start + RECORD_LEN];
        let id = guest_name(&record[104..104 + NAME_LEN])?;
        if id.is_empty() {
            continue;
        }
        let used_cpu_us = be_u64(record, 8);
        let mem_max_kb = be_u64(record, 32);
        let mem_used_kb = be_u64(record, 48);
        guests.push(HypfsGuest {
            id,
            cpu_time_seconds: (used_cpu_us as f64) / 1_000_000.0,
            memory_usage_bytes: (mem_used_kb as f64) * 1024.0,
            memory_limit_bytes: (mem_max_kb as f64) * 1024.0,
        });
    }
    Ok(guests)
}

/// Build a version-0 file. Names are encoded as IBM037, matching a live guest.
pub fn encode_diag_2fc(guests: &[HypfsGuest]) -> Result<Vec<u8>> {
    if guests.len() as u64 > MAX_GUESTS {
        return Err(Error::new("too many guests to encode"));
    }
    let count = guests.len() as u64;
    let mut bytes = vec![0_u8; HEADER_LEN + guests.len() * RECORD_LEN];
    bytes[0..8].copy_from_slice(&(count * RECORD_LEN as u64).to_be_bytes());
    bytes[26..34].copy_from_slice(&count.to_be_bytes());
    for (index, guest) in guests.iter().enumerate() {
        let start = HEADER_LEN + index * RECORD_LEN;
        let used_cpu_us = (guest.cpu_time_seconds * 1_000_000.0).round() as u64;
        let mem_used_kb = (guest.memory_usage_bytes / 1024.0).round() as u64;
        let mem_max_kb = (guest.memory_limit_bytes / 1024.0).round() as u64;
        bytes[start + 8..start + 16].copy_from_slice(&used_cpu_us.to_be_bytes());
        bytes[start + 32..start + 40].copy_from_slice(&mem_max_kb.to_be_bytes());
        bytes[start + 48..start + 56].copy_from_slice(&mem_used_kb.to_be_bytes());
        let encoded = encode_name(&guest.id)?;
        bytes[start + 104..start + 112].copy_from_slice(&encoded);
    }
    Ok(bytes)
}

fn be_u64(bytes: &[u8], offset: usize) -> u64 {
    let mut raw = [0_u8; 8];
    raw.copy_from_slice(&bytes[offset..offset + 8]);
    u64::from_be_bytes(raw)
}

fn guest_name(raw: &[u8]) -> Result<String> {
    // Live diag_2fc names are IBM037, including `$`, `#`, and `@` (0x5B, 0x7B, 0x7C).
    // Those specials sit below 0x80, so the encoding cannot be guessed from the high bit.
    let mut name = String::new();
    for byte in raw {
        if *byte == 0 || *byte == 0x40 {
            continue;
        }
        let ch = ibm037(*byte).ok_or_else(|| {
            Error::new(format!("diag_2fc guest name byte {byte:#x} is not IBM037"))
        })?;
        name.push(ch);
    }
    Ok(name)
}

fn encode_name(id: &str) -> Result<[u8; NAME_LEN]> {
    if id.is_empty() || id.len() > NAME_LEN || !id.chars().all(|ch| ch.is_ascii()) {
        return Err(Error::new(format!(
            "guest id {id:?} is not 1 to 8 ASCII characters"
        )));
    }
    let mut out = [0x40_u8; NAME_LEN];
    for (index, ch) in id.chars().enumerate() {
        out[index] =
            to_ibm037(ch).ok_or_else(|| Error::new(format!("cannot encode {ch:?} as IBM037")))?;
    }
    Ok(out)
}

fn ibm037(byte: u8) -> Option<char> {
    Some(match byte {
        0x5b => '$',
        0x7b => '#',
        0x7c => '@',
        0xc1..=0xc9 => (b'A' + (byte - 0xc1)) as char,
        0xd1..=0xd9 => (b'J' + (byte - 0xd1)) as char,
        0xe2..=0xe9 => (b'S' + (byte - 0xe2)) as char,
        0xf0..=0xf9 => (b'0' + (byte - 0xf0)) as char,
        _ => return None,
    })
}

fn to_ibm037(ch: char) -> Option<u8> {
    Some(match ch {
        '$' => 0x5b,
        '#' => 0x7b,
        '@' => 0x7c,
        'A'..='I' => 0xc1 + (ch as u8 - b'A'),
        'J'..='R' => 0xd1 + (ch as u8 - b'J'),
        'S'..='Z' => 0xe2 + (ch as u8 - b'S'),
        '0'..='9' => 0xf0 + (ch as u8 - b'0'),
        _ => return None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_ebcdic_cpu_and_memory() {
        let guests = vec![HypfsGuest {
            id: "LINUX1".to_string(),
            cpu_time_seconds: 1.5,
            memory_usage_bytes: 4096.0,
            memory_limit_bytes: 8192.0,
        }];
        let bytes = encode_diag_2fc(&guests).unwrap();
        assert_eq!(
            &bytes[104 + 64..104 + 64 + 8],
            &[0xD3, 0xC9, 0xD5, 0xE4, 0xE7, 0xF1, 0x40, 0x40]
        );
        let parsed = parse_diag_2fc(&bytes).unwrap();
        assert_eq!(parsed, guests);
    }

    #[test]
    fn hash_userid_round_trips_as_ibm037() {
        let guests = vec![HypfsGuest {
            id: "#".to_string(),
            cpu_time_seconds: 1.0,
            memory_usage_bytes: 1024.0,
            memory_limit_bytes: 2048.0,
        }];
        let bytes = encode_diag_2fc(&guests).unwrap();
        assert_eq!(bytes[64 + 104], 0x7b);
        assert_eq!(parse_diag_2fc(&bytes).unwrap(), guests);
    }

    #[test]
    fn oversized_record_length_is_rejected() {
        let mut bytes = vec![0_u8; HEADER_LEN];
        bytes[0..8].copy_from_slice(&0xffff_ffff_ffff_ffc0_u64.to_be_bytes());
        bytes[26..34].copy_from_slice(&1_u64.to_be_bytes());
        let error = parse_diag_2fc(&bytes).unwrap_err();
        assert!(error.to_string().contains("longer"));
    }

    #[test]
    fn shorter_record_is_rejected() {
        let mut bytes = encode_diag_2fc(&[HypfsGuest {
            id: "LINUX1".to_string(),
            cpu_time_seconds: 1.0,
            memory_usage_bytes: 1024.0,
            memory_limit_bytes: 2048.0,
        }])
        .unwrap();
        // Claim a 64-byte record, which is shorter than the struct.
        bytes[0..8].copy_from_slice(&64_u64.to_be_bytes());
        let error = parse_diag_2fc(&bytes).unwrap_err();
        assert!(error.to_string().contains("shorter"));
    }
}
