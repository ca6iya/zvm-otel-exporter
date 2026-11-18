"""Pure mapping from Feilong payloads to samples."""

from __future__ import annotations

from zvm_otel_exporter.translate import (
    diskpool_samples,
    host_samples,
    parse_ssi_lines,
    ssi_samples,
)


def test_host_units() -> None:
    _host, samples = host_samples(
        {
            "hypervisor_hostname": "OPNSTK2",
            "zvm_host": "OPNSTK2",
            "vcpus": 6,
            "vcpus_used": 4,
            "memory_mb": 2,
            "memory_mb_used": 1,
            "disk_total": 2,
            "disk_used": 1,
            "disk_available": 1,
            "cpu_info": {"architecture": "s390x", "cec_model": "2817"},
            "hypervisor_type": "zvm",
            "hypervisor_version": 640,
            "ipl_time": "IPL at 06/02/17 11:07:10 EDT",
            "zcc_userid": "ZCCUID",
        }
    )
    by_name = {sample.name: sample.value for sample in samples}
    assert by_name["zvm.host.cpu.count"] == 6
    assert by_name["zvm.host.memory.limit"] == 2 * 1024 * 1024
    assert by_name["zvm.host.disk.limit"] == 2 * 1024**3


def test_diskpool_details_shape_from_the_api_docs() -> None:
    output = {
        "ICICPL": [
            {
                "volume_name": "vol1",
                "device_type": "3390",
                "free_size": 2345,
                "dasd_group": "ICICPL",
            }
        ]
    }
    samples = diskpool_samples("HOST", output, None)
    assert len(samples) == 1
    assert samples[0].name == "zvm.disk_pool.volume.free"
    assert samples[0].value == 2345
    assert samples[0].attributes["zvm.disk.pool"] == "ICICPL"


def test_diskpool_summary_and_configured_label() -> None:
    samples = diskpool_samples(
        "HOST",
        {"disk_total": 10, "disk_used": 4, "disk_available": 6},
        "ECKD:pool1",
    )
    assert {sample.name for sample in samples} == {
        "zvm.disk_pool.limit",
        "zvm.disk_pool.usage",
        "zvm.disk_pool.available",
    }
    assert samples[0].attributes["zvm.disk.pool"] == "ECKD:pool1"
    assert samples[0].value == 10 * 1024**3


def test_ssi_text_records() -> None:
    lines = [
        "ssi_name = ZVM2SSI",
        "ssi_mode = Stable",
        "",
        "member_slot = 1",
        "member_system_id = OPNSTK2",
        "member_state = Joined",
        "",
        "member_slot = 2",
        "member_system_id = OPNSTK3",
        "member_state = Down",
    ]
    members = parse_ssi_lines(lines)
    assert members[0]["ssi_name"] == "ZVM2SSI"
    assert members[1]["member_state"] == "Down"
    samples = ssi_samples(lines)
    assert [sample.value for sample in samples] == [1.0, 0.0]
    assert samples[1].attributes["zvm.ssi.member"] == "OPNSTK3"
