"""Typed BACnet models for discovery operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ...utils import KEEP_EMPTY

__all__ = [
    "BACnetObjectIdentifier",
    "BACnetDeviceIdentifier",
    "BACnetDevice",
    "BACnetObject",
    "ScheduleValue",
    "BACnetTimeValue",
    "BACnetDailySchedule",
    "BACnetDateRange",
    "BACnetSpecialEventPeriod",
    "BACnetSpecialEvent",
    "BACnetObjectPropertyReference",
    "BACnetSchedule",
    "ReadFailure",
    "BACnetScheduleReadResult",
    "BACnetScanTimings",
    "BACnetNetworkScanInput",
    "BACnetObjectsDiscoveryInput",
    "BACnetNetworkScanResult",
    "BACnetObjectsDiscoveryResult",
]


@dataclass(slots=True)
class BACnetObjectIdentifier:
    """BACnet object identity (object type + instance)."""

    object_type: str
    instance: int


@dataclass(slots=True)
class BACnetDeviceIdentifier:
    """BACnet device identity (network address + device id)."""

    address: str
    device_id: int


@dataclass(slots=True)
class BACnetDevice:
    """Discovered BACnet device with stable uid."""

    uid: str
    identifier: BACnetDeviceIdentifier
    name: str | None = None
    vendor: str | None = None
    model: str | None = None
    firmware: str | None = None
    object_list: list[BACnetObjectIdentifier] = field(default_factory=list)


@dataclass(slots=True)
class BACnetObject:
    """Discovered BACnet object with stable uid."""

    uid: str
    device: BACnetDeviceIdentifier
    object_identifier: BACnetObjectIdentifier
    name: str | None = None
    description: str | None = None
    units: str | None = None
    unit_id: str | None = None
    value: bool | int | float | str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


ReadFailure = Literal[
    "no_response",
    "unknown_object",
    "unknown_property",
    "access_denied",
    "decode_error",
    "error",
]
"""Why a BACnet read failed.

- ``"no_response"``: the device did not answer (offline or unreachable).
- ``"unknown_object"``: the device has no such object.
- ``"unknown_property"``: the object has no such property.
- ``"access_denied"``: the device refused to return the value.
- ``"decode_error"``: the value arrived but could not be decoded.
- ``"error"``: any other failure; the log has details.
"""

ScheduleValue = bool | int | float | str | None
"""A value a schedule commands. ``None`` is BACnet Null: "release"."""


@dataclass(slots=True)
class BACnetTimeValue:
    """One schedule entry: from ``time`` on, command ``value``.

    ``time`` is ``"HH:MM"``, or ``"HH:MM:SS"`` when seconds are set. An
    unspecified part shows as ``"*"``. ``value`` ``None`` means release: the
    schedule stops commanding and its default applies.
    """

    time: str
    value: ScheduleValue = field(metadata=KEEP_EMPTY)


@dataclass(slots=True)
class BACnetDailySchedule:
    """The entries of one weekday, ``"Monday"`` to ``"Sunday"``."""

    day: str
    entries: list[BACnetTimeValue] = field(default_factory=list, metadata=KEEP_EMPTY)


@dataclass(slots=True)
class BACnetDateRange:
    """Inclusive date range. ``None`` at either end means any date.

    Full dates are ``"YYYY-MM-DD"``. Partial or special dates (every year,
    odd months, last day of month) keep the bacpypes3 text, e.g.
    ``"*-12-25 *"``.
    """

    start: str | None = field(default=None, metadata=KEEP_EMPTY)
    end: str | None = field(default=None, metadata=KEEP_EMPTY)


@dataclass(slots=True)
class BACnetSpecialEventPeriod:
    """When an exception applies. ``kind`` says which fields are set.

    - ``"date"``: ``date``.
    - ``"range"``: ``start`` and ``end`` (as in :class:`BACnetDateRange`).
    - ``"week_n_day"``: ``month``, ``week`` (week of month) and ``weekday``
      (1 = Monday); 255 means any.
    - ``"calendar"``: ``calendar_instance``, a Calendar object on the device.
    """

    kind: Literal["date", "range", "week_n_day", "calendar", "unknown"]
    date: str | None = None
    start: str | None = None
    end: str | None = None
    month: int | None = None
    week: int | None = None
    weekday: int | None = None
    calendar_instance: int | None = None


@dataclass(slots=True)
class BACnetSpecialEvent:
    """One exception schedule entry. Lower ``priority`` wins (1 is highest)."""

    period: BACnetSpecialEventPeriod
    priority: int
    entries: list[BACnetTimeValue] = field(default_factory=list)


@dataclass(slots=True)
class BACnetObjectPropertyReference:
    """A property a schedule writes to.

    ``device_id`` is set only when the object is on another device.
    """

    object_identifier: BACnetObjectIdentifier
    property_name: str
    array_index: int | None = None
    device_id: int | None = None


@dataclass(slots=True)
class BACnetSchedule:
    """A Schedule object, decoded to plain data.

    A property that could not be read or decoded keeps its default here.
    ``missing_properties`` maps its BACnet name to the :data:`ReadFailure`.
    Use it to tell "not read" apart from "empty" or "Null". :func:`obs.to_dict` keeps the None values that
    carry meaning (release, any date), so its output can be trusted as is.
    """

    device_address: str
    instance: int
    name: str | None = None
    present_value: ScheduleValue = field(default=None, metadata=KEEP_EMPTY)
    schedule_default: ScheduleValue = field(default=None, metadata=KEEP_EMPTY)
    effective_period: BACnetDateRange | None = None
    weekly_schedule: list[BACnetDailySchedule] = field(default_factory=list)
    exception_schedule: list[BACnetSpecialEvent] = field(default_factory=list)
    controlled_points: list[BACnetObjectPropertyReference] = field(default_factory=list)
    missing_properties: dict[str, ReadFailure] = field(default_factory=dict)


@dataclass(slots=True)
class BACnetScheduleReadResult:
    """Result of reading one Schedule object.

    ``data`` is set whenever the schedule could be read at all, even if some
    properties are missing. When it is None, ``failure`` says why: the device
    did not answer (``"no_response"``) or has no such schedule
    (``"unknown_object"``). ``error`` is a human-readable message.
    """

    device_address: str
    instance: int
    data: BACnetSchedule | None = None
    failure: ReadFailure | None = None
    error: str | None = None


@dataclass(slots=True)
class BACnetScanTimings:
    """Execution timing details for a scan operation."""

    started_at_utc: str
    finished_at_utc: str
    duration_seconds: float


@dataclass(slots=True)
class BACnetNetworkScanInput:
    """Inputs for BACnet network discovery."""

    timeout: int
    network: str | None = None
    client_ip: str | None = None
    bbmd_ip: str | None = None


@dataclass(slots=True)
class BACnetObjectsDiscoveryInput:
    """Inputs for BACnet object discovery on a single device."""

    device: BACnetDeviceIdentifier
    object_list: list[BACnetObjectIdentifier] | None = None
    rpm_batch_size: int = 10
    max_instance: int = 1000
    client_ip: str | None = None
    bbmd_ip: str | None = None
    include_schedules: bool = False


@dataclass(slots=True)
class BACnetNetworkScanResult:
    """Result wrapper for network-level BACnet device discovery."""

    input: BACnetNetworkScanInput
    data: list[BACnetDevice]
    timings: BACnetScanTimings
    success: bool
    error: str | None = None


@dataclass(slots=True)
class BACnetObjectsDiscoveryResult:
    """Result wrapper for device-level BACnet object discovery."""

    input: BACnetObjectsDiscoveryInput
    data: list[BACnetObject]
    timings: BACnetScanTimings
    success: bool
    error: str | None = None
