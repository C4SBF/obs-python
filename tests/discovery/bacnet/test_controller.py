from __future__ import annotations

import asyncio
import socket
import sys
import types
from unittest.mock import AsyncMock, Mock

import obs.discovery.bacnet.controller as controller_module
from obs.discovery.bacnet.controller import BACnetController
from obs.discovery.bacnet.types import BACnetObjectIdentifier
from tests.discovery.bacnet.factories import FakeWhoIsResponse


def test_initialize_returns_true_when_already_initialized() -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")
    controller._initialized = True
    controller.bacnet = object()

    # when
    result = asyncio.run(controller.initialize())

    # then
    assert result is True


def test_initialize_success_with_mocked_bac0(monkeypatch) -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24", bbmd_ip="10.0.0.1")
    fake_bac0 = types.SimpleNamespace(
        log_level=Mock(),
        lite=Mock(return_value=object()),
    )
    monkeypatch.setitem(sys.modules, "BAC0", fake_bac0)
    monkeypatch.setattr(
        controller_module.asyncio, "sleep", AsyncMock(return_value=None)
    )

    # when
    result = asyncio.run(controller.initialize())

    # then
    assert result is True
    assert controller._initialized is True
    assert controller.bacnet is not None


def test_initialize_returns_false_on_error(monkeypatch) -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")
    monkeypatch.setitem(sys.modules, "BAC0", object())

    # when
    result = asyncio.run(controller.initialize())

    # then
    assert result is False


def test_auto_detect_ip_success(monkeypatch) -> None:
    # given
    fake_socket = Mock()
    fake_socket.getsockname.return_value = ("10.20.30.40", 1234)
    fake_socket.__enter__ = Mock(return_value=fake_socket)
    fake_socket.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(socket, "socket", Mock(return_value=fake_socket))

    # when
    ip = BACnetController._auto_detect_ip()

    # then
    assert ip == "10.20.30.40/24"


def test_auto_detect_ip_fallback(monkeypatch) -> None:
    # given
    monkeypatch.setattr(socket, "socket", Mock(side_effect=OSError("no net")))

    # when
    ip = BACnetController._auto_detect_ip()

    # then
    assert ip == "0.0.0.0/24"


def test_build_uid_helpers() -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")

    # when
    dev_uid = controller._build_device_uid("1.2.3.4", 77)
    obj_uid = controller._build_object_uid("1.2.3.4", 77, "analogInput", 3)

    # then
    assert dev_uid == "bacnet://1.2.3.4/77"
    assert obj_uid == "bacnet://1.2.3.4/77/analogInput:3"


def test_parse_object_list_ignores_invalid_entries(
    initialized_controller: BACnetController,
) -> None:
    # given
    raw = [("analogInput", 1), ("binaryInput", "2"), ("bad",), object()]

    # when
    parsed = initialized_controller._parse_object_list(raw)

    # then
    assert parsed == [
        BACnetObjectIdentifier(object_type="analogInput", instance=1),
        BACnetObjectIdentifier(object_type="binaryInput", instance=2),
    ]


def test_normalize_object_type() -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")

    # when
    normalized = controller._normalize_object_type("analog-input")

    # then
    assert normalized == "analogInput"


def test_to_native_and_unit_id() -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")

    # when
    native_bool = controller._to_native(True)
    native_float = controller._to_native(3.2)
    native_int = controller._to_native(5)
    native_str = controller._to_native(object())
    from_enum = controller._unit_id(type("EnumLike", (), {"value": 48})())
    from_number = controller._unit_id(62)

    # then
    assert native_bool is True
    assert native_float == 3.2
    assert native_int == 5
    assert isinstance(native_str, str)
    assert from_enum == "48"
    assert from_number == "62"


def test_read_multiple_success(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    bacnet_mock.readMultiple.return_value = {"device:1": {"objectName": "d1"}}

    # when
    result = asyncio.run(
        initialized_controller.read_multiple(
            "1.2.3.4",
            {"device:1": ["objectName"]},
        )
    )

    # then
    assert result == {"device:1": {"objectName": "d1"}}


def test_read_multiple_returns_none_on_exception(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    bacnet_mock.readMultiple.side_effect = RuntimeError("rpm unsupported")

    # when
    result = asyncio.run(
        initialized_controller.read_multiple("1.2.3.4", {"device:1": ["objectName"]})
    )

    # then
    assert result is None


def test_read_multiple_returns_none_for_non_dict_result(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    bacnet_mock.readMultiple.return_value = ["not-a-dict"]

    # when
    result = asyncio.run(
        initialized_controller.read_multiple("1.2.3.4", {"device:1": ["objectName"]})
    )

    # then
    assert result is None


def test_read_device_census_prefers_rpm(
    initialized_controller: BACnetController, monkeypatch
) -> None:
    # given
    rpm_result = {
        "device:1001": {
            "objectName": "VAV-1",
            "vendorName": "Acme",
            "objectList": [("analogInput", 1)],
        }
    }
    monkeypatch.setattr(
        initialized_controller, "read_multiple", AsyncMock(return_value=rpm_result)
    )

    # when
    device = asyncio.run(initialized_controller.read_device_census("1.2.3.4", 1001))

    # then
    assert device.uid == "bacnet://1.2.3.4/1001"
    assert device.name == "VAV-1"
    assert device.vendor == "Acme"
    assert device.object_list == [
        BACnetObjectIdentifier(object_type="analogInput", instance=1)
    ]


def test_read_device_census_falls_back_to_individual_reads(
    initialized_controller: BACnetController, bacnet_mock: Mock, monkeypatch
) -> None:
    # given
    monkeypatch.setattr(
        initialized_controller, "read_multiple", AsyncMock(return_value=None)
    )
    bacnet_mock.read = AsyncMock(
        side_effect=["DeviceName", "Vendor", "Model-X", "1.2.3", [("binaryInput", 3)]]
    )

    # when
    device = asyncio.run(initialized_controller.read_device_census("1.2.3.4", 12))

    # then
    assert device.name == "DeviceName"
    assert device.vendor == "Vendor"
    assert device.object_list == [
        BACnetObjectIdentifier(object_type="binaryInput", instance=3)
    ]


def test_read_device_census_handles_bad_rpm_shape_and_falls_back(
    initialized_controller: BACnetController, bacnet_mock: Mock, monkeypatch
) -> None:
    # given
    monkeypatch.setattr(
        initialized_controller,
        "read_multiple",
        AsyncMock(return_value={"device:9": "invalid"}),
    )
    bacnet_mock.read = AsyncMock(side_effect=["n", "v", "m", "f", [("analogInput", 2)]])

    # when
    device = asyncio.run(initialized_controller.read_device_census("1.2.3.4", 9))

    # then
    assert device.name == "n"
    assert device.vendor == "v"
    assert device.object_list == [
        BACnetObjectIdentifier(object_type="analogInput", instance=2)
    ]


def test_scan_network_reads_and_filters_devices(
    initialized_controller: BACnetController, bacnet_mock: Mock, monkeypatch
) -> None:
    # given
    responses = [
        FakeWhoIsResponse(device_id=9999, source="192.168.1.2"),
        FakeWhoIsResponse(device_id=1001, source="192.168.1.10"),
        FakeWhoIsResponse(device_id=1002, source="192.168.1.11"),
    ]
    bacnet_mock.who_is.return_value = responses

    async def _fake_census(addr: str, did: int):
        return controller_module.BACnetDevice(
            uid=f"bacnet://{addr}/{did}",
            identifier=controller_module.BACnetDeviceIdentifier(
                address=addr, device_id=did
            ),
            name=f"dev-{did}",
        )

    monkeypatch.setattr(initialized_controller, "read_device_census", _fake_census)

    # when
    devices = asyncio.run(initialized_controller.scan_network())

    # then
    assert [d.identifier.device_id for d in devices] == [1001, 1002]


def test_scan_network_raises_when_not_initialized_and_no_bacnet(monkeypatch) -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")
    controller._initialized = False
    controller.bacnet = None
    monkeypatch.setattr(controller, "initialize", AsyncMock(return_value=True))

    # when / then
    try:
        asyncio.run(controller.scan_network())
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "not initialized" in str(exc)


def test_scan_network_returns_empty_on_exception(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    bacnet_mock.who_is.side_effect = RuntimeError("who-is failed")

    # when
    result = asyncio.run(initialized_controller.scan_network())

    # then
    assert result == []


def test_scan_device_objects_with_object_list(
    initialized_controller: BACnetController, monkeypatch
) -> None:
    # given
    objects = [
        ("analogInput", 1),
        ("binaryOutput", 2),
    ]
    discovered = [
        controller_module.BACnetObject(
            uid="bacnet://1.2.3.4/10/analogInput:1",
            device=controller_module.BACnetDeviceIdentifier(
                address="1.2.3.4", device_id=10
            ),
            object_identifier=controller_module.BACnetObjectIdentifier(
                object_type="analogInput", instance=1
            ),
        )
    ]
    monkeypatch.setattr(
        initialized_controller, "read_objects_rpm", AsyncMock(return_value=discovered)
    )

    # when
    result = asyncio.run(
        initialized_controller.scan_device_objects(
            "1.2.3.4",
            10,
            object_list=[
                controller_module.BACnetObjectIdentifier(
                    object_type=o[0], instance=o[1]
                )
                for o in objects
            ],
        )
    )

    # then
    assert result == discovered


def test_scan_device_objects_initializes_when_needed(monkeypatch) -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")
    controller.bacnet = Mock()
    controller._initialized = False
    monkeypatch.setattr(controller, "initialize", AsyncMock(return_value=True))
    monkeypatch.setattr(
        controller, "_scan_device_objects_locked", AsyncMock(return_value=[])
    )

    # when
    result = asyncio.run(controller.scan_device_objects("1.2.3.4", 10))

    # then
    assert result == []
    controller.initialize.assert_awaited_once()  # type: ignore[attr-defined]


def test_scan_device_objects_raises_when_bacnet_missing(monkeypatch) -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")
    controller._initialized = False
    controller.bacnet = None
    monkeypatch.setattr(controller, "initialize", AsyncMock(return_value=True))

    # when / then
    try:
        asyncio.run(controller.scan_device_objects("1.2.3.4", 10))
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "not initialized" in str(exc)


def test_scan_device_objects_locked_uses_instance_fallback(
    initialized_controller: BACnetController, bacnet_mock: Mock, monkeypatch
) -> None:
    # given
    bacnet_mock.read.side_effect = RuntimeError("no objectList")
    discovered = [
        controller_module.BACnetObject(
            uid="bacnet://1.2.3.4/10/analogValue:1",
            device=controller_module.BACnetDeviceIdentifier(
                address="1.2.3.4", device_id=10
            ),
            object_identifier=controller_module.BACnetObjectIdentifier(
                object_type="analogValue", instance=1
            ),
        )
    ]
    read_objects_rpm = AsyncMock(return_value=discovered)
    monkeypatch.setattr(initialized_controller, "read_objects_rpm", read_objects_rpm)

    # when
    result = asyncio.run(
        initialized_controller._scan_device_objects_locked(
            "1.2.3.4",
            10,
            max_instance=1,
            object_list=None,
            rpm_batch_size=3,
        )
    )

    # then
    assert result == discovered
    assert read_objects_rpm.await_args is not None
    assert read_objects_rpm.await_args.kwargs["batch_size"] == 3
    assert len(read_objects_rpm.await_args.args[2]) == 6


def test_scan_device_objects_locked_returns_empty_on_error(
    initialized_controller: BACnetController, monkeypatch
) -> None:
    # given
    monkeypatch.setattr(
        initialized_controller,
        "read_objects_rpm",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    # when
    result = asyncio.run(
        initialized_controller._scan_device_objects_locked(
            "1.2.3.4",
            10,
            max_instance=1,
            object_list=[BACnetObjectIdentifier(object_type="analogInput", instance=1)],
            rpm_batch_size=2,
        )
    )

    # then
    assert result == []


def test_read_objects_rpm_falls_back_to_single_reads(
    initialized_controller: BACnetController, monkeypatch
) -> None:
    # given
    monkeypatch.setattr(
        initialized_controller, "read_multiple", AsyncMock(return_value=None)
    )

    async def _fake_read_single(device_address, device_id, object_type, instance):
        return controller_module.BACnetObject(
            uid=f"bacnet://{device_address}/{device_id}/{object_type}:{instance}",
            device=controller_module.BACnetDeviceIdentifier(
                address=device_address, device_id=device_id
            ),
            object_identifier=controller_module.BACnetObjectIdentifier(
                object_type=object_type,
                instance=instance,
            ),
        )

    monkeypatch.setattr(
        initialized_controller, "_read_bacnet_object_unlocked", _fake_read_single
    )

    # when
    result = asyncio.run(
        initialized_controller.read_objects_rpm(
            "1.2.3.4",
            10,
            [("analogInput", 1)],
            batch_size=1,
        )
    )

    # then
    assert len(result) == 1
    assert result[0] is not None


def test_read_objects_rpm_returns_empty_for_no_objects(
    initialized_controller: BACnetController,
) -> None:
    # given / when
    result = asyncio.run(initialized_controller.read_objects_rpm("1.2.3.4", 10, []))

    # then
    assert result == []


def test_read_objects_rpm_reduces_batch_size_and_parses_normalized_keys(
    initialized_controller: BACnetController, monkeypatch
) -> None:
    # given
    call_count = {"n": 0}

    async def _fake_read_multiple(device_address, rpm_objects):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        key = next(iter(rpm_objects.keys()))
        return {
            key.replace("analogInput", "analog-input"): {
                "objectName": "p",
                "presentValue": 1.0,
                "description": "d",
                "units": "volts",
            }
        }

    monkeypatch.setattr(initialized_controller, "read_multiple", _fake_read_multiple)

    # when
    result = asyncio.run(
        initialized_controller.read_objects_rpm(
            "1.2.3.4",
            10,
            [("analogInput", 1), ("analogInput", 2)],
            batch_size=2,
        )
    )

    # then
    assert len(result) == 2
    assert result[0] is not None
    assert result[1] is not None


def test_build_object_from_props_for_binary_has_no_units(
    initialized_controller: BACnetController,
) -> None:
    # given
    props = {"objectName": "BI1", "presentValue": True, "description": "Binary"}

    # when
    obj = initialized_controller._build_object_from_props(
        device_address="1.2.3.4",
        device_id=10,
        object_type="binaryInput",
        instance=1,
        props=props,
    )

    # then
    assert obj.units is None
    assert obj.value is True


def test_read_bacnet_object_unlocked_returns_none_when_name_missing(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    bacnet_mock.read = AsyncMock(return_value=None)

    # when
    result = asyncio.run(
        initialized_controller._read_bacnet_object_unlocked(
            "1.2.3.4",
            8,
            "analogInput",
            1,
        )
    )

    # then
    assert result is None


def test_read_bacnet_object_unlocked_handles_partial_read_failures(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    bacnet_mock.read = AsyncMock(
        side_effect=["Temp", RuntimeError("value"), "Desc", 62]
    )

    # when
    result = asyncio.run(
        initialized_controller._read_bacnet_object_unlocked(
            "1.2.3.4", 8, "analogInput", 1
        )
    )

    # then
    assert result is not None
    assert result.name == "Temp"
    assert result.value is None
    assert result.units == "62"
    assert result.unit_id == "62"


def test_read_bacnet_object_unlocked_returns_none_on_name_read_exception(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    bacnet_mock.read = AsyncMock(side_effect=RuntimeError("read failed"))

    # when
    result = asyncio.run(
        initialized_controller._read_bacnet_object_unlocked(
            "1.2.3.4", 8, "analogInput", 1
        )
    )

    # then
    assert result is None


def test_unit_id_handles_value_attribute_and_unknown_values() -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")

    class EnumLike:
        value = 48

    # when
    unit_from_enum = controller._unit_id(EnumLike())
    unit_from_unknown_int = controller._unit_id(999)
    unit_from_other_obj = controller._unit_id(object())

    # then
    assert unit_from_enum == "48"
    assert unit_from_unknown_int == "999"
    assert isinstance(unit_from_other_obj, str)


def test_get_bacnet_controller_is_keyed_singleton(monkeypatch) -> None:
    # given
    monkeypatch.setattr(controller_module, "_bacnet_controller", None)
    monkeypatch.setattr(controller_module, "_bacnet_controllers", {})

    # when
    first = controller_module.get_bacnet_controller(client_ip="1.1.1.1/24")
    second = controller_module.get_bacnet_controller(client_ip="1.1.1.1/24")
    third = controller_module.get_bacnet_controller(client_ip="2.2.2.2/24")

    # then
    assert first is second
    assert first is not third


def test_clear_controller_cache_resets_cached_controller(monkeypatch) -> None:
    # given
    cached = BACnetController(client_ip="1.1.1.1/24")
    cached._initialized = True
    cached.bacnet = None
    monkeypatch.setattr(controller_module, "_bacnet_controller", cached)
    monkeypatch.setattr(controller_module, "_bacnet_controllers", {})

    # when
    controller_module.clear_controller_cache()

    # then
    assert controller_module._bacnet_controller is None


def test_clear_controller_cache_runs_cleanup_path(monkeypatch) -> None:
    # given
    cached = BACnetController(client_ip="1.1.1.1/24")
    cached._initialized = True
    cached.bacnet = Mock()
    cached.bacnet.disconnect = AsyncMock(side_effect=RuntimeError("disconnect failed"))
    monkeypatch.setattr(controller_module, "_bacnet_controller", cached)
    monkeypatch.setattr(controller_module, "_bacnet_controllers", {})

    import obs.discovery.bacnet._loop as loop_module

    fake_loop = Mock()
    fake_loop.is_closed.return_value = False
    monkeypatch.setattr(loop_module, "_loop", fake_loop)

    class FakeFuture:
        def result(self, timeout):
            raise RuntimeError("future failed")

    monkeypatch.setattr(
        controller_module.asyncio,
        "run_coroutine_threadsafe",
        lambda coro, loop: FakeFuture(),
    )

    # when
    controller_module.clear_controller_cache()

    # then
    assert controller_module._bacnet_controller is None


def test_initialize_returns_true_when_initialized_inside_lock_branch() -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")

    class InjectingLock:
        async def __aenter__(self):
            controller._initialized = True
            controller.bacnet = object()
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    controller._init_lock = InjectingLock()  # type: ignore[assignment]

    # when
    result = asyncio.run(controller.initialize())

    # then
    assert result is True


def test_initialize_success_without_bbmd_hits_default_lite(monkeypatch) -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")
    fake_bac0 = types.SimpleNamespace(
        log_level=Mock(), lite=Mock(return_value=object())
    )
    monkeypatch.setitem(sys.modules, "BAC0", fake_bac0)
    monkeypatch.setattr(
        controller_module.asyncio, "sleep", AsyncMock(return_value=None)
    )

    # when
    result = asyncio.run(controller.initialize())

    # then
    assert result is True
    assert "bbmdAddress" not in fake_bac0.lite.call_args.kwargs


def test_scan_network_returns_empty_for_no_responses_branch(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    bacnet_mock.who_is.return_value = []

    # when
    result = asyncio.run(initialized_controller.scan_network())

    # then
    assert result == []


def test_scan_network_handles_own_device_lookup_exception_branch(
    initialized_controller: BACnetController, bacnet_mock: Mock, monkeypatch
) -> None:
    # given
    bacnet_mock.localDevice = object()
    bacnet_mock.who_is.return_value = [
        FakeWhoIsResponse(device_id=1001, source="1.2.3.4")
    ]

    async def _fake_census(addr: str, did: int):
        return controller_module.BACnetDevice(
            uid=f"bacnet://{addr}/{did}",
            identifier=controller_module.BACnetDeviceIdentifier(
                address=addr, device_id=did
            ),
        )

    monkeypatch.setattr(initialized_controller, "read_device_census", _fake_census)

    # when
    result = asyncio.run(initialized_controller.scan_network())

    # then
    assert len(result) == 1


def test_scan_network_skips_malformed_whois_response_branch(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    class BadResponse:
        iAmDeviceIdentifier = ("device", "x")
        pduSource = "1.2.3.4"

    bacnet_mock.who_is.return_value = [BadResponse()]

    # when
    result = asyncio.run(initialized_controller.scan_network())

    # then
    assert result == []


def test_scan_network_filters_census_exceptions_branch(
    initialized_controller: BACnetController, bacnet_mock: Mock, monkeypatch
) -> None:
    # given
    bacnet_mock.who_is.return_value = [
        FakeWhoIsResponse(device_id=1001, source="1.2.3.4")
    ]

    async def _boom(addr: str, did: int):
        raise RuntimeError("boom")

    monkeypatch.setattr(initialized_controller, "read_device_census", _boom)

    # when
    result = asyncio.run(initialized_controller.scan_network())

    # then
    assert result == []


def test_read_device_census_raises_when_bacnet_none_branch() -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")
    controller.bacnet = None

    # when / then
    try:
        asyncio.run(controller.read_device_census("1.2.3.4", 7))
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "not initialized" in str(exc)


def test_read_device_census_missing_devkey_fallback_branches(
    initialized_controller: BACnetController, bacnet_mock: Mock, monkeypatch
) -> None:
    # given
    monkeypatch.setattr(
        initialized_controller,
        "read_multiple",
        AsyncMock(return_value={"device:999": {}}),
    )
    bacnet_mock.read = AsyncMock(
        side_effect=[
            RuntimeError("name"),
            RuntimeError("vendor"),
            RuntimeError("model"),
            RuntimeError("firmware"),
            RuntimeError("obj"),
        ]
    )

    # when
    result = asyncio.run(initialized_controller.read_device_census("1.2.3.4", 9))

    # then
    assert result.name is None
    assert result.vendor is None
    assert result.object_list == []


def test_read_multiple_raises_when_bacnet_none_branch() -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")
    controller.bacnet = None

    # when / then
    try:
        asyncio.run(controller.read_multiple("1.2.3.4", {"device:1": ["objectName"]}))
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "not initialized" in str(exc)


def test_read_multiple_special_error_name_info_branch(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    SegmentationNotSupported = type("SegmentationNotSupported", (Exception,), {})
    bacnet_mock.readMultiple.side_effect = SegmentationNotSupported("unsupported")

    # when
    result = asyncio.run(
        initialized_controller.read_multiple("1.2.3.4", {"device:1": ["objectName"]})
    )

    # then
    assert result is None


def test_parse_object_list_conversion_exception_branch(
    initialized_controller: BACnetController,
) -> None:
    # given
    raw = [("analogInput", "bad"), ("binaryInput", 2)]

    # when
    parsed = initialized_controller._parse_object_list(raw)

    # then
    assert parsed == [BACnetObjectIdentifier(object_type="binaryInput", instance=2)]


def test_scan_device_objects_locked_reads_object_list_success_branch(
    initialized_controller: BACnetController, bacnet_mock: Mock, monkeypatch
) -> None:
    # given
    bacnet_mock.read = AsyncMock(return_value=[("analog-input", 1), ("binaryInput", 2)])
    read_rpm = AsyncMock(return_value=[])
    monkeypatch.setattr(initialized_controller, "read_objects_rpm", read_rpm)

    # when
    result = asyncio.run(
        initialized_controller._scan_device_objects_locked(
            "1.2.3.4",
            10,
            max_instance=3,
            object_list=None,
            rpm_batch_size=4,
        )
    )

    # then
    assert result == []
    assert read_rpm.await_args is not None
    scanned = read_rpm.await_args.args[2]
    assert ("analogInput", 1) in scanned
    assert ("binaryInput", 2) in scanned


def test_read_objects_rpm_non_dict_and_missing_key_branches(
    initialized_controller: BACnetController, monkeypatch
) -> None:
    # given
    monkeypatch.setattr(
        initialized_controller,
        "read_multiple",
        AsyncMock(return_value={"analogInput": "not-dict"}),
    )
    monkeypatch.setattr(
        initialized_controller,
        "_read_bacnet_object_unlocked",
        AsyncMock(return_value=None),
    )

    # when
    result = asyncio.run(
        initialized_controller.read_objects_rpm(
            "1.2.3.4", 10, [("analogInput", 1)], batch_size=1
        )
    )

    # then
    assert result == [None]


def test_read_bacnet_object_raises_when_bacnet_none_branch() -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")
    controller.bacnet = None

    # when / then
    try:
        asyncio.run(
            controller._read_bacnet_object_unlocked("1.2.3.4", 10, "analogInput", 1)
        )
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "not initialized" in str(exc)


def test_read_bacnet_object_description_failure_branch(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    bacnet_mock.read = AsyncMock(
        side_effect=["n", 1.0, RuntimeError("desc"), RuntimeError("units")]
    )

    # when
    result = asyncio.run(
        initialized_controller._read_bacnet_object_unlocked(
            "1.2.3.4", 10, "analogInput", 1
        )
    )

    # then
    assert result is not None
    assert result.description is None
    assert result.units is None


def test_read_bacnet_object_non_analog_skips_units_branch(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    bacnet_mock.read = AsyncMock(side_effect=["bin", True, RuntimeError("desc")])

    # when
    result = asyncio.run(
        initialized_controller._read_bacnet_object_unlocked(
            "1.2.3.4", 10, "binaryInput", 1
        )
    )

    # then
    assert result is not None
    assert result.units is None


def test_unit_id_none_branch() -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")

    # when
    result = controller._unit_id(None)

    # then
    assert result is None


def test_clear_controller_cache_when_none_branch(monkeypatch) -> None:
    # given
    monkeypatch.setattr(controller_module, "_bacnet_controller", None)
    monkeypatch.setattr(controller_module, "_bacnet_controllers", {})

    # when
    controller_module.clear_controller_cache()

    # then
    assert controller_module._bacnet_controller is None


def test_clear_controller_cache_closed_loop_branch(monkeypatch) -> None:
    # given
    cached = BACnetController(client_ip="1.1.1.1/24")
    cached._initialized = True
    cached.bacnet = Mock()
    cached.bacnet.disconnect = AsyncMock(return_value=None)
    monkeypatch.setattr(controller_module, "_bacnet_controller", cached)
    monkeypatch.setattr(controller_module, "_bacnet_controllers", {})

    import obs.discovery.bacnet._loop as loop_module

    fake_loop = Mock()
    fake_loop.is_closed.return_value = True
    monkeypatch.setattr(loop_module, "_loop", fake_loop)

    # when
    controller_module.clear_controller_cache()

    # then
    assert controller_module._bacnet_controller is None


def test_clear_controller_cache_cleanup_inner_disconnect_error_branch(
    monkeypatch,
) -> None:
    # given
    cached = BACnetController(client_ip="1.1.1.1/24")
    cached._initialized = True
    cached.bacnet = Mock()
    cached.bacnet.disconnect = AsyncMock(side_effect=RuntimeError("disconnect"))
    monkeypatch.setattr(controller_module, "_bacnet_controller", cached)
    monkeypatch.setattr(controller_module, "_bacnet_controllers", {})

    import obs.discovery.bacnet._loop as loop_module

    fake_loop = Mock()
    fake_loop.is_closed.return_value = False
    monkeypatch.setattr(loop_module, "_loop", fake_loop)

    class _DoneFuture:
        def result(self, timeout):
            return None

    def _run_coroutine_threadsafe(coro, loop):
        asyncio.run(coro)
        return _DoneFuture()

    monkeypatch.setattr(
        controller_module.asyncio, "run_coroutine_threadsafe", _run_coroutine_threadsafe
    )

    # when
    controller_module.clear_controller_cache()

    # then
    assert controller_module._bacnet_controller is None


def test_clear_controller_cache_outer_exception_branch(monkeypatch) -> None:
    # given
    class ExplodingController:
        def __bool__(self):
            return True

        def __getattribute__(self, name):
            if name == "__class__":
                return object
            raise RuntimeError("explode")

    monkeypatch.setattr(controller_module, "_bacnet_controller", ExplodingController())
    monkeypatch.setattr(controller_module, "_bacnet_controllers", {})

    # when
    controller_module.clear_controller_cache()

    # then
    assert controller_module._bacnet_controller is None


# --- ReadMixin tests ---


def test_read_point_success(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    bacnet_mock.read = AsyncMock(side_effect=[72.5, "Zone Temp", 62])

    # when
    result = asyncio.run(
        initialized_controller.read_point(
            "192.168.1.10", 1001, "analogValue", 1, timeout=5.0
        )
    )

    # then
    assert result is not None
    assert result.value == 72.5
    assert result.name == "Zone Temp"
    assert result.units == "62"
    assert result.object_identifier.object_type == "analogValue"
    assert result.object_identifier.instance == 1
    assert result.metadata == {"source": "read_point"}


def test_read_point_initializes_when_needed(monkeypatch) -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")
    controller.bacnet = Mock()
    controller.bacnet.read = AsyncMock(side_effect=[42.0, "Name", 62])
    controller._initialized = False
    monkeypatch.setattr(controller, "initialize", AsyncMock(return_value=True))

    # when
    result = asyncio.run(controller.read_point("1.2.3.4", 10, "analogInput", 1))

    # then
    assert result is not None
    controller.initialize.assert_awaited_once()


def test_read_point_raises_when_bacnet_none(monkeypatch) -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")
    controller._initialized = False
    controller.bacnet = None
    monkeypatch.setattr(controller, "initialize", AsyncMock(return_value=True))

    # when / then
    try:
        asyncio.run(controller.read_point("1.2.3.4", 10, "analogInput", 1))
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "not initialized" in str(exc)


def test_read_point_unlocked_returns_none_on_error(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    bacnet_mock.read = AsyncMock(side_effect=RuntimeError("read failed"))

    # when
    result = asyncio.run(
        initialized_controller._read_point_unlocked(
            "192.168.1.10", 1001, "analogValue", 1
        )
    )

    # then
    assert result is None


def test_read_point_unlocked_handles_optional_property_failures(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    # presentValue succeeds, name fails, units fails
    bacnet_mock.read = AsyncMock(
        side_effect=[55.0, RuntimeError("no name"), RuntimeError("no units")]
    )

    # when
    result = asyncio.run(
        initialized_controller._read_point_unlocked(
            "192.168.1.10", 1001, "analogValue", 1
        )
    )

    # then
    assert result is not None
    assert result.value == 55.0
    assert result.name is None
    assert result.units is None


def test_read_point_unlocked_skips_units_for_binary(
    initialized_controller: BACnetController, bacnet_mock: Mock
) -> None:
    # given
    bacnet_mock.read = AsyncMock(side_effect=[True, "Binary Point"])

    # when
    result = asyncio.run(
        initialized_controller._read_point_unlocked(
            "192.168.1.10", 1001, "binaryInput", 1
        )
    )

    # then
    assert result is not None
    assert result.value is True
    assert result.units is None
    # Only 2 reads: presentValue and objectName (no units for binary)
    assert bacnet_mock.read.await_count == 2


def test_read_points_with_rpm_success(
    initialized_controller: BACnetController, monkeypatch
) -> None:
    # given
    rpm_result = {
        "analogValue:1": {
            "presentValue": 72.5,
            "objectName": "Zone Temp",
            "units": 62,
        },
        "analogValue:2": {
            "presentValue": 45.0,
            "objectName": "Setpoint",
            "units": 62,
        },
    }
    monkeypatch.setattr(
        initialized_controller, "read_multiple", AsyncMock(return_value=rpm_result)
    )

    # when
    result = asyncio.run(
        initialized_controller.read_points(
            "192.168.1.10", 1001, [("analogValue", 1), ("analogValue", 2)]
        )
    )

    # then
    assert len(result) == 2
    assert result[0] is not None
    assert result[0].value == 72.5
    assert result[0].name == "Zone Temp"
    assert result[0].metadata == {"source": "rpm_read"}
    assert result[1] is not None
    assert result[1].value == 45.0


def test_read_points_falls_back_to_individual_on_rpm_failure(
    initialized_controller: BACnetController, monkeypatch, bacnet_mock: Mock
) -> None:
    # given
    monkeypatch.setattr(
        initialized_controller, "read_multiple", AsyncMock(return_value=None)
    )
    # _read_point_unlocked reads: presentValue, objectName, units
    bacnet_mock.read = AsyncMock(side_effect=[72.5, "Zone Temp", 62])

    # when
    result = asyncio.run(
        initialized_controller.read_points("192.168.1.10", 1001, [("analogValue", 1)])
    )

    # then
    assert len(result) == 1
    assert result[0] is not None
    assert result[0].value == 72.5


def test_read_points_falls_back_for_missing_rpm_keys(
    initialized_controller: BACnetController, monkeypatch, bacnet_mock: Mock
) -> None:
    # given
    # RPM returns only one point, other is missing
    rpm_result = {
        "analogValue:1": {
            "presentValue": 72.5,
            "objectName": "Zone Temp",
            "units": 62,
        },
    }
    monkeypatch.setattr(
        initialized_controller, "read_multiple", AsyncMock(return_value=rpm_result)
    )
    bacnet_mock.read = AsyncMock(side_effect=[45.0, "Setpoint", 62])

    # when
    result = asyncio.run(
        initialized_controller.read_points(
            "192.168.1.10", 1001, [("analogValue", 1), ("analogValue", 2)]
        )
    )

    # then
    assert len(result) == 2
    assert result[0] is not None
    assert result[0].value == 72.5
    assert result[1] is not None
    assert result[1].value == 45.0  # From fallback


def test_read_points_returns_empty_for_empty_input(
    initialized_controller: BACnetController,
) -> None:
    # given / when
    result = asyncio.run(initialized_controller.read_points("192.168.1.10", 1001, []))

    # then
    assert result == []


def test_read_points_initializes_when_needed(monkeypatch) -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")
    controller.bacnet = Mock()
    controller._initialized = False
    monkeypatch.setattr(controller, "initialize", AsyncMock(return_value=True))
    monkeypatch.setattr(
        controller, "read_multiple", AsyncMock(return_value={"analogValue:1": {}})
    )

    # when
    result = asyncio.run(controller.read_points("1.2.3.4", 10, [("analogValue", 1)]))

    # then
    assert len(result) == 1
    controller.initialize.assert_awaited_once()


def test_read_points_raises_when_bacnet_none(monkeypatch) -> None:
    # given
    controller = BACnetController(client_ip="1.1.1.1/24")
    controller._initialized = False
    controller.bacnet = None
    monkeypatch.setattr(controller, "initialize", AsyncMock(return_value=True))

    # when / then
    try:
        asyncio.run(controller.read_points("1.2.3.4", 10, [("analogValue", 1)]))
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "not initialized" in str(exc)


def test_read_points_handles_normalized_rpm_keys(
    initialized_controller: BACnetController, monkeypatch
) -> None:
    # given
    # RPM returns with hyphenated key format
    rpm_result = {
        "analog-value:1": {
            "presentValue": 72.5,
            "objectName": "Zone Temp",
            "units": 62,
        },
    }
    monkeypatch.setattr(
        initialized_controller, "read_multiple", AsyncMock(return_value=rpm_result)
    )

    # when
    result = asyncio.run(
        initialized_controller.read_points("192.168.1.10", 1001, [("analogValue", 1)])
    )

    # then
    assert len(result) == 1
    assert result[0] is not None
    assert result[0].value == 72.5


def test_build_read_result(initialized_controller: BACnetController) -> None:
    # given
    props = {
        "presentValue": 72.5,
        "objectName": "Zone Temp",
        "units": 62,
    }

    # when
    result = initialized_controller._build_read_result(
        device_address="192.168.1.10",
        device_id=1001,
        object_type="analogValue",
        instance=1,
        props=props,
    )

    # then
    assert result.uid == "bacnet://192.168.1.10/1001/analogValue:1"
    assert result.value == 72.5
    assert result.name == "Zone Temp"
    assert result.units == "62"
    assert result.unit_id == "62"
    assert result.device.address == "192.168.1.10"
    assert result.device.device_id == 1001
    assert result.object_identifier.object_type == "analogValue"
    assert result.object_identifier.instance == 1
    assert result.metadata == {"source": "rpm_read"}


def test_build_read_result_handles_none_values(
    initialized_controller: BACnetController,
) -> None:
    # given
    props = {"presentValue": None, "objectName": None, "units": None}

    # when
    result = initialized_controller._build_read_result(
        device_address="192.168.1.10",
        device_id=1001,
        object_type="binaryInput",
        instance=1,
        props=props,
    )

    # then
    assert result.value is None
    assert result.name is None
    assert result.units is None
    assert result.unit_id is None
