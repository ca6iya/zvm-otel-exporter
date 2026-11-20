# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0

"""Scrape Feilong and produce a snapshot.

A connection or authentication failure marks Feilong down for the rest of that
scrape, so a dead host does not wait out a timeout on every route. The last
successful z/VM series are kept and ``zvm.exporter.scrape.stale`` is set, and
the HTTP server keeps answering.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

from zvm_otel_exporter import __version__
from zvm_otel_exporter.config import Config
from zvm_otel_exporter.events import EventSource, view_from_samples
from zvm_otel_exporter.feilong import (
    FeilongAuthError,
    FeilongClient,
    FeilongError,
    FeilongNotFound,
    FeilongUnavailable,
)
from zvm_otel_exporter.identity import (
    IdentitySource,
    discovered_from_samples,
    identity_sample,
)
from zvm_otel_exporter.models import Sample, Snapshot
from zvm_otel_exporter.translate import (
    diskpool_samples,
    guest_stat_samples,
    host_samples,
    interface_samples,
    minidisk_samples,
    parse_id_list,
    parse_power,
    pcif_samples,
    power_samples,
    smapi_samples,
    ssi_samples,
    version_samples,
    vswitch_samples,
)
from zvm_otel_exporter.vmcp import VmcpSource

log = logging.getLogger(__name__)


class Collector:
    def __init__(
        self,
        client: FeilongClient,
        config: Config,
        vmcp: VmcpSource | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.api_errors = 0
        self.last_success = 0.0
        self.last_good: tuple[Sample, ...] = ()
        self.host_name = ""
        self._down = False
        self._lock = threading.Lock()
        self._warned_fast_scrape = False
        if vmcp is not None:
            self.vmcp: VmcpSource | None = vmcp
        elif config.vmcp.enabled:
            self.vmcp = VmcpSource(config.vmcp)
        else:
            self.vmcp = None
        self.identity = IdentitySource(config.identity)
        self.events = EventSource(config.events)
        self.power_complete = False

    def collect(self) -> Snapshot:
        started = time.perf_counter()
        wall = time.time()
        self._down = False
        self.power_complete = False
        self._warn_fast_scrape()
        try:
            if self.config.feilong.enabled:
                fresh, host_ok = self._gather()
            else:
                fresh, host_ok = [], False
        except Exception as exc:
            log.warning("unexpected scrape error: %s", exc)
            with self._lock:
                self.api_errors += 1
            fresh, host_ok = [], False
        vmcp_ok = False
        if self.vmcp is not None:
            host = self.host_name or self.config.vmcp.host_name or "local"
            reading = self.vmcp.collect(host)
            fresh.extend(reading.samples)
            vmcp_ok = reading.ok
        info = identity_sample(self.identity.observe(discovered_from_samples(fresh)))
        if info is not None:
            fresh.append(info)
        if not self.config.feilong.enabled:
            up = vmcp_ok
        elif self.config.collectors.host:
            up = host_ok
        else:
            up = not self._down
        if up:
            self.last_good = tuple(fresh)
            self.last_success = wall
            zvm_samples = list(fresh)
            stale = False
        else:
            fresh_names = {sample.name for sample in fresh}
            carried = [sample for sample in self.last_good if sample.name not in fresh_names]
            zvm_samples = [*carried, *fresh]
            stale = bool(carried)
        duration = time.perf_counter() - started
        samples = [*zvm_samples, *self._exporter_samples(up, stale, duration)]
        feilong_up = None if not self.config.feilong.enabled else not self._down
        guests_complete = (
            self.config.feilong.enabled
            and self.config.collectors.power_state
            and self.power_complete
            and not stale
        )
        self.events.observe(
            view_from_samples(
                fresh,
                feilong_up=feilong_up,
                guests_complete=guests_complete,
            )
        )
        samples.extend(self.events.counter_samples())
        log.info(
            "scrape finished up=%s stale=%s series=%s api_errors=%s duration=%.3fs",
            up,
            stale,
            len(samples),
            self.api_errors,
            duration,
        )
        cached_at = None if self.vmcp is None else self.vmcp.cached_at
        clock = None if self.vmcp is None else self.vmcp.clock
        return Snapshot(
            tuple(samples),
            up,
            stale,
            wall,
            vmcp_cached_at=cached_at,
            clock=clock,
        )

    def _warn_fast_scrape(self) -> None:
        if self._warned_fast_scrape or not self.config.feilong.enabled:
            return
        if self.config.scrape_interval >= 30:
            return
        self._warned_fast_scrape = True
        log.warning(
            "scrape_interval %.0fs is below 30s; Feilong is queried on every scrape",
            self.config.scrape_interval,
        )

    def _exporter_samples(self, up: bool, stale: bool, duration: float) -> list[Sample]:
        with self._lock:
            errors = self.api_errors
        return [
            Sample("zvm.exporter.info", 1.0, {"service.version": __version__}),
            Sample("zvm.exporter.up", 1.0 if up else 0.0, {}),
            Sample("zvm.exporter.scrape.duration", duration, {}),
            Sample("zvm.exporter.scrape.errors", float(errors), {}),
            Sample("zvm.exporter.scrape.stale", 1.0 if stale else 0.0, {}),
            Sample("zvm.exporter.scrape.last_success", self.last_success, {}),
        ]

    def _call(self, name: str, fn, *, missing_ok: bool = False):  # noqa: ANN001
        with self._lock:
            if self._down:
                return None
        try:
            return fn()
        except FeilongNotFound:
            if missing_ok:
                log.debug("%s was not found", name)
                return None
            with self._lock:
                self.api_errors += 1
            log.warning("%s was not found", name)
            return None
        except (FeilongUnavailable, FeilongAuthError) as exc:
            with self._lock:
                self.api_errors += 1
                self._down = True
            log.warning("%s failed: %s", name, exc)
            return None
        except FeilongError as exc:
            with self._lock:
                self.api_errors += 1
            log.warning("%s failed: %s", name, exc)
            return None

    def _gather(self) -> tuple[list[Sample], bool]:
        toggles = self.config.collectors
        fresh: list[Sample] = []
        if toggles.version:
            output = self._call("feilong version", lambda: self.client.get_output("/"))
            if output is not None:
                fresh.extend(version_samples(output))
        if toggles.smapi:
            output = self._call("smapi health", lambda: self.client.get_output("/smapi_health"))
            if output is not None:
                fresh.extend(smapi_samples(output))
        host_ok = False
        if toggles.host:
            output = self._call("host info", lambda: self.client.get_output("/host"))
            if isinstance(output, dict):
                host, samples = host_samples(output)
                self.host_name = host
                fresh.extend(samples)
                host_ok = True
        host = self.host_name or "unknown"
        if toggles.disk_pool:
            pools: list[str | None] = list(self.config.feilong.disk_pools) or [None]
            for pool in pools:
                query = {"details": "true" if self.config.feilong.disk_pool_details else "false"}
                if pool:
                    query["poolname"] = pool
                output = self._call(
                    f"disk pool {pool or 'default'}",
                    lambda query=query: self.client.get_output("/host/diskpool", query),
                )
                if isinstance(output, dict):
                    fresh.extend(diskpool_samples(host, output, pool))
        self._guests(fresh, host)
        if toggles.vswitches:
            names = self._call("vswitches", lambda: self.client.get_output("/vswitches"))
            if isinstance(names, list):
                limited = names[: self.config.feilong.max_vswitches]
                if len(names) > len(limited):
                    log.warning(
                        "vswitch list truncated from %s to %s",
                        len(names),
                        len(limited),
                    )
                for name in limited:
                    detail = self._call(
                        f"vswitch {name}",
                        lambda name=name: self.client.get_output(
                            f"/vswitches/{quote(str(name), safe='')}"
                        ),
                        missing_ok=True,
                    )
                    if isinstance(detail, dict):
                        fresh.extend(vswitch_samples(host, detail))
        if toggles.ssi:
            output = self._call("ssi", lambda: self.client.get_output("/host/ssi"))
            if isinstance(output, list):
                fresh.extend(ssi_samples(output))
        if toggles.pcif:
            output = self._call("pcif", lambda: self.client.get_output("/host/pcif"))
            if isinstance(output, list):
                fresh.extend(pcif_samples(host, output))
        return fresh, host_ok

    def _guests(self, fresh: list[Sample], host: str) -> None:
        toggles = self.config.collectors
        need = any(
            (
                toggles.guests,
                toggles.interfaces,
                toggles.power_state,
                toggles.minidisks,
            )
        )
        if not need:
            return
        managed: list[str] | None = None
        host_guests: list[str] | None = None
        if toggles.guests or toggles.power_state or toggles.minidisks:
            raw = self._call("managed guests", lambda: self.client.get_output("/guests"))
            if raw is not None:
                managed = parse_id_list(raw)
        if toggles.guests or toggles.interfaces:
            raw = self._call("host guests", lambda: self.client.get_output("/host/guests"))
            if raw is not None:
                host_guests = parse_id_list(raw)
        if toggles.guests:
            if managed is not None:
                fresh.append(
                    Sample(
                        "zvm.guests",
                        float(len(managed)),
                        {"zvm.host.name": host, "zvm.guest.scope": "managed"},
                    )
                )
            if host_guests is not None:
                fresh.append(
                    Sample(
                        "zvm.guests",
                        float(len(host_guests)),
                        {"zvm.host.name": host, "zvm.guest.scope": "host"},
                    )
                )
        merged = _merge_ids(managed, host_guests)
        if len(merged) > self.config.feilong.max_guests:
            log.warning(
                "guest list truncated from %s to %s",
                len(merged),
                self.config.feilong.max_guests,
            )
            merged = merged[: self.config.feilong.max_guests]
        if toggles.guests and merged:
            stats = self._batched("/guests/stats", merged, "guest stats")
            fresh.extend(guest_stat_samples(host, stats))
        if toggles.interfaces and merged:
            nics = self._batched("/guests/interfacestats", merged, "guest interface stats")
            fresh.extend(interface_samples(host, nics))
        power_ids = managed if managed is not None else (host_guests or [])
        capped = self._cap_per_guest(power_ids)
        if toggles.power_state and capped:
            states = self._power(capped)
            fresh.extend(power_samples(host, states))
            self.power_complete = (
                managed is not None
                and not self._down
                and len(capped) == len(power_ids)
                and len(states) == len(capped)
            )
        elif toggles.power_state and managed is not None and not power_ids and not self._down:
            self.power_complete = True
        if toggles.minidisks and capped:
            for userid in capped:
                output = self._call(
                    f"minidisks {userid}",
                    lambda userid=userid: self.client.get_output(
                        f"/guests/{quote(userid, safe='')}/disks"
                    ),
                    missing_ok=True,
                )
                if output is not None:
                    fresh.extend(minidisk_samples(host, userid, output))

    def _batched(self, path: str, userids: list[str], name: str) -> dict[str, object]:
        merged: dict[str, object] = {}
        size = self.config.feilong.batch_size
        for start in range(0, len(userids), size):
            batch = userids[start : start + size]
            query = {"userid": ",".join(batch)}
            output = self._call(
                name,
                lambda query=query: self.client.get_output(path, query),
            )
            if isinstance(output, dict):
                merged.update(output)
        return merged

    def _power(self, userids: list[str]) -> dict[str, str]:
        states: dict[str, str] = {}
        workers = min(self.config.feilong.concurrency, len(userids), 16) or 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._one_power, userid): userid for userid in userids}
            for future in as_completed(futures):
                userid = futures[future]
                try:
                    state = future.result()
                except Exception as exc:
                    log.warning("power state for %s failed: %s", userid, exc)
                    continue
                if state:
                    states[userid] = state
        return states

    def _one_power(self, userid: str) -> str | None:
        output = self._call(
            f"power state {userid}",
            lambda: self.client.get_output(f"/guests/{quote(userid, safe='')}/power_state"),
            missing_ok=True,
        )
        if output is None:
            return None
        return parse_power(output)

    def _cap_per_guest(self, userids: list[str]) -> list[str]:
        limit = self.config.feilong.per_guest_limit
        ordered = sorted(userids)
        if len(ordered) > limit:
            log.warning(
                "per-guest Feilong calls limited to %s of %s guests",
                limit,
                len(ordered),
            )
            return ordered[:limit]
        return ordered


def _merge_ids(managed: list[str] | None, host_guests: list[str] | None) -> list[str]:
    seen: list[str] = []
    for source in (host_guests, managed):
        if not source:
            continue
        for userid in source:
            if userid not in seen:
                seen.append(userid)
    return seen
