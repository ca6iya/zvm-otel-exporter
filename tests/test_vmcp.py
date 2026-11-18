"""vmcp parsing, caching, and the hard command budget."""

from __future__ import annotations

import threading
from importlib.resources import files

from tests.helpers import make_config, sample_values
from zvm_otel_exporter.collector import Collector
from zvm_otel_exporter.config import VmcpConfig
from zvm_otel_exporter.feilong import FeilongClient
from zvm_otel_exporter.prometheus import render_prometheus
from zvm_otel_exporter.vmcp import (
    CommandResult,
    SubprocessRunner,
    VmcpSource,
    parse_alloc,
    parse_load,
)


def _fixture(name: str) -> str:
    return files("zvm_otel_exporter.fixtures.vmcp").joinpath(name).read_text(encoding="utf-8")


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class FakeRunner:
    def __init__(self, outputs: dict[str, str], fail: set[str] | None = None) -> None:
        self.outputs = outputs
        self.fail = fail or set()
        self.calls: list[tuple[str, ...]] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.hold = False

    def run(self, args: tuple[str, ...], timeout: float) -> CommandResult:
        self.calls.append(args)
        if self.hold:
            self.entered.set()
            self.release.wait(1)
        key = args[-1]
        if key in self.fail:
            return CommandResult(stdout="", returncode=1)
        return CommandResult(stdout=self.outputs.get(key, ""))


def _outputs() -> dict[str, str]:
    return {
        "PAGE": _fixture("query_alloc_page.txt"),
        "SPOOL": _fixture("query_alloc_spool.txt"),
        "LOAD": _fixture("indicate_load.txt"),
    }


def _source(runner: FakeRunner, clock: Clock, interval: float = 60) -> VmcpSource:
    return VmcpSource(
        VmcpConfig(enabled=True, interval=interval, timeout=5),
        runner=runner,
        clock=clock,
    )


def test_page_and_spool_prefer_exact_volume_sums() -> None:
    page = parse_alloc(_fixture("query_alloc_page.txt"))
    assert page is not None
    assert page.allocated == 7 * 600840 + 180
    assert page.used == 14812
    assert page.allocated != 4107 * 1024
    spool = parse_alloc(_fixture("query_alloc_spool.txt"))
    assert spool is not None
    assert spool.allocated == 600840 * 2 + 510660 + 323100 + 601020 * 2
    assert spool.used == 599500 + 508033 + 321442 + 43651 + 81642 + 588935
    assert spool.used != 2093 * 1024


def test_summary_fallback_and_indicate_load_shapes() -> None:
    summary = parse_alloc(_fixture("query_alloc_summary_only.txt"))
    assert summary == parse_alloc("SUMMARY 1000 250 25%\nUSABLE 800 200 25%\n")
    assert summary is not None
    assert (summary.allocated, summary.used) == (1000, 250)
    assert parse_alloc(_fixture("unauthorized.txt")) is None
    modern = parse_load(_fixture("indicate_load.txt"))
    assert modern is not None
    assert modern.utilization == 0.61
    assert modern.cpu_count == 3
    assert modern.paging_rate == 6
    legacy = parse_load(_fixture("indicate_load_legacy.txt"))
    assert legacy is not None
    assert legacy.utilization == 0.88
    assert legacy.cpu_count == 3
    assert legacy.paging_rate == 23


def test_cache_and_backoff_limit_cp_commands() -> None:
    clock = Clock()
    runner = FakeRunner(_outputs())
    source = _source(runner, clock)
    first = source.collect("OPNSTK2")
    assert len(runner.calls) == 3
    assert [call[-1] for call in runner.calls] == ["PAGE", "SPOOL", "LOAD"]
    assert first.ok is True
    assert sample_values(first, "zvm.paging.used") == [14812]
    assert sample_values(first, "zvm.system.cpu.utilization") == [0.61]
    assert sample_values(first, "zvm.paging.rate") == [6]
    names = {sample.name for sample in first.samples}
    assert not any("volume" in sample.attributes for sample in first.samples)
    assert "zvm.system.cpu.utilization" in names
    clock.now += 59
    source.collect("OPNSTK2")
    assert len(runner.calls) == 3
    clock.now += 1
    source.collect("OPNSTK2")
    assert len(runner.calls) == 6

    failing = FakeRunner(_outputs(), fail={"PAGE"})
    failed = _source(failing, clock)
    assert failed.collect("OPNSTK2").ok is False
    assert len(failing.calls) == 3
    clock.now += 60
    failed.collect("OPNSTK2")
    assert len(failing.calls) == 3
    clock.now += 60
    failed.collect("OPNSTK2")
    assert len(failing.calls) == 6


def test_concurrent_collect_does_not_double_commands() -> None:
    clock = Clock()
    runner = FakeRunner(_outputs())
    runner.hold = True
    source = _source(runner, clock)
    results: list[int] = []

    def _run() -> None:
        reading = source.collect("OPNSTK2")
        results.append(len(reading.samples))

    first = threading.Thread(target=_run)
    first.start()
    assert runner.entered.wait(1)
    second = threading.Thread(target=_run)
    second.start()
    second.join(1)
    runner.release.set()
    first.join(1)
    assert len(runner.calls) == 3
    assert len(results) == 2


def test_subprocess_timeout_is_bounded(tmp_path) -> None:
    program = tmp_path / "vmcp"
    program.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    program.chmod(0o755)
    result = SubprocessRunner(str(program)).run(("QUERY", "ALLOC", "PAGE"), timeout=0.2)
    assert result.timed_out is True
    assert result.failed is True


def test_collector_exports_vmcp_through_prometheus(mock_feilong) -> None:
    config = make_config(mock_feilong.url)
    config.vmcp.enabled = True
    runner = FakeRunner(_outputs())
    clock = Clock()
    source = VmcpSource(config.vmcp, runner=runner, clock=clock)
    client = FeilongClient(config.feilong, config.secrets())
    try:
        snapshot = Collector(client, config, vmcp=source).collect()
        Collector(client, config, vmcp=source).collect()
    finally:
        client.close()
    text = render_prometheus(snapshot).decode()
    assert "zvm_paging_allocated_pages" in text
    assert "zvm_paging_used_pages" in text
    assert "zvm_spool_used_pages" in text
    assert "zvm_system_cpu_utilization" in text
    assert 'zvm_host_name="OPNSTK2"' in text
    assert len(runner.calls) == 3
    Collector(client, config, vmcp=source).collect()
    assert len(runner.calls) == 3


def test_power_state_calls_are_capped(mock_feilong) -> None:
    from zvm_otel_exporter.collector import Collector as CollectorType

    config = make_config(mock_feilong.url, per_guest_limit=1)
    client = FeilongClient(config.feilong, config.secrets())
    try:
        snapshot = CollectorType(client, config).collect()
    finally:
        client.close()
    power_calls = [path for path in mock_feilong.requests if path.endswith("/power_state")]
    assert power_calls == ["/guests/CMSGUEST/power_state"]
    assert sample_values(snapshot, "zvm.guest.up", **{"zvm.guest.id": "LINUX01"}) == []
    assert sample_values(snapshot, "zvm.guest.cpu.time", **{"zvm.guest.id": "LINUX01"}) == [
        509530870 / 1_000_000
    ]
