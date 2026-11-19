# SPDX-License-Identifier: Apache-2.0
"""System and LPAR identity stays cheap and overridable."""

from __future__ import annotations

import re
from pathlib import Path

from tests.helpers import make_config
from zvm_otel_exporter.collector import Collector
from zvm_otel_exporter.config import IdentityConfig, OtlpConfig, load_config
from zvm_otel_exporter.feilong import FeilongClient
from zvm_otel_exporter.identity import (
    IdentitySource,
    identity_sample,
    parse_query_userid,
    parse_sysinfo,
)
from zvm_otel_exporter.models import Sample
from zvm_otel_exporter.otel import SnapshotStore, start_otel
from zvm_otel_exporter.prometheus import render_prometheus


def test_parse_sysinfo() -> None:
    text = Path("tests/fixtures/sysinfo.txt").read_text(encoding="utf-8")
    parsed = parse_sysinfo(text)
    assert parsed["lpar_name"] == "ZVMLPAR1"
    assert parsed["lpar_number"] == "15"
    assert parsed["cpc_type"] == "3906"
    assert parsed["cpc_model"] == "702"
    assert parsed["cpc_sequence"] == "00000000000C4B8E"
    assert parsed["cpc_plant"] == "02"
    assert parsed["hypervisor"] == "z/VM 7.3.0"
    assert parsed["exporter_guest"] == "LINUX1"
    assert parsed["vm_level"] == "VM00"
    assert "system_name" not in parsed
    assert "host_name" not in parsed


def test_sysinfo_is_cached_and_overrides_win() -> None:
    clock = {"now": 0.0}
    reads = {"n": 0}

    def reader() -> str:
        reads["n"] += 1
        return Path("tests/fixtures/sysinfo.txt").read_text(encoding="utf-8")

    source = IdentitySource(
        IdentityConfig(interval=600, site="POK", lpar_name="OVERRIDE"),
        clock=lambda: clock["now"],
        reader=reader,
    )
    first = source.observe({"host_name": "OPNSTK2", "arch": "s390x", "ssi_name": "ZVM2SSI"})
    assert reads["n"] == 1
    assert first.lpar_name == "OVERRIDE"
    assert first.site == "POK"
    assert first.host_name == "OPNSTK2"
    assert first.system_name == ""
    assert first.hypervisor == "z/VM 7.3.0"
    assert first.exporter_guest == "LINUX1"
    assert first.ssi_name == "ZVM2SSI"
    assert first.arch == "s390x"
    clock["now"] = 599
    source.observe()
    assert reads["n"] == 1
    clock["now"] = 600
    source.observe()
    assert reads["n"] == 2
    resource = first.resource_attributes()
    assert resource["host.name"] == "OPNSTK2"
    assert resource["host.arch"] == "s390x"
    assert "host.id" not in resource
    assert resource["zvm.cpc.sequence"] == "00000000000C4B8E"
    assert resource["zvm.lpar.name"] == "OVERRIDE"
    assert resource["zvm.hypervisor"] == "z/VM 7.3.0"
    assert "deployment.environment.name" not in resource
    assert "host.type" not in resource
    assert set(resource) <= set(first.as_dict())


def test_env_override_and_minimum_interval() -> None:
    config = load_config(
        None,
        environ={
            "ZVM_EXPORTER_FEILONG_URL": "https://feilong.example",
            "ZVM_EXPORTER_FEILONG_ADMIN_TOKEN": "admin-token-value",
            "ZVM_EXPORTER_IDENTITY_LPAR_NAME": "LPARX",
            "ZVM_EXPORTER_IDENTITY_ENVIRONMENT": "prod",
        },
    )
    assert config.identity.lpar_name == "LPARX"
    assert config.identity.environment == "prod"
    try:
        load_config(
            None,
            environ={
                "ZVM_EXPORTER_FEILONG_URL": "https://feilong.example",
                "ZVM_EXPORTER_FEILONG_ADMIN_TOKEN": "admin-token-value",
                "ZVM_EXPORTER_IDENTITY_INTERVAL": "60",
            },
        )
    except Exception as exc:
        assert "600" in str(exc)
    else:
        raise AssertionError("short identity interval was accepted")


def test_collector_exports_system_info(mock_feilong) -> None:
    config = make_config(mock_feilong.url)
    config.identity = IdentityConfig(
        sysinfo_path="tests/fixtures/sysinfo.txt",
        interval=600,
        site="LAB",
        environment="test",
    )
    client = FeilongClient(config.feilong, config.secrets())
    collector = Collector(client, config)
    try:
        snapshot = collector.collect()
    finally:
        client.close()
    text = render_prometheus(snapshot).decode()
    assert "zvm_system_info{" in text
    assert 'zvm_lpar_name="ZVMLPAR1"' in text
    assert 'zvm_host_name="OPNSTK2"' in text
    assert 'zvm_system_name="OPNSTK2"' in text
    assert re.search(r'(^|[{,])host_name="OPNSTK2"', text)
    assert 'zvm_site="LAB"' in text
    assert 'deployment_environment_name="test"' in text
    assert 'zvm_ssi_name="ZVM2SSI"' in text
    assert 'zvm_hypervisor="z/VM 7.3.0"' in text
    assert 'zvm_exporter_guest="LINUX1"' in text
    assert 'zvm_vm_level="VM00"' in text
    assert "host_id" not in text
    info = [sample for sample in snapshot.samples if sample.name == "zvm.system.info"]
    assert len(info) == 1
    assert info[0].value == 1.0
    guest = next(sample for sample in snapshot.samples if sample.name == "zvm.guest.cpu.count")
    assert "zvm.lpar.name" not in guest.attributes
    assert "lpar" not in guest.attributes


def test_otel_resource_includes_identity() -> None:
    source = IdentitySource(
        IdentityConfig(site="POK", environment="prod", arch="s390x", host_name="ZVM1"),
        reader=lambda: "",
    )
    store = SnapshotStore()
    store.update(
        __import__("zvm_otel_exporter.models", fromlist=["Snapshot"]).Snapshot(
            samples=(Sample("zvm.exporter.up", 1.0, {}),),
            up=True,
            stale=False,
            scraped_at=0.0,
        )
    )

    runtime = start_otel(
        OtlpConfig(enabled=True, endpoint="http://127.0.0.1:1", protocol="http", timeout=1),
        store,
        export_interval_ms=3_600_000,
        resource_attributes=source.resource_attributes(),
    )
    values = dict(runtime.provider._sdk_config.resource.attributes)
    runtime.shutdown()
    assert values["host.name"] == "ZVM1"
    assert values["deployment.environment.name"] == "prod"
    assert values["zvm.site"] == "POK"
    assert values["service.name"] == "zvm-otel-exporter"
    assert "host.id" not in values


def test_vm01_is_the_inner_guest_and_vm00_stays_the_hypervisor() -> None:
    parsed = parse_sysinfo(
        "LPAR Name:            LPAR1\n"
        "VM00 Name:            OUTER\n"
        "VM00 Control Program: z/VM    7.3.0\n"
        "VM01 Name:            LINUX99\n"
        "VM01 Control Program: z/VM    7.2.0\n"
    )
    assert parsed["hypervisor"] == "z/VM 7.3.0"
    assert parsed["exporter_guest"] == "LINUX99"
    assert parsed["vm_level"] == "VM01"
    assert "system_name" not in parsed


def test_garbled_and_non_z_sysinfo_add_nothing() -> None:
    assert parse_sysinfo("this is not sysinfo\n::::\n") == {}
    assert parse_sysinfo("processor : 0\nvendor_id : GenuineIntel\n") == {}
    assert identity_sample(IdentitySource(IdentityConfig(), reader=lambda: "").observe()) is None


def test_missing_sysinfo_file_is_empty(tmp_path: Path) -> None:
    source = IdentitySource(IdentityConfig(sysinfo_path=str(tmp_path / "missing"), interval=600))
    assert source.observe().lpar_name == ""
    assert source.observe().system_name == ""


def test_sysinfo_read_stops_at_64_kib(tmp_path: Path) -> None:
    path = tmp_path / "sysinfo"
    path.write_bytes(b"LPAR Name:            KEEP\n" + (b"A" * (70 * 1024)) + b"\nPlant: 99\n")
    source = IdentitySource(IdentityConfig(sysinfo_path=str(path), interval=600))
    parsed = source.sysinfo()
    assert parsed["lpar_name"] == "KEEP"
    assert "cpc_plant" not in parsed


def test_cache_picks_up_a_new_file_only_after_the_interval() -> None:
    clock = {"now": 0.0}
    pages = iter(
        (
            "LPAR Name:            ONE\n",
            "LPAR Name:            TWO\n",
        )
    )
    source = IdentitySource(
        IdentityConfig(interval=600),
        clock=lambda: clock["now"],
        reader=lambda: next(pages),
    )
    assert source.observe().lpar_name == "ONE"
    clock["now"] = 599
    assert source.observe().lpar_name == "ONE"
    clock["now"] = 600
    assert source.observe().lpar_name == "TWO"


def test_override_beats_feilong_and_query_userid_fills_only_gaps() -> None:
    source = IdentitySource(
        IdentityConfig(system_name="OVERRIDE", lpar_name="LPARX"),
        reader=lambda: "LPAR Name:            FROMFILE\nVM00 Name:            LINUX1\n",
    )
    labels = source.observe(
        {
            "host_name": "FROMFEILONG",
            "system_name": "FROMSYS",
            "query_userid": "GUEST1 AT ZVM1",
        }
    )
    assert labels.lpar_name == "LPARX"
    assert labels.system_name == "OVERRIDE"
    assert labels.host_name == "FROMFEILONG"
    assert labels.exporter_guest == "LINUX1"
    bare = IdentitySource(IdentityConfig(), reader=lambda: "").observe(
        {"query_userid": "GUEST1 AT ZVM1"}
    )
    assert bare.system_name == "ZVM1"
    assert bare.exporter_guest == "GUEST1"
    assert parse_query_userid("not a userid line") == {}
