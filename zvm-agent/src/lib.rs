// Copyright 2026 z/VM OTel Exporter contributors
// SPDX-License-Identifier: Apache-2.0

//! In-process reader for one Linux guest.
//!
//! Guest files (`/proc`, `/proc/sysinfo`, s390 hypfs `diag_2fc`) and an
//! optional monitor fixture are aggregated here and exported as OTLP.
//! Feilong, SMAPI, and `/dev/monreader` are not called.

pub mod contract;
pub mod error;
pub mod hypfs;
pub mod monitor;
pub mod otlp;
pub mod procfs;
pub mod snapshot;
pub mod sysinfo;
