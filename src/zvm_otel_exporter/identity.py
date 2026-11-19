# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0
"""z/VM system and LPAR identity from /proc/sysinfo, Feilong, and overrides.

``/proc/sysinfo`` is a local file on Linux on Z. It is read at most once per
``identity.interval`` (default and minimum 10 minutes) and at most 64 KiB.
Configured values always win. A missing file is ignored after one log line.

VM00 in ``/proc/sysinfo`` is the hypervisor level closest to the hardware
(STSI order), not the z/VM system name. ``VM00 Name`` is a virtual-machine
userid. The z/VM system and host names come from Feilong, from an override,
or stay empty. ``QUERY USERID`` (``userid AT sysname``) is applied only when
a caller already has that text. This collector does not issue the command.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from zvm_otel_exporter.config import IdentityConfig
from zvm_otel_exporter.models import Sample

log = logging.getLogger(__name__)

_MAX_LABEL = 128
_SYSINFO_CAP = 64 * 1024
_SYSINFO_KEYS = {
    "LPAR Name": "lpar_name",
    "LPAR Number": "lpar_number",
    "Type": "cpc_type",
    "Sequence Code": "cpc_sequence",
    "Plant": "cpc_plant",
}
# Attribute key on the info metric and on the OTLP resource, then the field.
# Prometheus label names are these keys with "." replaced by "_".
_ATTRIBUTES = (
    ("host.name", "host_name"),
    ("host.arch", "arch"),
    ("deployment.environment.name", "environment"),
    ("zvm.system.name", "system_name"),
    ("zvm.host.name", "host_name"),
    ("zvm.lpar.name", "lpar_name"),
    ("zvm.lpar.number", "lpar_number"),
    ("zvm.cpc.type", "cpc_type"),
    ("zvm.cpc.model", "cpc_model"),
    ("zvm.cpc.sequence", "cpc_sequence"),
    ("zvm.cpc.plant", "cpc_plant"),
    ("zvm.site", "site"),
    ("zvm.ssi.name", "ssi_name"),
    ("zvm.hypervisor", "hypervisor"),
    ("zvm.exporter.guest", "exporter_guest"),
    ("zvm.vm.level", "vm_level"),
)
_VM_NAME = re.compile(r"^VM(\d{2}) Name$")
_VM_CP = re.compile(r"^VM(\d{2}) Control Program$")
_QUERY_USERID = re.compile(r"^(\S+)\s+AT\s+(\S+)\s*$", re.IGNORECASE | re.MULTILINE)


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
    hypervisor: str = ""
    exporter_guest: str = ""
    vm_level: str = ""

    def as_dict(self) -> dict[str, str]:
        """Metric attributes. Keys match :meth:`resource_attributes`."""

        values = self._values()
        return {key: values[field] for key, field in _ATTRIBUTES}

    def resource_attributes(self) -> dict[str, str]:
        """OTel resource attributes. Empty values are omitted. No ``host.id``."""

        raw = self.as_dict()
        return {key: value for key, value in raw.items() if value}

    def _values(self) -> dict[str, str]:
        return {
            "host_name": self.host_name,
            "system_name": self.system_name,
            "lpar_name": self.lpar_name,
            "lpar_number": self.lpar_number,
            "cpc_type": self.cpc_type,
            "cpc_model": self.cpc_model,
            "cpc_sequence": self.cpc_sequence,
            "cpc_plant": self.cpc_plant,
            "site": self.site,
            "environment": self.environment,
            "ssi_name": self.ssi_name,
            "arch": self.arch,
            "hypervisor": self.hypervisor,
            "exporter_guest": self.exporter_guest,
            "vm_level": self.vm_level,
        }


def parse_sysinfo(text: str) -> dict[str, str]:
    """Parse Linux on Z ``/proc/sysinfo``.

    LPAR name and number, CPC type, model, sequence, and plant come from this
    file. ``VM00 Control Program`` is ``zvm.hypervisor`` (the level closest to
    the hardware). The exporter guest userid is the ``Name`` at the highest
    VM level: VM00 when Linux is a first-level guest, VM01 when Linux is
    second-level. Neither name is the z/VM system name.
    """

    found: dict[str, str] = {}
    levels: dict[int, dict[str, str]] = {}
    for raw in text.splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not value or set(value) <= {":"}:
            continue
        mapped = _SYSINFO_KEYS.get(key)
        if mapped == "lpar_name":
            found[mapped] = _clip(value)
            continue
        if mapped:
            found[mapped] = _clip(value.split()[0])
            continue
        if key == "Model":
            found["cpc_model"] = _clip(value.split()[0])
            continue
        name_match = _VM_NAME.match(key)
        if name_match:
            levels.setdefault(int(name_match.group(1)), {})["name"] = _clip(value.split()[0])
            continue
        cp_match = _VM_CP.match(key)
        if cp_match:
            levels.setdefault(int(cp_match.group(1)), {})["cp"] = _clip(value)
    if not levels:
        return found
    outer = levels[min(levels)]
    if outer.get("cp"):
        found["hypervisor"] = outer["cp"]
    inner_level = max(levels)
    inner = levels[inner_level]
    if inner.get("name"):
        found["exporter_guest"] = inner["name"]
        found["vm_level"] = f"VM{inner_level:02d}"
    return found


def parse_query_userid(text: str) -> dict[str, str]:
    """Parse ``QUERY USERID`` output: ``userid AT sysname``.

    Returns nothing when the text is not that sentence. Callers must pass
    text they already have. This function does not run CP.
    """

    match = _QUERY_USERID.search(text.strip())
    if match is None:
        return {}
    return {
        "exporter_guest": _clip(match.group(1)),
        "system_name": _clip(match.group(2)),
    }


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
        incoming = dict(discovered or {})
        userid_text = incoming.pop("query_userid", "")
        for key, value in incoming.items():
            if value:
                merged[key] = value
        if userid_text:
            for key, value in parse_query_userid(userid_text).items():
                if value and not merged.get(key):
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
            "hypervisor": self._config.hypervisor,
            "exporter_guest": self._config.exporter_guest,
            "vm_level": self._config.vm_level,
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
            hypervisor=merged.get("hypervisor", ""),
            exporter_guest=merged.get("exporter_guest", ""),
            vm_level=merged.get("vm_level", ""),
        )

    def resource_attributes(self, discovered: Mapping[str, str] | None = None) -> dict[str, str]:
        return self.observe(discovered).resource_attributes()

    def _read_file(self) -> str:
        path = Path(self._config.sysinfo_path)
        try:
            with path.open("rb") as handle:
                raw = handle.read(_SYSINFO_CAP)
        except OSError:
            if not self._logged_missing:
                log.info("system identity file is not available at %s", path)
                self._logged_missing = True
            return ""
        return raw.decode("utf-8", errors="replace")


def identity_sample(labels: SystemLabels) -> Sample | None:
    attributes = labels.as_dict()
    if not any(attributes.values()):
        return None
    return Sample("zvm.system.info", 1.0, attributes)


def discovered_from_samples(samples: list[Sample]) -> dict[str, str]:
    """Pull identity already present on this scrape. No extra I/O.

    Host and system names come from Feilong ``zvm.host.info``. vmcp-only
    mode does not run ``QUERY USERID``, so those names stay empty unless
    an override is set. A cached ``QUERY USERID`` line can be passed to
    :meth:`IdentitySource.observe` as ``query_userid`` by a caller that
    already has it.
    """

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
