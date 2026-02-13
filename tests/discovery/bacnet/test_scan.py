from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from obs.discovery.bacnet import scan as scan_module
from obs.discovery.bacnet.types import BACnetDeviceIdentifier, BACnetObjectIdentifier
from tests.discovery.bacnet.factories import make_bacnet_device, make_bacnet_object


class StubController:
    def __init__(self, initialized: bool = False):
        self._initialized = initialized
        self.initialize = AsyncMock(return_value=True)
        self.scan_network = AsyncMock(return_value=[])
        self.scan_device_objects = AsyncMock(return_value=[])


def test_scan_bacnet_network_success(monkeypatch) -> None:
    # given
    controller = StubController(initialized=False)
    device = make_bacnet_device()
    controller.scan_network.return_value = [device]
    monkeypatch.setattr(scan_module, "get_bacnet_controller", lambda **_: controller)

    # when
    result = asyncio.run(scan_module.scan_bacnet_network(timeout=15))

    # then
    assert result.success is True
    assert result.error is None
    assert result.data == [device]
    assert result.input.timeout == 15
    controller.initialize.assert_awaited_once()


def test_scan_bacnet_network_error(monkeypatch) -> None:
    # given
    controller = StubController(initialized=True)
    controller.scan_network.side_effect = RuntimeError("boom")
    monkeypatch.setattr(scan_module, "get_bacnet_controller", lambda **_: controller)

    # when
    result = asyncio.run(scan_module.scan_bacnet_network())

    # then
    assert result.success is False
    assert result.data == []
    assert result.error == "boom"


def test_scan_bacnet_network_sync_uses_run_sync(monkeypatch) -> None:
    # given
    expected = object()

    def _fake_run_sync(coro, *, timeout):
        coro.close()
        assert timeout == 42
        return expected

    monkeypatch.setattr(scan_module, "run_sync", _fake_run_sync)

    # when
    result = scan_module.scan_bacnet_network_sync(timeout=12)

    # then
    assert result is expected


def test_discover_bacnet_objects_success(monkeypatch) -> None:
    # given
    controller = StubController(initialized=False)
    point = make_bacnet_object()
    object_list = [BACnetObjectIdentifier(object_type="analogInput", instance=1)]
    controller.scan_device_objects.return_value = [point]
    monkeypatch.setattr(scan_module, "get_bacnet_controller", lambda **_: controller)

    # when
    result = asyncio.run(
        scan_module.discover_bacnet_objects(
            "192.168.1.10",
            1001,
            object_list=object_list,
            rpm_batch_size=7,
        )
    )

    # then
    assert result.success is True
    assert result.data == [point]
    assert result.input.device == BACnetDeviceIdentifier(
        address="192.168.1.10",
        device_id=1001,
    )
    assert result.input.object_list == object_list
    controller.scan_device_objects.assert_awaited_once()


def test_discover_bacnet_objects_error(monkeypatch) -> None:
    # given
    controller = StubController(initialized=True)
    controller.scan_device_objects.side_effect = RuntimeError("failed")
    monkeypatch.setattr(scan_module, "get_bacnet_controller", lambda **_: controller)

    # when
    result = asyncio.run(scan_module.discover_bacnet_objects("1.2.3.4", 7))

    # then
    assert result.success is False
    assert result.data == []
    assert result.error == "failed"


def test_discover_bacnet_objects_sync_uses_run_sync(monkeypatch) -> None:
    # given
    expected = object()

    def _fake_run_sync(coro, *, timeout):
        coro.close()
        assert timeout == scan_module.BACNET_OPERATION_TIMEOUT
        return expected

    monkeypatch.setattr(scan_module, "run_sync", _fake_run_sync)

    # when
    result = scan_module.discover_bacnet_objects_sync("1.2.3.4", 44)

    # then
    assert result is expected
