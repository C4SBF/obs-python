from __future__ import annotations

from obs.discovery.bacnet.types import (
    BACnetDevice,
    BACnetDeviceIdentifier,
    BACnetNetworkScanInput,
    BACnetNetworkScanResult,
    BACnetObject,
    BACnetObjectIdentifier,
    BACnetObjectsDiscoveryInput,
    BACnetObjectsDiscoveryResult,
    BACnetScanTimings,
)


def test_bacnet_device_defaults_are_typed_and_independent() -> None:
    # given
    identifier_a = BACnetDeviceIdentifier(address="1.1.1.1", device_id=10)
    identifier_b = BACnetDeviceIdentifier(address="1.1.1.2", device_id=11)

    # when
    device_a = BACnetDevice(uid="bacnet://1.1.1.1/10", identifier=identifier_a)
    device_b = BACnetDevice(uid="bacnet://1.1.1.2/11", identifier=identifier_b)
    device_a.object_list.append(
        BACnetObjectIdentifier(object_type="analogInput", instance=1)
    )

    # then
    assert device_b.object_list == []


def test_bacnet_object_defaults_are_typed_and_independent() -> None:
    # given
    dev = BACnetDeviceIdentifier(address="1.1.1.1", device_id=10)
    obj_id_a = BACnetObjectIdentifier(object_type="analogInput", instance=1)
    obj_id_b = BACnetObjectIdentifier(object_type="analogInput", instance=2)

    # when
    obj_a = BACnetObject(
        uid="bacnet://1.1.1.1/10/analogInput:1",
        device=dev,
        object_identifier=obj_id_a,
    )
    obj_b = BACnetObject(
        uid="bacnet://1.1.1.1/10/analogInput:2",
        device=dev,
        object_identifier=obj_id_b,
    )
    obj_a.unit_id = "62"
    obj_a.metadata["source"] = "rpm"

    # then
    assert obj_b.unit_id is None
    assert obj_b.metadata == {}


def test_network_result_wrapper_keeps_input_data_timings() -> None:
    # given
    timings = BACnetScanTimings(
        started_at_utc="2026-02-12T00:00:00+00:00",
        finished_at_utc="2026-02-12T00:00:01+00:00",
        duration_seconds=1.0,
    )
    scan_input = BACnetNetworkScanInput(timeout=10)

    # when
    result = BACnetNetworkScanResult(
        input=scan_input,
        data=[],
        timings=timings,
        success=True,
    )

    # then
    assert result.input.timeout == 10
    assert result.success is True
    assert result.timings.duration_seconds == 1.0


def test_objects_result_wrapper_keeps_input_data_timings() -> None:
    # given
    timings = BACnetScanTimings(
        started_at_utc="2026-02-12T00:00:00+00:00",
        finished_at_utc="2026-02-12T00:00:02+00:00",
        duration_seconds=2.0,
    )
    discover_input = BACnetObjectsDiscoveryInput(
        device=BACnetDeviceIdentifier(address="1.1.1.1", device_id=7),
    )

    # when
    result = BACnetObjectsDiscoveryResult(
        input=discover_input,
        data=[],
        timings=timings,
        success=False,
        error="timeout",
    )

    # then
    assert result.input.device.device_id == 7
    assert result.success is False
    assert result.error == "timeout"
