from __future__ import annotations

import asyncio

import pytest
from bacpypes3.basetypes import (
    CalendarEntry,
    DailySchedule,
    DateRange,
    DeviceObjectPropertyReference,
    PropertyIdentifier,
    SpecialEvent,
    SpecialEventPeriod,
    TimeValue,
    WeekNDay,
)
from bacpypes3.constructeddata import AnyAtomic
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Date,
    Enumerated,
    Null,
    ObjectIdentifier,
    Real,
    Time,
    Unsigned,
)

from obs import to_dict
from obs.discovery.bacnet.controller import BACnetController
from obs.discovery.bacnet.controller import schedule_read
from obs.discovery.bacnet.controller.values import to_native
from obs.discovery.bacnet.types import (
    BACnetDailySchedule,
    BACnetDateRange,
    BACnetObjectIdentifier,
    BACnetObjectPropertyReference,
    BACnetSchedule,
    BACnetSpecialEvent,
    BACnetSpecialEventPeriod,
    BACnetTimeValue,
)

ADDRESS = "192.168.1.50"


def _tv(time: str, value) -> TimeValue:
    return TimeValue(time=Time(time), value=AnyAtomic(value))


def _occupancy_weekly() -> list[DailySchedule]:
    """A boolean occupancy schedule: occupied Monday 06-12, Tuesday 04-09.

    The occupied period ends with Null (release), not False.
    """
    days: list[list[TimeValue]] = [[] for _ in range(7)]
    days[0] = [_tv("06:00:00", Boolean(True)), _tv("12:00:00", Null(()))]
    days[1] = [_tv("04:00:00", Boolean(True)), _tv("09:00:00", Null(()))]
    return [DailySchedule(daySchedule=d) for d in days]


def _occupancy_schedule(**overrides) -> dict[str, object]:
    values: dict[str, object] = {
        "presentValue": AnyAtomic(Boolean(False)),
        "objectName": CharacterString("occupancyschedule"),
        "scheduleDefault": AnyAtomic(Boolean(False)),
        "effectivePeriod": DateRange(startDate=Date("*-*-*"), endDate=Date("*-*-*")),
        "weeklySchedule": _occupancy_weekly(),
        "exceptionSchedule": [],
        "listOfObjectPropertyReferences": [
            DeviceObjectPropertyReference(
                objectIdentifier=ObjectIdentifier("binary-value,1"),
                propertyIdentifier=PropertyIdentifier("present-value"),
            )
        ],
    }
    values.update(overrides)
    return values


class FakeDevice(BACnetController):
    """A controller whose direct reads come from a dict of schedule:0 values.

    ``failures`` maps a property to the ReadFailure its read returns. A
    property in neither dict fails with "unknown_property".
    """

    def __init__(
        self, props: dict[str, object], failures: dict[str, str] | None = None
    ):
        super().__init__(client_ip="192.168.1.2/24")
        self.props = props
        self.failures = failures or {}
        self.reads: list[str] = []

    async def direct_read_property_detailed(
        self, device_address, object_type, instance, property_name, *, timeout=5.0
    ):
        assert (device_address, object_type, instance) == (ADDRESS, "schedule", 0)
        self.reads.append(property_name)
        if property_name in self.failures:
            return None, self.failures[property_name]
        if property_name not in self.props:
            return None, "unknown_property"
        return self.props[property_name], None


def _read(device: FakeDevice) -> BACnetSchedule:
    result = asyncio.run(device.read_schedule(ADDRESS, 0))
    assert result.failure is None
    assert result.data is not None
    return result.data


# --- decoding ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (AnyAtomic(Null(())), None),
        (Null(()), None),
        (AnyAtomic(Unsigned(1)), 1),
        (AnyAtomic(Real(72.5)), 72.5),
        (AnyAtomic(Boolean(True)), True),
        (AnyAtomic(Enumerated(1)), 1),  # binary schedule: active
        (AnyAtomic(CharacterString("occupied")), "occupied"),
    ],
)
def test_to_native_decodes_schedule_values(raw, expected) -> None:
    # when
    value = to_native(raw)

    # then
    assert value == expected
    assert type(value) is type(expected)


def test_decode_weekly_schedule_keeps_release_as_none() -> None:
    # when
    weekly = schedule_read.decode_weekly_schedule(_occupancy_weekly())

    # then
    assert weekly[0] == BACnetDailySchedule(
        day="Monday",
        entries=[
            BACnetTimeValue(time="06:00", value=True),
            BACnetTimeValue(time="12:00", value=None),
        ],
    )
    assert weekly[1].entries == [
        BACnetTimeValue(time="04:00", value=True),
        BACnetTimeValue(time="09:00", value=None),
    ]
    assert [d.day for d in weekly] == list(schedule_read.DAYS)
    assert all(d.entries == [] for d in weekly[2:])


def test_decode_time_keeps_seconds_only_when_set() -> None:
    # when
    weekly = schedule_read.decode_weekly_schedule(
        [DailySchedule(daySchedule=[_tv("07:30:15", Unsigned(1))])]
    )

    # then
    assert weekly[0].entries[0].time == "07:30:15"


def test_unspecified_effective_period_means_any_date() -> None:
    # given
    period = DateRange(startDate=Date("*-*-*"), endDate=Date("*-*-*"))

    # when / then
    assert schedule_read.decode_date_range(period) == BACnetDateRange(None, None)


def test_effective_period_with_dates() -> None:
    # given
    period = DateRange(startDate=Date("2026-01-01"), endDate=Date("2026-12-31"))

    # when / then
    assert schedule_read.decode_date_range(period) == BACnetDateRange(
        "2026-01-01", "2026-12-31"
    )


def test_partial_date_keeps_bacpypes3_text() -> None:
    # given — every year on 25 December.
    period = DateRange(startDate=Date((255, 12, 25, 255)), endDate=Date("*-*-*"))

    # when / then
    assert schedule_read.decode_date_range(period) == BACnetDateRange("*-12-25 *", None)


def test_decode_exception_schedule_period_kinds() -> None:
    # given
    exceptions = [
        SpecialEvent(
            period=SpecialEventPeriod(
                calendarEntry=CalendarEntry(date=Date("2026-12-25"))
            ),
            listOfTimeValues=[_tv("00:00:00", Unsigned(0))],
            eventPriority=16,
        ),
        SpecialEvent(
            period=SpecialEventPeriod(
                calendarEntry=CalendarEntry(
                    dateRange=DateRange(
                        startDate=Date("2026-12-24"), endDate=Date("2027-01-01")
                    )
                )
            ),
            listOfTimeValues=[],
            eventPriority=10,
        ),
        SpecialEvent(
            period=SpecialEventPeriod(calendarReference=ObjectIdentifier("calendar,1")),
            listOfTimeValues=[],
            eventPriority=8,
        ),
        SpecialEvent(
            period=SpecialEventPeriod(
                # Any month, last week, Monday.
                calendarEntry=CalendarEntry(weekNDay=WeekNDay(b"\xff\x06\x01"))
            ),
            listOfTimeValues=[],
            eventPriority=12,
        ),
        SpecialEvent(
            period=SpecialEventPeriod(calendarEntry=CalendarEntry()),
            listOfTimeValues=[],
            eventPriority=16,
        ),
    ]

    # when
    decoded = schedule_read.decode_exception_schedule(exceptions)

    # then
    assert decoded[0] == BACnetSpecialEvent(
        period=BACnetSpecialEventPeriod(kind="date", date="2026-12-25"),
        priority=16,
        entries=[BACnetTimeValue(time="00:00", value=0)],
    )
    assert decoded[1].period == BACnetSpecialEventPeriod(
        kind="range", start="2026-12-24", end="2027-01-01"
    )
    assert decoded[2].period == BACnetSpecialEventPeriod(
        kind="calendar", calendar_instance=1
    )
    assert decoded[3].period == BACnetSpecialEventPeriod(
        kind="week_n_day", month=255, week=6, weekday=1
    )
    assert decoded[4].period == BACnetSpecialEventPeriod(kind="unknown")


def test_decode_object_references() -> None:
    # given
    refs = [
        DeviceObjectPropertyReference(
            objectIdentifier=ObjectIdentifier("binary-output,3"),
            propertyIdentifier=PropertyIdentifier("present-value"),
        ),
        DeviceObjectPropertyReference(
            objectIdentifier=ObjectIdentifier("analog-value,7"),
            propertyIdentifier=PropertyIdentifier("priority-array"),
            propertyArrayIndex=8,
            deviceIdentifier=ObjectIdentifier("device,99"),
        ),
    ]

    # when
    decoded = schedule_read.decode_object_references(refs)

    # then
    assert decoded == [
        BACnetObjectPropertyReference(
            object_identifier=BACnetObjectIdentifier("binaryOutput", 3),
            property_name="presentValue",
        ),
        BACnetObjectPropertyReference(
            object_identifier=BACnetObjectIdentifier("analogValue", 7),
            property_name="priorityArray",
            array_index=8,
            device_id=99,
        ),
    ]


# --- reading -----------------------------------------------------------------


def test_read_schedule_decodes_every_property() -> None:
    # given
    device = FakeDevice(_occupancy_schedule())

    # when
    schedule = _read(device)

    # then
    assert schedule.device_address == ADDRESS
    assert schedule.instance == 0
    assert schedule.name == "occupancyschedule"
    assert schedule.present_value is False
    assert schedule.schedule_default is False
    assert schedule.effective_period == BACnetDateRange(None, None)
    assert schedule.weekly_schedule[0].entries[1].value is None
    assert schedule.exception_schedule == []
    assert schedule.controlled_points[0].object_identifier == (
        BACnetObjectIdentifier("binaryValue", 1)
    )
    assert schedule.missing_properties == {}


def test_read_schedule_null_default_is_none() -> None:
    # given
    device = FakeDevice(_occupancy_schedule(scheduleDefault=AnyAtomic(Null(()))))

    # when
    schedule = _read(device)

    # then
    assert schedule.schedule_default is None
    assert "scheduleDefault" not in schedule.missing_properties


def test_read_schedule_lists_properties_that_fail_with_reason() -> None:
    # given
    props = _occupancy_schedule()
    del props["exceptionSchedule"]
    props["weeklySchedule"] = object()  # can't be decoded
    device = FakeDevice(props, failures={"effectivePeriod": "access_denied"})

    # when
    schedule = _read(device)

    # then
    assert schedule.weekly_schedule == []
    assert schedule.exception_schedule == []
    assert schedule.missing_properties == {
        "effectivePeriod": "access_denied",
        "weeklySchedule": "decode_error",
        "exceptionSchedule": "unknown_property",
    }
    assert schedule.name == "occupancyschedule"


@pytest.mark.parametrize("failure", ["no_response", "unknown_object"])
def test_read_schedule_reports_why_there_is_no_schedule(failure) -> None:
    # given
    device = FakeDevice(_occupancy_schedule(), failures={"presentValue": failure})

    # when
    result = asyncio.run(device.read_schedule(ADDRESS, 0))

    # then
    assert result.data is None
    assert result.failure == failure
    assert result.error is not None
    assert device.reads == ["presentValue"]


def test_read_schedule_continues_when_present_value_is_denied() -> None:
    # given
    device = FakeDevice(
        _occupancy_schedule(), failures={"presentValue": "access_denied"}
    )

    # when
    schedule = _read(device)

    # then
    assert schedule.present_value is None
    assert schedule.missing_properties == {"presentValue": "access_denied"}
    assert schedule.weekly_schedule[0].entries[0].value is True


def test_read_schedule_stops_reading_once_device_goes_silent() -> None:
    # given
    device = FakeDevice(_occupancy_schedule(), failures={"objectName": "no_response"})

    # when
    schedule = _read(device)

    # then
    assert device.reads == ["presentValue", "objectName"]
    assert schedule.present_value is False
    assert set(schedule.missing_properties.values()) == {"no_response"}
    assert len(schedule.missing_properties) == 6


def test_to_dict_keeps_release_and_any_date() -> None:
    # given
    schedule = _read(
        FakeDevice(_occupancy_schedule(scheduleDefault=AnyAtomic(Null(()))))
    )

    # when
    data = to_dict(schedule)

    # then
    assert data["schedule_default"] is None
    assert data["effective_period"] == {"start": None, "end": None}
    assert data["weekly_schedule"][0]["entries"][1] == {"time": "12:00", "value": None}
    assert data["weekly_schedule"][2] == {"day": "Wednesday", "entries": []}
