"""Read Schedule objects and decode them to plain data.

Reads go through :meth:`DirectReadMixin.direct_read_property`, so they also
work on devices that don't answer Who-Is. That read returns raw bacpypes3
values (a list of ``DailySchedule`` for ``weeklySchedule`` and so on); the
decoders here turn them into the dataclasses in :mod:`..types`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ..types import (
    BACnetDailySchedule,
    BACnetDateRange,
    BACnetObjectIdentifier,
    BACnetObjectPropertyReference,
    BACnetSchedule,
    BACnetSpecialEvent,
    BACnetSpecialEventPeriod,
    BACnetTimeValue,
)
from .values import normalize_object_type, to_native

logger = logging.getLogger(__name__)

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

_WILDCARD = 255


def _decode_time(t: Any) -> str:
    """bacpypes3 Time -> ``"HH:MM"`` or ``"HH:MM:SS"``; a wildcard part is ``"*"``."""
    hour, minute, second, _ = tuple(t)

    def part(v: int) -> str:
        return "*" if v == _WILDCARD else f"{v:02d}"

    if second in (0, _WILDCARD):
        return f"{part(hour)}:{part(minute)}"
    return f"{part(hour)}:{part(minute)}:{part(second)}"


def _decode_date(d: Any) -> str | None:
    """bacpypes3 Date -> ``"YYYY-MM-DD"``; ``None`` for a fully unspecified date.

    Partial or special dates keep the bacpypes3 text, e.g. ``"*-12-25 *"``.
    """
    year, month, day, _ = tuple(d)
    if year == month == day == _WILDCARD:
        return None
    if year != _WILDCARD and 1 <= month <= 12 and 1 <= day <= 31:
        return f"{1900 + year:04d}-{month:02d}-{day:02d}"
    return str(d)


def _decode_time_values(time_values: Any) -> list[BACnetTimeValue]:
    return [
        BACnetTimeValue(time=_decode_time(tv.time), value=to_native(tv.value))
        for tv in time_values or []
    ]


def decode_weekly_schedule(weekly: Any) -> list[BACnetDailySchedule]:
    """``weeklySchedule`` -> one :class:`BACnetDailySchedule` per day, Monday first."""
    return [
        BACnetDailySchedule(day=day, entries=_decode_time_values(daily.daySchedule))
        for day, daily in zip(DAYS, weekly or [], strict=False)
    ]


def decode_date_range(date_range: Any) -> BACnetDateRange:
    return BACnetDateRange(
        start=_decode_date(date_range.startDate),
        end=_decode_date(date_range.endDate),
    )


def _decode_period(period: Any) -> BACnetSpecialEventPeriod:
    reference = period.calendarReference
    if reference is not None:
        return BACnetSpecialEventPeriod(
            kind="calendar", calendar_instance=int(tuple(reference)[1])
        )
    entry = period.calendarEntry
    if entry.date is not None:
        return BACnetSpecialEventPeriod(kind="date", date=_decode_date(entry.date))
    if entry.dateRange is not None:
        date_range = decode_date_range(entry.dateRange)
        return BACnetSpecialEventPeriod(
            kind="range", start=date_range.start, end=date_range.end
        )
    if entry.weekNDay is not None:
        month, week, weekday = bytes(entry.weekNDay)
        return BACnetSpecialEventPeriod(
            kind="week_n_day", month=month, week=week, weekday=weekday
        )
    return BACnetSpecialEventPeriod(kind="unknown")


def decode_exception_schedule(exceptions: Any) -> list[BACnetSpecialEvent]:
    return [
        BACnetSpecialEvent(
            period=_decode_period(event.period),
            priority=int(event.eventPriority),
            entries=_decode_time_values(event.listOfTimeValues),
        )
        for event in exceptions or []
    ]


def decode_object_references(references: Any) -> list[BACnetObjectPropertyReference]:
    """``listOfObjectPropertyReferences`` -> the points the schedule writes to."""
    decoded = []
    for ref in references or []:
        object_type, instance = tuple(ref.objectIdentifier)
        device = ref.deviceIdentifier
        array_index = ref.propertyArrayIndex
        decoded.append(
            BACnetObjectPropertyReference(
                object_identifier=BACnetObjectIdentifier(
                    object_type=normalize_object_type(str(object_type)),
                    instance=int(instance),
                ),
                property_name=normalize_object_type(str(ref.propertyIdentifier)),
                array_index=int(array_index) if array_index is not None else None,
                device_id=int(tuple(device)[1]) if device is not None else None,
            )
        )
    return decoded


# (BACnetSchedule field, BACnet property, decoder). presentValue goes first:
# if it can't be read, the device is treated as unreachable and the rest are
# skipped, since each failed read costs a full timeout.
SCHEDULE_PROPERTIES: tuple[tuple[str, str, Callable[[Any], Any]], ...] = (
    ("present_value", "presentValue", to_native),
    ("name", "objectName", str),
    ("schedule_default", "scheduleDefault", to_native),
    ("effective_period", "effectivePeriod", decode_date_range),
    ("weekly_schedule", "weeklySchedule", decode_weekly_schedule),
    ("exception_schedule", "exceptionSchedule", decode_exception_schedule),
    ("controlled_points", "listOfObjectPropertyReferences", decode_object_references),
)


class ScheduleReadMixin:
    """Read one Schedule object as :class:`BACnetSchedule`."""

    async def read_schedule(
        self,
        device_address: str,
        instance: int,
        *,
        timeout: float = 5.0,
    ) -> BACnetSchedule | None:
        """Read and decode ``schedule:<instance>`` on ``device_address``.

        Returns ``None`` if ``presentValue`` can't be read: the schedule
        doesn't exist or the device didn't answer. Other properties that fail
        are listed in :attr:`BACnetSchedule.missing_properties`.

        ``timeout`` applies to each property read.
        """
        schedule = BACnetSchedule(device_address=device_address, instance=instance)
        for field_name, prop, decode in SCHEDULE_PROPERTIES:
            raw = await self.direct_read_property(  # type: ignore[attr-defined]
                device_address, "schedule", instance, prop, timeout=timeout
            )
            if raw is None:
                if field_name == "present_value":
                    return None
                schedule.missing_properties.append(prop)
                continue
            try:
                setattr(schedule, field_name, decode(raw))
            except (AttributeError, TypeError, ValueError) as exc:
                logger.warning(
                    "Could not decode %s schedule:%d %s: %s",
                    device_address,
                    instance,
                    prop,
                    exc,
                )
                schedule.missing_properties.append(prop)
        return schedule
