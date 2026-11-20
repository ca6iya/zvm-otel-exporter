# Copyright 2026 z/VM OTel Exporter contributors
# SPDX-License-Identifier: Apache-2.0
"""State-change events from consecutive scrapes.

The first scrape is a baseline and emits nothing. A later change is emitted
only after it has been seen ``confirmations`` times in a row, so a one-scrape
flap is dropped. Memory is the last confirmed view plus at most one pending
view. There is no extra Feilong call and no extra CP command.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from opentelemetry._logs import SeverityNumber

from zvm_otel_exporter.config import EventsConfig
from zvm_otel_exporter.models import Sample

LOGON = "zvm.guest.logon"
LOGOFF = "zvm.guest.logoff"
RELOCATE = "zvm.guest.relocate"
SMAPI_DOWN = "zvm.smapi.unhealthy"
SMAPI_UP = "zvm.smapi.recovered"
FEILONG_DOWN = "zvm.feilong.unhealthy"
FEILONG_UP = "zvm.feilong.recovered"
IDENTITY = "zvm.identity.changed"
SUPPRESSED = "zvm.events.suppressed"

EVENT_NAMES = (
    LOGON,
    LOGOFF,
    RELOCATE,
    SMAPI_DOWN,
    SMAPI_UP,
    FEILONG_DOWN,
    FEILONG_UP,
    IDENTITY,
    SUPPRESSED,
)
_WARN = {SMAPI_DOWN, FEILONG_DOWN}
_IDENTITY_KEYS = (
    "zvm.system.name",
    "zvm.host.name",
    "zvm.lpar.name",
    "zvm.lpar.number",
    "zvm.ssi.name",
)
_MEMBER_KEYS = ("ssi_member", "member_system_id", "host_system")


@dataclass(frozen=True)
class GuestState:
    """``up`` is None when this scrape has a member but no power sample."""

    up: bool | None
    member: str = ""


@dataclass(frozen=True)
class CollectionView:
    guests: Mapping[str, GuestState] = field(default_factory=dict)
    smapi: bool | None = None
    feilong: bool | None = None
    identity: tuple[tuple[str, str], ...] = ()
    guests_complete: bool = False


@dataclass(frozen=True)
class StateEvent:
    name: str
    body: str
    attributes: Mapping[str, str] = field(default_factory=dict)

    @property
    def severity_text(self) -> str:
        return "WARN" if self.name in _WARN else "INFO"

    @property
    def severity_number(self) -> SeverityNumber:
        return SeverityNumber.WARN if self.name in _WARN else SeverityNumber.INFO


def member_from_stat(raw: Mapping[str, object]) -> str:
    """Return an SSI member already present on a guest stat object."""

    for key in _MEMBER_KEYS:
        value = raw.get(key)
        if value:
            text = str(value).strip()
            if text:
                return text
    return ""


def view_from_samples(
    samples: list[Sample],
    *,
    feilong_up: bool | None,
    guests_complete: bool = False,
) -> CollectionView:
    guests: dict[str, GuestState] = {}
    members: dict[str, str] = {}
    smapi: bool | None = None
    identity: list[tuple[str, str]] = []
    for sample in samples:
        guest = sample.attributes.get("zvm.guest.id", "")
        if sample.name == "zvm.guest.up" and guest:
            guests[guest] = GuestState(up=sample.value >= 1.0, member="")
        elif sample.name == "zvm.guest.location" and guest:
            members[guest] = sample.attributes.get("zvm.ssi.member", "")
        elif sample.name == "zvm.smapi.healthy":
            smapi = sample.value >= 1.0
        elif sample.name == "zvm.system.info":
            identity = [
                (key, sample.attributes.get(key, ""))
                for key in _IDENTITY_KEYS
                if sample.attributes.get(key, "")
            ]
    merged = {
        guest: GuestState(up=state.up, member=members.get(guest, state.member))
        for guest, state in guests.items()
    }
    for guest, member in members.items():
        if guest not in merged and member:
            merged[guest] = GuestState(up=None, member=member)
    return CollectionView(
        guests=merged,
        smapi=smapi,
        feilong=feilong_up,
        identity=tuple(identity),
        guests_complete=guests_complete,
    )


class EventSource:
    """Diff the latest view against the last confirmed view."""

    def __init__(self, config: EventsConfig) -> None:
        self._config = config
        self._confirmed: CollectionView | None = None
        self._pending: dict[str, tuple[object, int]] = {}
        self._counts: dict[str, float] = {name: 0.0 for name in EVENT_NAMES}
        self.records: tuple[StateEvent, ...] = ()

    def observe(self, view: CollectionView) -> tuple[StateEvent, ...]:
        if not self._config.enabled:
            self.records = ()
            return ()
        if self._confirmed is None:
            self._confirmed = view
            self.records = ()
            return ()
        detected = self._changes(view)
        self._confirmed = self._advance(self._confirmed, view)
        allowed = self._allow(detected)
        emitted, dropped = _cap(allowed, self._config.max_per_cycle)
        if dropped:
            emitted.append(
                StateEvent(
                    SUPPRESSED,
                    f"{dropped} state changes were not exported individually",
                    {"zvm.events.dropped": str(dropped)},
                )
            )
        for event in emitted:
            if event.name != SUPPRESSED:
                self._counts[event.name] = self._counts.get(event.name, 0.0) + 1.0
        if dropped:
            self._counts[SUPPRESSED] = self._counts.get(SUPPRESSED, 0.0) + float(dropped)
        self.records = tuple(emitted)
        return self.records

    def counter_samples(self) -> list[Sample]:
        if not self._config.enabled:
            return []
        return [
            Sample("zvm.events", count, {"event": name})
            for name, count in self._counts.items()
            if count or name != SUPPRESSED
        ]

    def _allow(self, events: list[StateEvent]) -> list[StateEvent]:
        chosen = self._config.types
        if not chosen:
            return events
        allowed = set(chosen)
        return [event for event in events if event.name in allowed]

    def _changes(self, view: CollectionView) -> list[StateEvent]:
        assert self._confirmed is not None
        events: list[StateEvent] = []
        events.extend(self._flag("smapi", self._confirmed.smapi, view.smapi, SMAPI_DOWN, SMAPI_UP))
        events.extend(
            self._flag("feilong", self._confirmed.feilong, view.feilong, FEILONG_DOWN, FEILONG_UP)
        )
        events.extend(self._identity(view.identity))
        events.extend(self._guests(view))
        return events

    def _flag(
        self,
        key: str,
        previous: bool | None,
        current: bool | None,
        down_name: str,
        up_name: str,
    ) -> list[StateEvent]:
        if previous is None or current is None or previous == current:
            self._pending.pop(key, None)
            return []
        if not self._ready(key, current):
            return []
        if current:
            return [StateEvent(up_name, f"{key} recovered", {})]
        return [StateEvent(down_name, f"{key} became unhealthy", {})]

    def _identity(self, current: tuple[tuple[str, str], ...]) -> list[StateEvent]:
        assert self._confirmed is not None
        previous = self._confirmed.identity
        if not previous or not current or previous == current:
            self._pending.pop("identity", None)
            return []
        if not self._ready("identity", current):
            return []
        old = dict(previous)
        new = dict(current)
        changed = [
            key
            for key in _IDENTITY_KEYS
            if old.get(key, "") != new.get(key, "") and new.get(key, "")
        ]
        if not changed:
            return []
        return [
            StateEvent(
                IDENTITY,
                "z/VM identity labels changed",
                {"zvm.identity.fields": ",".join(changed)},
            )
        ]

    def _guests(self, view: CollectionView) -> list[StateEvent]:
        assert self._confirmed is not None
        previous = self._confirmed.guests
        current = view.guests
        self._drop_absent_pending(current)
        if previous and not current:
            return []
        events: list[StateEvent] = []
        for guest in sorted(set(previous) | set(current)):
            old = previous.get(guest)
            new = current.get(guest)
            key = "guest:" + guest
            if new is None and not view.guests_complete:
                continue
            if new is not None and new.up is None:
                self._pending.pop(key, None)
                if (
                    old is not None
                    and old.up is True
                    and old.member
                    and new.member
                    and old.member != new.member
                    and self._ready(key, new)
                ):
                    events.extend(_guest_events(guest, old, new))
                continue
            if old == new:
                self._pending.pop(key, None)
                continue
            if not self._ready(key, new):
                continue
            events.extend(_guest_events(guest, old, new))
        return events

    def _drop_absent_pending(self, current: Mapping[str, GuestState]) -> None:
        for key in list(self._pending):
            if key.startswith("guest:") and key.removeprefix("guest:") not in current:
                self._pending.pop(key, None)

    def _ready(self, key: str, value: object) -> bool:
        needed = self._config.confirmations
        if needed <= 1:
            self._pending.pop(key, None)
            return True
        seen = self._pending.get(key)
        count = seen[1] + 1 if seen is not None and seen[0] == value else 1
        if count >= needed:
            self._pending.pop(key, None)
            return True
        self._pending[key] = (value, count)
        return False

    def _advance(self, confirmed: CollectionView, view: CollectionView) -> CollectionView:
        """Keep unconfirmed guest and flag values at the previous state."""

        guests = dict(confirmed.guests)
        for guest, state in view.guests.items():
            if "guest:" + guest in self._pending:
                continue
            previous = guests.get(guest)
            if state.up is None and previous is not None:
                guests[guest] = GuestState(up=previous.up, member=state.member or previous.member)
            else:
                guests[guest] = state
        if view.guests_complete:
            for guest in list(guests):
                if guest not in view.guests and "guest:" + guest not in self._pending:
                    del guests[guest]
        smapi = confirmed.smapi if view.smapi is None or "smapi" in self._pending else view.smapi
        feilong = (
            confirmed.feilong
            if view.feilong is None or "feilong" in self._pending
            else view.feilong
        )
        identity = (
            confirmed.identity
            if not view.identity or "identity" in self._pending
            else view.identity
        )
        return CollectionView(guests=guests, smapi=smapi, feilong=feilong, identity=identity)


def _guest_events(guest: str, old: GuestState | None, new: GuestState | None) -> list[StateEvent]:
    attrs = {"zvm.guest.id": guest, "zvm.userid": guest}
    events: list[StateEvent] = []
    was_up = bool(old.up) if old is not None else False
    now_up = new.up if new is not None else None
    if now_up is True and not was_up:
        events.append(StateEvent(LOGON, f"{guest} logged on", attrs))
    elif now_up is False and was_up:
        events.append(StateEvent(LOGOFF, f"{guest} logged off", attrs))
    elif new is None and was_up:
        events.append(StateEvent(LOGOFF, f"{guest} logged off", attrs))
    old_member = old.member if old is not None else ""
    new_member = new.member if new is not None else ""
    if was_up and now_up is True and old_member and new_member and old_member != new_member:
        events.append(
            StateEvent(
                RELOCATE,
                f"{guest} relocated",
                {
                    **attrs,
                    "zvm.ssi.member": new_member,
                    "zvm.ssi.member.previous": old_member,
                },
            )
        )
    return events


def _cap(events: list[StateEvent], limit: int) -> tuple[list[StateEvent], int]:
    if len(events) <= limit:
        return list(events), 0
    kept = events[:limit]
    return kept, len(events) - limit


def emit_log_records(logger, events: tuple[StateEvent, ...] | list[StateEvent]) -> None:
    """Write events to an OpenTelemetry logger. No network I/O by itself."""

    for event in events:
        attributes = {"event.name": event.name, **event.attributes}
        logger.emit(
            severity_number=event.severity_number,
            severity_text=event.severity_text,
            body=event.body,
            attributes=attributes,
            event_name=event.name,
        )
