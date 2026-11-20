# SPDX-License-Identifier: Apache-2.0
"""State-change events stay off, bounded, and quiet on the first scrape."""

from __future__ import annotations

from tests.helpers import make_config
from zvm_otel_exporter.collector import Collector
from zvm_otel_exporter.config import EventsConfig, load_config
from zvm_otel_exporter.events import (
    FEILONG_DOWN,
    IDENTITY,
    LOGOFF,
    LOGON,
    RELOCATE,
    SMAPI_DOWN,
    SMAPI_UP,
    SUPPRESSED,
    CollectionView,
    EventSource,
    GuestState,
    emit_log_records,
    view_from_samples,
)
from zvm_otel_exporter.feilong import FeilongClient
from zvm_otel_exporter.models import Sample
from zvm_otel_exporter.prometheus import render_prometheus


def _view(
    guests: dict[str, tuple[bool, str]] | None = None,
    *,
    smapi: bool | None = True,
    feilong: bool | None = True,
    identity: tuple[tuple[str, str], ...] = (("zvm.lpar.name", "LPAR1"),),
    complete: bool = False,
) -> CollectionView:
    return CollectionView(
        guests={
            name: GuestState(up=up, member=member) for name, (up, member) in (guests or {}).items()
        },
        smapi=smapi,
        feilong=feilong,
        identity=identity,
        guests_complete=complete,
    )


def _names(events) -> list[str]:
    return [event.name for event in events]


def test_events_are_disabled_by_default(mock_feilong) -> None:
    config = make_config(mock_feilong.url)
    assert config.events.enabled is False
    client = FeilongClient(config.feilong, config.secrets())
    collector = Collector(client, config)
    try:
        snapshot = collector.collect()
    finally:
        client.close()
    assert collector.events.records == ()
    text = render_prometheus(snapshot).decode()
    assert "zvm_events_total" not in text


def test_baseline_is_silent_and_second_sight_emits() -> None:
    source = EventSource(EventsConfig(enabled=True, confirmations=2))
    first = _view({"LINUX1": (True, "MEM1")})
    assert source.observe(first) == ()
    assert source.observe(_view({"LINUX1": (False, "MEM1")})) == ()
    logged_off = source.observe(_view({"LINUX1": (False, "MEM1")}))
    assert _names(logged_off) == [LOGOFF]
    assert logged_off[0].attributes["zvm.userid"] == "LINUX1"
    assert logged_off[0].severity_text == "INFO"


def test_flap_does_not_emit() -> None:
    source = EventSource(EventsConfig(enabled=True, confirmations=2))
    source.observe(_view({"LINUX1": (True, "")}))
    source.observe(_view({"LINUX1": (False, "")}))
    back = source.observe(_view({"LINUX1": (True, "")}))
    assert back == ()
    assert source.observe(_view({"LINUX1": (True, "")})) == ()


def test_relocate_logon_and_identity() -> None:
    source = EventSource(EventsConfig(enabled=True, confirmations=1))
    source.observe(_view({"LINUX1": (True, "MEM1")}))
    moved = source.observe(_view({"LINUX1": (True, "MEM2"), "LINUX2": (True, "MEM1")}))
    assert _names(moved) == [RELOCATE, LOGON]
    relocate = next(event for event in moved if event.name == RELOCATE)
    assert relocate.attributes["zvm.ssi.member"] == "MEM2"
    assert relocate.attributes["zvm.ssi.member.previous"] == "MEM1"
    changed = source.observe(
        _view(
            {"LINUX1": (True, "MEM2"), "LINUX2": (True, "MEM1")},
            identity=(("zvm.lpar.name", "LPAR9"),),
        )
    )
    assert _names(changed) == [IDENTITY]
    assert changed[0].attributes["zvm.identity.fields"] == "zvm.lpar.name"


def test_smapi_and_feilong_severity() -> None:
    source = EventSource(EventsConfig(enabled=True, confirmations=1))
    source.observe(_view())
    down = source.observe(_view(smapi=False, feilong=False))
    assert _names(down) == [SMAPI_DOWN, FEILONG_DOWN]
    assert {event.severity_text for event in down} == {"WARN"}
    up = source.observe(_view(smapi=True, feilong=True))
    assert _names(up) == [SMAPI_UP, "zvm.feilong.recovered"]
    assert {event.severity_text for event in up} == {"INFO"}


def test_cap_emits_one_summary() -> None:
    guests = {f"G{index}": (True, "") for index in range(6)}
    source = EventSource(EventsConfig(enabled=True, confirmations=1, max_per_cycle=2))
    source.observe(_view({}))
    events = source.observe(_view(guests))
    assert _names(events) == [LOGON, LOGON, SUPPRESSED]
    assert events[-1].attributes["zvm.events.dropped"] == "4"
    counts = {sample.attributes["event"]: sample.value for sample in source.counter_samples()}
    assert counts[LOGON] == 2
    assert counts[SUPPRESSED] == 4


def test_allowlist_drops_other_types() -> None:
    source = EventSource(EventsConfig(enabled=True, confirmations=1, types=(LOGON,)))
    source.observe(_view({"LINUX1": (True, "")}))
    events = source.observe(_view({"LINUX1": (False, "")}, smapi=False))
    assert events == ()


def test_allowlist_keeps_logon() -> None:
    source = EventSource(EventsConfig(enabled=True, confirmations=1, types=(LOGON,)))
    source.observe(_view({}))
    events = source.observe(_view({"LINUX1": (True, "")}, smapi=False))
    assert _names(events) == [LOGON]


def test_pending_guest_is_forgotten_when_it_disappears() -> None:
    source = EventSource(EventsConfig(enabled=True, confirmations=2))
    source.observe(_view({}))
    source.observe(_view({"LINUX1": (True, "")}))
    source.observe(_view({}))
    again = source.observe(_view({"LINUX1": (True, "")}))
    assert again == ()


def test_location_without_power_is_not_a_logoff() -> None:
    source = EventSource(EventsConfig(enabled=True, confirmations=1))
    source.observe(_view({"LINUX1": (True, "MEM1")}))
    quiet = source.observe(
        CollectionView(
            guests={"LINUX1": GuestState(up=None, member="MEM1")}, smapi=True, feilong=True
        )
    )
    assert quiet == ()


def test_string_false_does_not_enable_events(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "feilong:\n  url: https://feilong.example\n  admin_token: admin-token-value\n"
        "events:\n  enabled: 'false'\n",
        encoding="utf-8",
    )
    config = load_config(None, environ={"ZVM_EXPORTER_CONFIG": str(path)})
    assert config.events.enabled is False


def test_incomplete_guest_list_does_not_log_off_the_missing_guest() -> None:
    source = EventSource(EventsConfig(enabled=True, confirmations=1))
    source.observe(_view({"LINUX1": (True, ""), "LINUX2": (True, "")}))
    events = source.observe(_view({"LINUX2": (True, "")}))
    assert LOGOFF not in _names(events)


def test_complete_guest_list_logs_off_a_missing_guest() -> None:
    source = EventSource(EventsConfig(enabled=True, confirmations=1))
    full = _view({"LINUX1": (True, ""), "LINUX2": (True, "")}, complete=True)
    remaining = _view({"LINUX2": (True, "")}, complete=True)
    source.observe(full)
    events = source.observe(remaining)
    assert _names(events) == [LOGOFF]
    assert events[0].attributes["zvm.guest.id"] == "LINUX1"


def test_feilong_timeout_after_host_success_is_unhealthy(mock_feilong) -> None:
    config = make_config(mock_feilong.url)
    config.events = EventsConfig(enabled=True, confirmations=1)
    client = FeilongClient(config.feilong, config.secrets())
    collector = Collector(client, config)
    try:
        collector.collect()

        def host_then_timeout() -> tuple[list[Sample], bool]:
            collector._down = True
            return (
                [
                    Sample(
                        "zvm.host.info",
                        1.0,
                        {"zvm.host.name": "OPNSTK2", "zvm.system.name": "OPNSTK2"},
                    )
                ],
                True,
            )

        collector._gather = host_then_timeout  # type: ignore[method-assign]
        snapshot = collector.collect()
    finally:
        client.close()
    assert FEILONG_DOWN in _names(collector.events.records)
    up = next(sample for sample in snapshot.samples if sample.name == "zvm.exporter.up")
    assert up.value == 1.0


def test_carried_power_sample_does_not_confirm_logoff(mock_feilong) -> None:
    config = make_config(mock_feilong.url)
    config.events = EventsConfig(enabled=True, confirmations=2)
    client = FeilongClient(config.feilong, config.secrets())
    collector = Collector(client, config)
    try:
        collector.collect()

        def guest_turned_off() -> tuple[list[Sample], bool]:
            return (
                [
                    Sample(
                        "zvm.host.info",
                        1.0,
                        {"zvm.host.name": "OPNSTK2", "zvm.system.name": "OPNSTK2"},
                    ),
                    Sample(
                        "zvm.guest.up",
                        0.0,
                        {
                            "zvm.host.name": "OPNSTK2",
                            "zvm.guest.id": "LINUX1",
                            "zvm.power.state": "off",
                        },
                    ),
                ],
                True,
            )

        collector._gather = guest_turned_off  # type: ignore[method-assign]
        collector.collect()
        assert collector.events.records == ()

        def failed_scrape() -> tuple[list[Sample], bool]:
            collector._down = True
            return [], False

        collector._gather = failed_scrape  # type: ignore[method-assign]
        collector.collect()
    finally:
        client.close()
    assert LOGOFF not in _names(collector.events.records)
    source = EventSource(EventsConfig(enabled=True, confirmations=1))
    source.observe(_view({"LINUX1": (True, "")}))
    assert source.observe(_view({})) == ()


def test_view_from_samples_reads_power_member_and_identity() -> None:
    samples = [
        Sample("zvm.guest.up", 1.0, {"zvm.guest.id": "LINUX1", "zvm.power.state": "on"}),
        Sample(
            "zvm.guest.location",
            1.0,
            {"zvm.guest.id": "LINUX1", "zvm.ssi.member": "MEM1"},
        ),
        Sample("zvm.smapi.healthy", 0.0, {}),
        Sample("zvm.system.info", 1.0, {"zvm.lpar.name": "LPAR1", "zvm.host.name": "ZVM1"}),
    ]
    view = view_from_samples(samples, feilong_up=True)
    assert view.guests["LINUX1"] == GuestState(up=True, member="MEM1")
    assert view.smapi is False
    assert view.feilong is True
    assert ("zvm.lpar.name", "LPAR1") in view.identity


def test_otlp_log_record_shape() -> None:
    from opentelemetry._logs import SeverityNumber
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import (
        InMemoryLogRecordExporter,
        SimpleLogRecordProcessor,
    )
    from opentelemetry.sdk.resources import Resource

    provider = LoggerProvider(resource=Resource.create({"zvm.lpar.name": "LPAR1"}))
    exporter = InMemoryLogRecordExporter()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    logger = provider.get_logger("zvm-otel-exporter")
    source = EventSource(EventsConfig(enabled=True, confirmations=1))
    source.observe(_view({}))
    events = source.observe(_view({"LINUX1": (True, "")}))
    emit_log_records(logger, events)
    finished = exporter.get_finished_logs()
    assert len(finished) == 1
    record = finished[0].log_record
    assert record.event_name == LOGON
    assert dict(record.attributes)["event.name"] == LOGON
    assert dict(record.attributes)["zvm.guest.id"] == "LINUX1"
    assert record.severity_number == SeverityNumber.INFO
    assert dict(finished[0].resource.attributes)["zvm.lpar.name"] == "LPAR1"
    provider.shutdown()


def test_env_enables_events_and_rejects_unknown_types() -> None:
    config = load_config(
        None,
        environ={
            "ZVM_EXPORTER_FEILONG_URL": "https://feilong.example",
            "ZVM_EXPORTER_FEILONG_ADMIN_TOKEN": "admin-token-value",
            "ZVM_EXPORTER_EVENTS_ENABLED": "true",
            "ZVM_EXPORTER_EVENTS_TYPES": "zvm.guest.logon",
            "ZVM_EXPORTER_EVENTS_MAX_PER_CYCLE": "10",
        },
    )
    assert config.events.enabled is True
    assert config.events.types == ("zvm.guest.logon",)
    assert config.events.max_per_cycle == 10
    try:
        load_config(
            None,
            environ={
                "ZVM_EXPORTER_FEILONG_URL": "https://feilong.example",
                "ZVM_EXPORTER_FEILONG_ADMIN_TOKEN": "admin-token-value",
                "ZVM_EXPORTER_EVENTS_TYPES": "not.an.event",
            },
        )
    except Exception as exc:
        assert "unknown events.types" in str(exc)
    else:
        raise AssertionError("unknown event type was accepted")
