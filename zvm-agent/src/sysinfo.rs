// Copyright 2026 z/VM OTel Exporter contributors
// SPDX-License-Identifier: Apache-2.0

//! `/proc/sysinfo` on Linux on Z.
//!
//! `VM00 Name` is a virtual-machine userid, not the z/VM system name. The
//! control program closest to the hardware is the hypervisor string. The
//! userid is the `Name` at the highest VM level.

use std::collections::BTreeMap;

const MAX_LABEL: usize = 128;
pub const SYSINFO_CAP: usize = 64 * 1024;

pub fn parse_sysinfo(text: &str) -> BTreeMap<String, String> {
    let mut found = BTreeMap::new();
    let mut levels: BTreeMap<u32, (Option<String>, Option<String>)> = BTreeMap::new();
    for raw in text.lines() {
        let Some((key, value)) = raw.split_once(':') else {
            continue;
        };
        let key = key.trim();
        let value = value.trim();
        if value.is_empty() || value.chars().all(|ch| ch == ':') {
            continue;
        }
        match key {
            "LPAR Name" => {
                found.insert("lpar_name".to_string(), clip(value));
            }
            "LPAR Number" => insert_token(&mut found, "lpar_number", value),
            "Type" => insert_token(&mut found, "cpc_type", value),
            "Sequence Code" => insert_token(&mut found, "cpc_sequence", value),
            "Plant" => insert_token(&mut found, "cpc_plant", value),
            "Model" => insert_token(&mut found, "cpc_model", value),
            _ => {
                if let Some(level) = vm_level(key, "Name") {
                    let name = first_token(value).map(clip);
                    levels.entry(level).or_insert((None, None)).0 = name;
                } else if let Some(level) = vm_level(key, "Control Program") {
                    levels.entry(level).or_insert((None, None)).1 = Some(clip(value));
                }
            }
        }
    }
    if let Some((_, (_, cp))) = levels.iter().next() {
        if let Some(cp) = cp {
            found.insert("hypervisor".to_string(), cp.clone());
        }
    }
    if let Some((level, (name, _))) = levels.iter().next_back() {
        if let Some(name) = name {
            found.insert("exporter_guest".to_string(), name.clone());
            found.insert("vm_level".to_string(), format!("VM{level:02}"));
        }
    }
    found
}

fn vm_level(key: &str, suffix: &str) -> Option<u32> {
    let rest = key.strip_prefix("VM")?;
    let (digits, tail) = rest.split_once(' ')?;
    if tail != suffix || digits.len() != 2 || !digits.chars().all(|ch| ch.is_ascii_digit()) {
        return None;
    }
    digits.parse().ok()
}

fn insert_token(found: &mut BTreeMap<String, String>, key: &str, value: &str) {
    if let Some(token) = first_token(value) {
        found.insert(key.to_string(), clip(token));
    }
}

fn first_token(value: &str) -> Option<&str> {
    value.split_whitespace().next()
}

fn clip(value: &str) -> String {
    let collapsed = value.split_whitespace().collect::<Vec<_>>().join(" ");
    collapsed.chars().take(MAX_LABEL).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = "\
Manufacturer:         IBM
Type:                 3906
Model:                702              N96
Sequence Code:        00000000000C4B8E
Plant:                02
LPAR Number:          15
LPAR Name:            ZVMLPAR1
VM00 Name:            LINUX1
VM00 Control Program: z/VM    7.3.0
";

    #[test]
    fn matches_the_exporter_sysinfo_fixture() {
        let parsed = parse_sysinfo(SAMPLE);
        assert_eq!(parsed["lpar_name"], "ZVMLPAR1");
        assert_eq!(parsed["lpar_number"], "15");
        assert_eq!(parsed["cpc_type"], "3906");
        assert_eq!(parsed["cpc_model"], "702");
        assert_eq!(parsed["cpc_sequence"], "00000000000C4B8E");
        assert_eq!(parsed["cpc_plant"], "02");
        assert_eq!(parsed["hypervisor"], "z/VM 7.3.0");
        assert_eq!(parsed["exporter_guest"], "LINUX1");
        assert_eq!(parsed["vm_level"], "VM00");
        assert!(!parsed.contains_key("system_name"));
        assert!(!parsed.contains_key("host_name"));
    }

    #[test]
    fn inner_guest_wins_and_outer_control_program_stays() {
        let parsed = parse_sysinfo(
            "LPAR Name:            LPAR1\n\
             VM00 Name:            OUTER\n\
             VM00 Control Program: z/VM    7.3.0\n\
             VM01 Name:            LINUX99\n\
             VM01 Control Program: z/VM    7.2.0\n",
        );
        assert_eq!(parsed["hypervisor"], "z/VM 7.3.0");
        assert_eq!(parsed["exporter_guest"], "LINUX99");
        assert_eq!(parsed["vm_level"], "VM01");
    }

    #[test]
    fn garbled_text_adds_nothing() {
        assert!(parse_sysinfo("this is not sysinfo\n::::\n").is_empty());
        assert!(parse_sysinfo("processor : 0\nvendor_id : GenuineIntel\n").is_empty());
    }
}
