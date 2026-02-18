from __future__ import annotations

import asyncio
from types import SimpleNamespace

from obs.discovery import _context as context_module
from obs.discovery import _identity as identity_module
from obs.discovery import scan as scan_module
from obs.discovery.types import (
    DiscoveryNetworkScanInput,
    DiscoveryNetworkScanResult,
    DiscoveryObjectsData,
    DiscoveryObjectsInput,
    DiscoveryObjectsResult,
    DiscoveryScanTimings,
    Protocol,
)
from tests.factories import (
    FakeRawBACnetDevice,
    FakeRawBACnetObject,
    FakeRawDeviceIdentifier,
    FakeRawObjectIdentifier,
    make_discovery_device,
    make_discovery_point,
)


def test_discover_objects_returns_error_result_for_invalid_identifier() -> None:
    # given
    invalid_device_id = "not-a-valid-identifier"

    # when
    result = asyncio.run(scan_module.discover_objects(invalid_device_id))

    # then
    assert result.success is False
    assert result.data.device.uid == invalid_device_id
    assert result.data.device.points == []
    assert result.errors


def test_parse_device_identifier_message_uses_hash_delimiter() -> None:
    # given
    invalid_device_id = "invalid"

    # when / then
    try:
        identity_module.parse_device_identifier(invalid_device_id)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "protocol://address#device_id" in str(exc)


def test_discover_objects_uses_route_aware_client_ip_fallback(monkeypatch) -> None:
    # given
    captured: dict[str, str] = {}
    raw_obj = FakeRawBACnetObject(
        uid="bacnet://10.0.0.9/1001/analogInput:1",
        object_identifier=FakeRawObjectIdentifier(
            object_type="analogInput", instance=1
        ),
        device=FakeRawDeviceIdentifier(address="10.0.0.9", device_id=1001),
    )

    def _fake_auto_detect(device_address: str | None = None) -> str:
        captured["route_for"] = device_address or ""
        return "10.0.0.2/24"

    async def _fake_discover_bacnet_objects(address: str, device_id: int, **kwargs):
        captured["address"] = address
        captured["device_id"] = str(device_id)
        captured["client_ip"] = kwargs.get("client_ip", "")
        return SimpleNamespace(success=True, error=None, data=[raw_obj])

    monkeypatch.setattr(scan_module, "auto_detect_client_ip", _fake_auto_detect)
    monkeypatch.setattr(
        "obs.discovery.bacnet.scan.discover_bacnet_objects",
        _fake_discover_bacnet_objects,
    )

    # when
    result = asyncio.run(
        scan_module.discover_objects(
            "bacnet://10.0.0.9#1001",
            network="10.0.0.0/24",
        )
    )

    # then
    assert result.success is True
    assert captured["route_for"] == "10.0.0.9"
    assert captured["address"] == "10.0.0.9"
    assert captured["device_id"] == "1001"
    assert captured["client_ip"] == "10.0.0.2/24"
    assert result.input.network == "10.0.0.0/24"
    assert len(result.data.device.points) == 1


def test_scan_network_uses_bacnet_ip_fallback(monkeypatch) -> None:
    # given
    captured: dict[str, str] = {}
    raw_device = FakeRawBACnetDevice(
        uid="bacnet://192.168.1.10/1001",
        identifier=FakeRawDeviceIdentifier(address="192.168.1.10", device_id=1001),
        object_list=[FakeRawObjectIdentifier(object_type="analogInput", instance=1)],
    )

    def _fake_auto_detect(device_address: str | None = None) -> str:
        captured["route_for"] = str(device_address)
        return "192.168.1.2/24"

    async def _fake_scan_bacnet_network(**kwargs):
        captured["client_ip"] = kwargs.get("client_ip", "")
        return SimpleNamespace(success=True, error=None, data=[raw_device])

    monkeypatch.setattr(scan_module, "auto_detect_client_ip", _fake_auto_detect)
    monkeypatch.setattr(
        "obs.discovery.bacnet.scan.scan_bacnet_network", _fake_scan_bacnet_network
    )

    # when
    result = asyncio.run(scan_module.scan_network(protocol=Protocol.BACNET))

    # then
    assert result.success is True
    assert captured["route_for"] == "None"
    assert captured["client_ip"] == "192.168.1.2/24"
    assert result.metadata["client_ip"] == "192.168.1.2/24"
    assert len(result.data) == 1


def test_scan_network_populates_protocol_ref_network(monkeypatch) -> None:
    # given
    raw_device = FakeRawBACnetDevice(
        uid="bacnet://192.168.1.10/1001",
        identifier=FakeRawDeviceIdentifier(address="192.168.1.10", device_id=1001),
    )

    monkeypatch.setattr(
        scan_module, "auto_detect_client_ip", lambda *_: "192.168.1.2/24"
    )

    async def _fake_scan_bacnet_network(**kwargs):
        return SimpleNamespace(success=True, error=None, data=[raw_device])

    monkeypatch.setattr(
        "obs.discovery.bacnet.scan.scan_bacnet_network", _fake_scan_bacnet_network
    )

    # when
    result = asyncio.run(
        scan_module.scan_network(protocol=Protocol.BACNET, network="192.168.1.0/24")
    )

    # then
    assert result.success is True
    assert result.data[0].protocol_ref is not None
    assert result.data[0].protocol_ref.network == "192.168.1.0/24"


def test_full_scan_merges_network_device_and_discovered_points(monkeypatch) -> None:
    # given
    network_device = make_discovery_device(
        uid="bacnet://192.168.1.10/1001",
        name="AHU-1",
        points=[],
    )
    discovered_point = make_discovery_point()
    discovered_device = make_discovery_device(
        uid="bacnet://192.168.1.10#1001",
        name="1001",
        points=[discovered_point],
    )

    async def _fake_scan_network(*args, **kwargs):
        return DiscoveryNetworkScanResult(
            input=DiscoveryNetworkScanInput(protocols=[Protocol.BACNET]),
            data=[network_device],
            timings=DiscoveryScanTimings(
                started_at_utc="2026-01-01T00:00:00+00:00",
                finished_at_utc="2026-01-01T00:00:01+00:00",
                duration_seconds=1.0,
            ),
            success=True,
        )

    async def _fake_discover_objects(device: str, **kwargs):
        return DiscoveryObjectsResult(
            input=DiscoveryObjectsInput(device=device),
            data=DiscoveryObjectsData(device=discovered_device),
            timings=DiscoveryScanTimings(
                started_at_utc="2026-01-01T00:00:00+00:00",
                finished_at_utc="2026-01-01T00:00:01+00:00",
                duration_seconds=1.0,
            ),
            success=True,
        )

    monkeypatch.setattr(scan_module, "scan_network", _fake_scan_network)
    monkeypatch.setattr(scan_module, "discover_objects", _fake_discover_objects)

    # when
    result = asyncio.run(scan_module.full_scan(protocol=Protocol.BACNET))

    # then
    assert result.success is True
    assert len(result.data.devices) == 1
    assert result.data.devices[0].uid == "bacnet://192.168.1.10/1001"
    assert len(result.data.devices[0].points) == 1


def test_scan_network_sets_unknown_client_ip_when_detection_fails(monkeypatch) -> None:
    # given
    monkeypatch.setattr(
        scan_module,
        "auto_detect_client_ip",
        lambda *_: (_ for _ in ()).throw(RuntimeError("no ip")),
    )

    async def _fake_scan_bacnet_network(**kwargs):
        return SimpleNamespace(success=True, error=None, data=[])

    monkeypatch.setattr(
        "obs.discovery.bacnet.scan.scan_bacnet_network", _fake_scan_bacnet_network
    )

    # when
    result = asyncio.run(scan_module.scan_network(protocol=Protocol.BACNET))

    # then
    assert result.metadata["client_ip"] == "unknown"


def test_scan_network_strict_fails_when_client_ip_unresolved(monkeypatch) -> None:
    # given
    monkeypatch.setattr(
        scan_module,
        "auto_detect_client_ip",
        lambda *_: (_ for _ in ()).throw(RuntimeError("no ip")),
    )
    monkeypatch.setattr(scan_module, "detect_local_network", lambda: "192.168.1.0/24")

    # when
    result = asyncio.run(
        scan_module.scan_network(protocol=Protocol.BACNET, strict=True)
    )

    # then
    assert result.success is False
    assert result.error_details
    assert result.error_details[0].code == "client_ip_resolution_failed"


def test_discover_objects_strict_fails_when_network_unresolved(monkeypatch) -> None:
    # given
    monkeypatch.setattr(
        scan_module,
        "detect_local_network",
        lambda: (_ for _ in ()).throw(RuntimeError("no net")),
    )

    # when
    result = asyncio.run(
        scan_module.discover_objects("bacnet://10.0.0.9#1001", strict=True)
    )

    # then
    assert result.success is False
    assert result.error_details
    assert result.error_details[0].code == "network_resolution_failed"


def test_scan_context_reads_library_version_from_source(monkeypatch) -> None:
    # given
    context_module.library_version_from_source.cache_clear()
    monkeypatch.setattr(context_module, "library_version_from_source", lambda: "0.2.0")

    # when
    context = context_module.scan_context(client_ip="10.0.0.2/24")

    # then
    assert context["library_version"] == "0.2.0"
    assert context["client_ip"] == "10.0.0.2/24"


# --- read_points tests ---


def test_read_points_success(monkeypatch) -> None:
    # given
    captured: dict[str, str] = {}
    raw_obj = FakeRawBACnetObject(
        uid="bacnet://192.168.1.10/1001/analogValue:1",
        object_identifier=FakeRawObjectIdentifier(
            object_type="analogValue", instance=1
        ),
        device=FakeRawDeviceIdentifier(address="192.168.1.10", device_id=1001),
        value=72.5,
    )

    def _fake_auto_detect(device_address: str | None = None) -> str:
        captured["route_for"] = device_address or ""
        return "192.168.1.2/24"

    async def _fake_read_bacnet_points(address, device_id, points, **kwargs):
        captured["address"] = address
        captured["device_id"] = str(device_id)
        captured["client_ip"] = kwargs.get("client_ip", "")
        return SimpleNamespace(success=True, error=None, data=[raw_obj])

    monkeypatch.setattr(scan_module, "auto_detect_client_ip", _fake_auto_detect)
    monkeypatch.setattr(
        "obs.discovery.bacnet.scan.read_bacnet_points",
        _fake_read_bacnet_points,
    )

    # when
    result = asyncio.run(
        scan_module.read_points(
            "bacnet://192.168.1.10#1001",
            [("analogValue", 1)],
            network="192.168.1.0/24",
        )
    )

    # then
    assert result.success is True
    assert captured["route_for"] == "192.168.1.10"
    assert captured["address"] == "192.168.1.10"
    assert captured["device_id"] == "1001"
    assert captured["client_ip"] == "192.168.1.2/24"
    assert len(result.data.points) == 1
    assert result.data.points[0].value == 72.5


def test_read_points_returns_error_for_invalid_identifier() -> None:
    # given
    invalid_device = "not-a-valid-identifier"

    # when
    result = asyncio.run(scan_module.read_points(invalid_device, [("analogValue", 1)]))

    # then
    assert result.success is False
    assert result.data.points == []
    assert result.errors
    assert result.error_details[0].code == "invalid_device_identifier"


def test_read_points_returns_error_on_network_resolution_failure(monkeypatch) -> None:
    # given
    monkeypatch.setattr(
        scan_module,
        "detect_local_network",
        lambda: (_ for _ in ()).throw(RuntimeError("no net")),
    )

    # when
    result = asyncio.run(
        scan_module.read_points(
            "bacnet://192.168.1.10#1001",
            [("analogValue", 1)],
            strict=True,
        )
    )

    # then
    assert result.success is False
    assert result.error_details[0].code == "network_resolution_failed"


def test_read_points_returns_error_on_client_ip_resolution_failure(monkeypatch) -> None:
    # given
    monkeypatch.setattr(scan_module, "detect_local_network", lambda: "192.168.1.0/24")
    monkeypatch.setattr(
        scan_module,
        "auto_detect_client_ip",
        lambda *_: (_ for _ in ()).throw(RuntimeError("no ip")),
    )

    # when
    result = asyncio.run(
        scan_module.read_points(
            "bacnet://192.168.1.10#1001",
            [("analogValue", 1)],
            strict=True,
        )
    )

    # then
    assert result.success is False
    assert result.error_details[0].code == "client_ip_resolution_failed"


def test_read_points_handles_protocol_read_failure(monkeypatch) -> None:
    # given
    monkeypatch.setattr(
        scan_module, "auto_detect_client_ip", lambda *_: "192.168.1.2/24"
    )

    async def _fake_read_bacnet_points(address, device_id, points, **kwargs):
        return SimpleNamespace(success=False, error="device timeout", data=[])

    monkeypatch.setattr(
        "obs.discovery.bacnet.scan.read_bacnet_points",
        _fake_read_bacnet_points,
    )

    # when
    result = asyncio.run(
        scan_module.read_points(
            "bacnet://192.168.1.10#1001",
            [("analogValue", 1)],
        )
    )

    # then
    assert result.success is False
    assert "device timeout" in result.errors[0]
    assert result.error_details[0].code == "protocol_read_failed"


def test_read_points_handles_exception_during_read(monkeypatch) -> None:
    # given
    monkeypatch.setattr(
        scan_module, "auto_detect_client_ip", lambda *_: "192.168.1.2/24"
    )

    async def _fake_read_bacnet_points(address, device_id, points, **kwargs):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(
        "obs.discovery.bacnet.scan.read_bacnet_points",
        _fake_read_bacnet_points,
    )

    # when
    result = asyncio.run(
        scan_module.read_points(
            "bacnet://192.168.1.10#1001",
            [("analogValue", 1)],
        )
    )

    # then
    assert result.success is False
    assert "connection lost" in result.errors[0]
    assert result.error_details[0].code == "read_error"


def test_read_points_sync_wrapper(monkeypatch) -> None:
    # given
    expected = object()

    def _fake_run_sync(coro, *, timeout):
        coro.close()
        assert timeout == 60
        return expected

    monkeypatch.setattr("obs.discovery.bacnet._loop.run_sync", _fake_run_sync)

    # when
    result = scan_module.read_points_sync(
        "bacnet://192.168.1.10#1001",
        [("analogValue", 1)],
    )

    # then
    assert result is expected
