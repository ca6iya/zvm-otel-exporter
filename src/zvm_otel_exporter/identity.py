# SPDX-License-Identifier: Apache-2.0
"""z/VM system and LPAR identity from /proc/sysinfo, Feilong, and overrides.

/proc/sysinfo is a local file on Linux on Z. It is read at most once per
``identity.interval`` (default and minimum 10 minutes). Configured values
always win. Missing files are ignored after a single log line.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from zvm_otel_exporter.config import IdentityConfig
from zvm_otel_exporter.models import Sample

log = logging.getLogger(__name__)

_MAX_LABEL = 128
_SYSINFO_KEYS = {
    "LPAR Name": "lpar_name",
    "LPAR Number": "lpar_number",
    "Type": "cpc_type",
    "Sequence Code": "cpc_sequence",
    "Plant": "cpc_plant",
    "VM00 Name": "system_name",
}


@dataclass(frozen=True)
class SystemLabels:
    host_name: str = ""
    system_name: str = ""
    lpar_name: str = ""
    lpar_number: str = ""
    cpc_type: str = ""
    cpc_model: str = ""
    cpc_sequence: str = ""
    cpc_plant: str = ""
    site: str = ""
    environment: str = ""
    ssi_name: str = ""
    arch: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "zvm.host.name": self.host_name,
            "zvm.system.name": self.system_name,
            "lpar": self.lpar_name,
            "lpar.number": self.lpar_number,
            "zvm.cpc.type": self.cpc_type,
            "zvm.cpc.model": self.cpc_model,
            "zvm.cpc.sequence": self.cpc_sequence,
            "zvm.cpc.plant": self.cpc_plant,
            "zvm.site": self.site,
            "deployment.environment": self.environment,
            "zvm.ssi.name": self.ssi_name,
            "host.arch": self.arch,
        }

    def resource_attributes(self) -> dict[str, str]:
        """OTel resource attributes. Empty values are omitted."""

        host = self.host_name or self.system_name
        raw = {
            "host.name": host,
            "host.arch": self.arch,
            "host.id": self.cpc_sequence,
            "deployment.environment.name": self.environment,
            "zvm.system.name": self.system_name,
            "zvm.host.name": self.host_name,
            "zvm.lpar.name": self.lpar_name,
            "zvm.lpar.number": self.lpar_number,
            "zvm.cpc.type": self.cpc_type,
            "zvm.cpc.model": self.cpc_model,
            "zvm.cpc.sequence": self.cpc_sequence,
            "zvm.cpc.plant": self.cpc_plant,
            "zvm.site": self.site,
            "zvm.ssi.name": self.ssi_name,
        }
        return {key: value for key, value in raw.items() if value}


def parse_sysinfo(text: str) -> dict[str, str]:
    """Parse Linux on Z ``/proc/sysinfo`` into identity fields."""

    found: dict[str, str] = {}
    for raw in text.splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            continue
        mapped = _SYSINFO_KEYS.get(key)
        if mapped:
            found[mapped] = _clip(value.split()[0] if mapped != "lpar_name" else value)
            continue
        if key == "Model":
            token = value.split()[0]
            found["cpc_model"] = _clip(token)
    if found.get("system_name") and not found.get("host_name"):
        found["host_name"] = found["system_name"]
    return found


class IdentitySource:
    """Cached identity. File reads happen at most once per interval."""

    def __init__(
        self,
        config: IdentityConfig,
        clock: Callable[[], float] | None = None,
        reader: Callable[[], str] | None = None,
    ) -> None:
        self._config = config
        self._clock = clock or time.monotonic
        self._reader = reader or self._read_file
        self._cached: dict[str, str] = {}
        self._next = 0.0
        self._logged_missing = False

    def sysinfo(self) -> dict[str, str]:
        now = self._clock()
        if self._next > 0 and now < self._next:
            return dict(self._cached)
        self._cached = parse_sysinfo(self._reader())
        self._next = now + self._config.interval
        return dict(self._cached)

    def observe(self, discovered: Mapping[str, str] | None = None) -> SystemLabels:
        merged = self.sysinfo()
        for key, value in (discovered or {}).items():
            if value:
                merged[key] = value
        overrides = {
            "host_name": self._config.host_name,
            "system_name": self._config.system_name,
            "lpar_name": self._config.lpar_name,
            "lpar_number": self._config.lpar_number,
            "cpc_type": self._config.cpc_type,
            "cpc_model": self._config.cpc_model,
            "cpc_sequence": self._config.cpc_sequence,
            "cpc_plant": self._config.cpc_plant,
            "site": self._config.site,
            "environment": self._config.environment,
            "ssi_name": self._config.ssi_name,
            "arch": self._config.arch,
        }
        for key, value in overrides.items():
            if value:
                merged[key] = _clip(value)
        return SystemLabels(
            host_name=merged.get("host_name", ""),
            system_name=merged.get("system_name", ""),
            lpar_name=merged.get("lpar_name", ""),
            lpar_number=merged.get("lpar_number", ""),
            cpc_type=merged.get("cpc_type", ""),
            cpc_model=merged.get("cpc_model", ""),
            cpc_sequence=merged.get("cpc_sequence", ""),
            cpc_plant=merged.get("cpc_plant", ""),
            site=merged.get("site", ""),
            environment=merged.get("environment", ""),
            ssi_name=merged.get("ssi_name", ""),
            arch=merged.get("arch", ""),
        )

    def resource_attributes(self, discovered: Mapping[str, str] | None = None) -> dict[str, str]:
        return self.observe(discovered).resource_attributes()

    def _read_file(self) -> str:
        path = Path(self._config.sysinfo_path)
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            if not self._logged_missing:
                log.info("system identity file is not available at %s", path)
                self._logged_missing = True
            return ""


def identity_sample(labels: SystemLabels) -> Sample | None:
    attributes = {key: value for key, value in labels.as_dict().items() if value}
    if not attributes:
        return None
    # Keep a stable label set so Prometheus families do not change shape.
    full = {key: labels.as_dict().get(key, "") for key in labels.as_dict()}
    return Sample("zvm.system.info", 1.0, full)


def discovered_from_samples(samples: list[Sample]) -> dict[str, str]:
    """Pull identity already present on this scrape. No extra I/O."""

    found: dict[str, str] = {}
    for sample in samples:
        if sample.name == "zvm.host.info":
            host = sample.attributes.get("zvm.host.name", "")
            system = sample.attributes.get("zvm.system.name", "")
            arch = sample.attributes.get("host.arch", "")
            model = sample.attributes.get("zvm.cec.model", "")
            if host:
                found["host_name"] = host
            if system:
                found["system_name"] = system
            if arch:
                found["arch"] = arch
            if model:
                found["cpc_model"] = model
        elif sample.name == "zvm.ssi.member.joined":
            ssi = sample.attributes.get("zvm.ssi.name", "")
            if ssi and "ssi_name" not in found:
                found["ssi_name"] = ssi
    return found


def _clip(value: str) -> str:
    text = " ".join(value.split())
    return text[:_MAX_LABEL]
