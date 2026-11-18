# SPDX-License-Identifier: Apache-2.0
"""Collector against the mock Feilong server."""

from __future__ import annotations

from tests.helpers import make_config, sample_values
from zvm_otel_exporter.collector import Collector
from zvm_otel_exporter.feilong import FeilongClient
from zvm_otel_exporter.mock import load_fixture

_GIB = 1024**3
_MIB = 1024**2
_KIB = 1024


def _collect(server, **feilong):
    config = make_config(server.url, **feilong)
    client = FeilongClient(config.feilong, config.secrets())
    try:
        return Collector(client, config).collect()
    finally:
        client.close()


def test_full_scrape_matches_fixture(mock_feilong) -> None:
    fixture = load_fixture()
    snapshot = _collect(mock_feilong)
    assert snapshot.up is True
    assert snapshot.stale is False
    assert sample_values(snapshot, "zvm.host.cpu.count") == [6]
    assert sample_values(snapshot, "zvm.host.memory.limit") == [51200 * _MIB]
    assert sample_values(snapshot, "zvm.host.memory.usage") == [0]
    assert sample_values(snapshot, "zvm.host.disk.available") == [3057 * _GIB]
    assert sample_values(
        snapshot, "zvm.disk_pool.available", **{"zvm.disk.pool": "ECKD:ECKDPOOL"}
    ) == [3060 * _GIB]
    assert sample_values(snapshot, "zvm.disk_pool.volume.free", **{"zvm.volume.name": "VOL1"}) == [
        2345
    ]
    assert sample_values(snapshot, "zvm.guests", **{"zvm.guest.scope": "managed"}) == [2]
    assert sample_values(snapshot, "zvm.guests", **{"zvm.guest.scope": "host"}) == [3]
    linux_cpu = fixture["stats"]["LINUX01"]["used_cpu_time_us"] / 1_000_000
    assert sample_values(snapshot, "zvm.guest.cpu.time", **{"zvm.guest.id": "LINUX01"}) == [
        linux_cpu
    ]
    assert sample_values(snapshot, "zvm.guest.memory.usage", **{"zvm.guest.id": "LINUX01"}) == [
        396232 * _KIB
    ]
    assert sample_values(snapshot, "zvm.guest.up", **{"zvm.guest.id": "LINUX01"}) == [1]
    assert sample_values(snapshot, "zvm.guest.up", **{"zvm.guest.id": "CMSGUEST"}) == [0]
    assert sample_values(
        snapshot,
        "zvm.guest.network.io",
        **{"zvm.guest.id": "LINUX01", "network.io.direction": "receive"},
    ) == [6131168]
    assert sample_values(
        snapshot,
        "zvm.guest.cpu.samples",
        **{"zvm.cpu.sample.state": "delay", "zvm.guest.id": "LINUX01"},
    ) == [116]
    assert sample_values(snapshot, "zvm.guest.disk.size", **{"zvm.guest.id": "LINUX01"}) == [29128]
    assert sample_values(snapshot, "zvm.vswitch.authorized_users") == [2]
    assert sample_values(snapshot, "zvm.vswitch.up") == [1]
    assert sample_values(snapshot, "zvm.ssi.member.joined") == [1, 1]
    assert sample_values(snapshot, "zvm.pcif.enabled", **{"zvm.pcif.id": "0000015E"}) == [1]
    assert sample_values(snapshot, "zvm.pcif.enabled", **{"zvm.pcif.id": "0000015F"}) == [0]
    assert sample_values(snapshot, "zvm.smapi.healthy") == [1]
    assert sample_values(snapshot, "zvm.smapi.calls", **{"zvm.smapi.call.state": "fail"}) == [1]
    assert sample_values(snapshot, "zvm.feilong.info") == [1]
    assert sample_values(snapshot, "zvm.exporter.up") == [1]
    names = {sample.name for sample in snapshot.samples}
    assert "zvm.page" not in " ".join(names)
    assert "spool" not in " ".join(names)


def test_batches_guest_stats(mock_feilong) -> None:
    _collect(mock_feilong, batch_size=1)
    stats_calls = [path for path in mock_feilong.requests if path == "/guests/stats"]
    assert len(stats_calls) >= 3


def test_unreachable_is_not_fatal_and_second_failure_is_stale() -> None:
    config = make_config("http://127.0.0.1:1", timeout=1)
    client = FeilongClient(config.feilong, config.secrets())
    collector = Collector(client, config)
    try:
        first = collector.collect()
    finally:
        client.close()
    assert first.up is False
    assert first.stale is False
    assert sample_values(first, "zvm.exporter.up") == [0]
    assert sample_values(first, "zvm.host.cpu.count") == []
    assert sample_values(first, "zvm.exporter.scrape.errors") == [1]


def test_serves_previous_samples_when_feilong_goes_away(mock_feilong) -> None:
    config = make_config(mock_feilong.url)
    client = FeilongClient(config.feilong, config.secrets())
    collector = Collector(client, config)
    try:
        good = collector.collect()
        mock_feilong.fail_paths.add("/")
        mock_feilong.fail_paths.add("/host")
        mock_feilong.fail_paths.add("/smapi_health")
        bad = collector.collect()
    finally:
        client.close()
    assert good.up is True
    assert bad.up is False
    assert bad.stale is True
    assert sample_values(bad, "zvm.host.cpu.count") == [6]
    assert sample_values(bad, "zvm.exporter.up") == [0]
    assert sample_values(bad, "zvm.exporter.scrape.stale") == [1]


def test_optional_collector_failure_keeps_host_up(mock_feilong) -> None:
    mock_feilong.fail_paths.add("/guests/stats")
    snapshot = _collect(mock_feilong)
    assert snapshot.up is True
    assert sample_values(snapshot, "zvm.host.cpu.count") == [6]
    assert sample_values(snapshot, "zvm.guest.cpu.time") == []
    assert sample_values(snapshot, "zvm.exporter.scrape.errors") == [1]
