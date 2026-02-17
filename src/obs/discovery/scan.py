"""Protocol-agnostic discovery API with dedicated operation wrappers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ._adapters import bacnet_device_to_device, bacnet_object_to_point
from ._context import scan_context, timings, utc_now
from ._identity import device_identifier_from_device, parse_device_identifier
from .network import auto_detect_client_ip, detect_local_network
from .types import (
    Device,
    DiscoveryError,
    DiscoveryFullScanData,
    DiscoveryFullScanInput,
    DiscoveryFullScanResult,
    DiscoveryNetworkScanInput,
    DiscoveryNetworkScanResult,
    DiscoveryObjectsData,
    DiscoveryObjectsInput,
    DiscoveryObjectsResult,
    EntityKind,
    Point,
    Protocol,
    ProtocolRef,
    ReadPointsData,
    ReadPointsInput,
    ReadPointsResult,
)

__all__ = [
    "scan_network",
    "scan_network_sync",
    "discover_objects",
    "discover_objects_sync",
    "full_scan",
    "full_scan_sync",
    "read_points",
    "read_points_sync",
]

logger = logging.getLogger(__name__)


def _error(code: str, message: str, **metadata: Any) -> DiscoveryError:
    return DiscoveryError(code=code, message=message, metadata=metadata)


def _normalize_protocols(protocol: Protocol | list[Protocol] | None) -> list[Protocol]:
    if protocol is None:
        return list(Protocol)
    if isinstance(protocol, Protocol):
        return [protocol]
    return protocol


def _resolve_client_ip(
    *,
    client_ip: str | None,
    device_address: str | None = None,
    strict: bool = False,
) -> str:
    if client_ip:
        return client_ip
    try:
        return auto_detect_client_ip(device_address)
    except RuntimeError:
        if strict:
            raise RuntimeError("Unable to resolve client IP") from None
        return "unknown"


def _resolve_network(network: str | None, *, strict: bool = False) -> str | None:
    if network:
        return network
    try:
        return detect_local_network()
    except RuntimeError:
        if strict:
            raise RuntimeError("Unable to resolve local network") from None
        return None


async def _scan_network_for(protocol: Protocol, **kwargs: Any) -> list[Device]:
    if protocol == Protocol.BACNET:
        from .bacnet.scan import scan_bacnet_network

        raw_result = await scan_bacnet_network(**dict(kwargs))
        if not raw_result.success:
            raise RuntimeError(raw_result.error or "BACnet network scan failed")
        network = kwargs.get("network")
        return [
            bacnet_device_to_device(raw_device, network=network)
            for raw_device in raw_result.data
        ]
    raise ValueError(f"Unsupported protocol: {protocol}")


async def scan_network(
    protocol: Protocol | list[Protocol] | None = None,
    *,
    network: str | None = None,
    strict: bool = False,
    **kwargs: Any,
) -> DiscoveryNetworkScanResult:
    """Discover devices on selected protocol(s), or all by default."""
    protocols = _normalize_protocols(protocol)
    started = utc_now()
    try:
        resolved_network = _resolve_network(network, strict=strict)
    except RuntimeError as exc:
        finished = utc_now()
        input_data = DiscoveryNetworkScanInput(
            protocols=protocols,
            network=network,
            strict=strict,
            metadata=dict(kwargs),
        )
        detail = _error("network_resolution_failed", str(exc))
        return DiscoveryNetworkScanResult(
            input=input_data,
            data=[],
            timings=timings(started, finished),
            success=False,
            errors=[detail.message],
            error_details=[detail],
            metadata=scan_context(client_ip=None),
        )
    input_data = DiscoveryNetworkScanInput(
        protocols=protocols,
        network=resolved_network,
        strict=strict,
        metadata=dict(kwargs),
    )
    local_kwargs = dict(kwargs)
    errors: list[str] = []
    error_details: list[DiscoveryError] = []
    devices: list[Device] = []

    try:
        client_ip = _resolve_client_ip(
            client_ip=local_kwargs.get("client_ip"),
            strict=strict,
        )
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        finished = utc_now()
        detail = _error("client_ip_resolution_failed", str(exc))
        return DiscoveryNetworkScanResult(
            input=input_data,
            data=[],
            timings=timings(started, finished),
            success=False,
            errors=[detail.message],
            error_details=[detail],
            metadata=scan_context(client_ip=None),
        )
    local_kwargs["client_ip"] = client_ip

    for proto in protocols:
        try:
            local_kwargs["network"] = resolved_network
            devices.extend(await _scan_network_for(proto, **local_kwargs))
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            errors.append(f"{proto}: {exc}")
            error_details.append(
                _error(
                    "protocol_scan_failed",
                    str(exc),
                    protocol=proto.value,
                )
            )
            logger.warning("Error scanning network for %s: %s", proto, exc)

    finished = utc_now()
    return DiscoveryNetworkScanResult(
        input=input_data,
        data=devices,
        timings=timings(started, finished),
        success=not errors,
        errors=errors,
        error_details=error_details,
        metadata=scan_context(client_ip=client_ip),
    )


def scan_network_sync(
    protocol: Protocol | list[Protocol] | None = None,
    *,
    network: str | None = None,
    strict: bool = False,
    **kwargs: Any,
) -> DiscoveryNetworkScanResult:
    """Synchronous wrapper for scan_network()."""
    from .bacnet._loop import run_sync

    return run_sync(
        scan_network(protocol=protocol, network=network, strict=strict, **kwargs),
        timeout=300,
    )


async def discover_objects(
    device: str,
    *,
    network: str | None = None,
    strict: bool = False,
    **kwargs: Any,
) -> DiscoveryObjectsResult:
    """Discover all objects/points for one identifier: protocol://address#device_id."""
    started = utc_now()
    try:
        resolved_network = _resolve_network(network, strict=strict)
    except RuntimeError as exc:
        finished = utc_now()
        input_data = DiscoveryObjectsInput(
            device=device,
            network=network,
            strict=strict,
            metadata=dict(kwargs),
        )
        detail = _error("network_resolution_failed", str(exc), device=device)
        return DiscoveryObjectsResult(
            input=input_data,
            data=DiscoveryObjectsData(
                device=Device(uid=device, kind=EntityKind.DEVICE, name=device),
            ),
            timings=timings(started, finished),
            success=False,
            errors=[detail.message],
            error_details=[detail],
            metadata=scan_context(client_ip=None),
        )
    input_data = DiscoveryObjectsInput(
        device=device,
        network=resolved_network,
        strict=strict,
        metadata=dict(kwargs),
    )
    provided_client_ip = kwargs.get("client_ip")
    try:
        default_client_ip = _resolve_client_ip(
            client_ip=provided_client_ip, strict=strict
        )
    except RuntimeError as exc:
        finished = utc_now()
        detail = _error("client_ip_resolution_failed", str(exc), device=device)
        return DiscoveryObjectsResult(
            input=input_data,
            data=DiscoveryObjectsData(
                device=Device(uid=device, kind=EntityKind.DEVICE, name=device),
            ),
            timings=timings(started, finished),
            success=False,
            errors=[detail.message],
            error_details=[detail],
            metadata=scan_context(client_ip=None),
        )
    errors: list[str] = []
    error_details: list[DiscoveryError] = []

    try:
        protocol, address, device_id = parse_device_identifier(device)
    except ValueError as exc:
        finished = utc_now()
        return DiscoveryObjectsResult(
            input=input_data,
            data=DiscoveryObjectsData(
                device=Device(
                    uid=device,
                    kind=EntityKind.DEVICE,
                    name=device,
                ),
            ),
            timings=timings(started, finished),
            success=False,
            errors=[str(exc)],
            error_details=[
                _error("invalid_device_identifier", str(exc), device=device)
            ],
            metadata=scan_context(client_ip=default_client_ip),
        )

    resolved_network = input_data.network
    client_ip = (
        provided_client_ip
        if provided_client_ip
        else _resolve_client_ip(client_ip=None, device_address=address, strict=strict)
    )
    discovered_device = Device(
        uid=device,
        kind=EntityKind.DEVICE,
        name=device_id,
        protocol_ref=ProtocolRef(
            protocol=protocol,
            address=address,
            device_id=device_id,
            network=resolved_network,
        ),
    )

    try:
        if protocol == Protocol.BACNET:
            from .bacnet.scan import discover_bacnet_objects

            raw_result = await discover_bacnet_objects(
                address,
                int(device_id),
                **{**dict(kwargs), "client_ip": client_ip},
            )
            if not raw_result.success:
                message = raw_result.error or "BACnet object discovery failed"
                errors.append(message)
                error_details.append(
                    _error(
                        "protocol_object_discovery_failed",
                        message,
                        protocol=protocol.value,
                        device=device,
                    )
                )

            discovered_device.points = [
                bacnet_object_to_point(raw_object, network=resolved_network)
                for raw_object in raw_result.data
            ]
        else:
            raise ValueError(f"Unsupported protocol: {protocol}")
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        errors.append(str(exc))
        error_details.append(
            _error(
                "object_discovery_error",
                str(exc),
                protocol=protocol.value,
                device=device,
            )
        )

    finished = utc_now()
    return DiscoveryObjectsResult(
        input=input_data,
        data=DiscoveryObjectsData(device=discovered_device),
        timings=timings(started, finished),
        success=not errors,
        errors=errors,
        error_details=error_details,
        metadata=scan_context(client_ip=client_ip),
    )


def discover_objects_sync(
    device: str,
    *,
    network: str | None = None,
    strict: bool = False,
    **kwargs: Any,
) -> DiscoveryObjectsResult:
    """Synchronous wrapper for discover_objects()."""
    from .bacnet._loop import run_sync

    return run_sync(
        discover_objects(device, network=network, strict=strict, **kwargs),
        timeout=300,
    )


async def full_scan(
    protocol: Protocol | list[Protocol] | None = None,
    *,
    network: str | None = None,
    strict: bool = False,
    max_concurrent: int = 10,
    **kwargs: Any,
) -> DiscoveryFullScanResult:
    """Scan network devices then discover objects for each discovered device."""
    protocols = _normalize_protocols(protocol)
    started = utc_now()
    try:
        resolved_network = _resolve_network(network, strict=strict)
    except RuntimeError as exc:
        finished = utc_now()
        input_data = DiscoveryFullScanInput(
            protocols=protocols,
            network=network,
            strict=strict,
            max_concurrent=max_concurrent,
            metadata=dict(kwargs),
        )
        detail = _error("network_resolution_failed", str(exc))
        return DiscoveryFullScanResult(
            input=input_data,
            data=DiscoveryFullScanData(devices=[]),
            timings=timings(started, finished),
            success=False,
            errors=[detail.message],
            error_details=[detail],
            metadata=scan_context(client_ip=None),
        )
    input_data = DiscoveryFullScanInput(
        protocols=protocols,
        network=resolved_network,
        strict=strict,
        max_concurrent=max_concurrent,
        metadata=dict(kwargs),
    )
    local_kwargs = dict(kwargs)
    try:
        client_ip = _resolve_client_ip(
            client_ip=local_kwargs.get("client_ip"), strict=strict
        )
    except RuntimeError as exc:
        finished = utc_now()
        detail = _error("client_ip_resolution_failed", str(exc))
        return DiscoveryFullScanResult(
            input=input_data,
            data=DiscoveryFullScanData(devices=[]),
            timings=timings(started, finished),
            success=False,
            errors=[detail.message],
            error_details=[detail],
            metadata=scan_context(client_ip=None),
        )
    local_kwargs["client_ip"] = client_ip
    error_details: list[DiscoveryError] = []

    network_result = await scan_network(
        protocol=protocol,
        network=resolved_network,
        strict=strict,
        **local_kwargs,
    )
    errors = list(network_result.errors)
    error_details.extend(network_result.error_details)
    devices = list(network_result.data)

    if not devices:
        finished = utc_now()
        return DiscoveryFullScanResult(
            input=input_data,
            data=DiscoveryFullScanData(devices=[]),
            timings=timings(started, finished),
            success=not errors,
            errors=errors,
            error_details=error_details,
            metadata=scan_context(client_ip=client_ip),
        )

    sem = asyncio.Semaphore(max_concurrent)

    async def _discover_for_device(device_obj: Device) -> Device | None:
        async with sem:
            try:
                identifier = device_identifier_from_device(device_obj)
                result = await discover_objects(
                    identifier,
                    network=resolved_network,
                    strict=strict,
                    **local_kwargs,
                )
            except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
                errors.append(f"{device_obj.uid}: {exc}")
                error_details.append(
                    _error(
                        "device_discovery_error",
                        str(exc),
                        device_uid=device_obj.uid,
                    )
                )
                logger.warning(
                    "Error discovering objects for %s: %s", device_obj.uid, exc
                )
                return None

            errors.extend(result.errors)
            error_details.extend(result.error_details)
            if not (result.success or result.data.device.points):
                return None

            # Preserve richer metadata from network scan device while keeping discovered points.
            discovered_device = result.data.device
            canonical_device = Device(
                uid=device_obj.uid,
                kind=device_obj.kind,
                name=device_obj.name,
                description=device_obj.description,
                extra={
                    **dict(device_obj.extra),
                    **dict(discovered_device.extra),
                },
                protocol_ref=device_obj.protocol_ref,
                manufacturer=discovered_device.manufacturer or device_obj.manufacturer,
                model=discovered_device.model or device_obj.model,
                firmware=discovered_device.firmware or device_obj.firmware,
                points=list(discovered_device.points),
            )
            if discovered_device.protocol_ref is not None:
                canonical_device.protocol_ref = discovered_device.protocol_ref
            if discovered_device.name and (
                not canonical_device.name or canonical_device.name.startswith("device-")
            ):
                canonical_device.name = discovered_device.name
            return canonical_device

    discovered_list = await asyncio.gather(
        *[_discover_for_device(device_obj) for device_obj in devices]
    )

    merged_devices: list[Device] = []

    for item in discovered_list:
        if item is None:
            continue
        merged_devices.append(item)

    finished = utc_now()
    return DiscoveryFullScanResult(
        input=input_data,
        data=DiscoveryFullScanData(devices=merged_devices),
        timings=timings(started, finished),
        success=not errors,
        errors=errors,
        error_details=error_details,
        metadata=scan_context(client_ip=client_ip),
    )


def full_scan_sync(
    protocol: Protocol | list[Protocol] | None = None,
    *,
    network: str | None = None,
    strict: bool = False,
    max_concurrent: int = 10,
    **kwargs: Any,
) -> DiscoveryFullScanResult:
    """Synchronous wrapper for full_scan()."""
    from .bacnet._loop import run_sync

    return run_sync(
        full_scan(
            protocol=protocol,
            network=network,
            strict=strict,
            max_concurrent=max_concurrent,
            **kwargs,
        ),
        timeout=600,
    )


async def read_points(
    device: str,
    points: list[tuple[str, int]],
    *,
    network: str | None = None,
    strict: bool = False,
    **kwargs: Any,
) -> ReadPointsResult:
    """Read current values from device points.

    Args:
        device: Device identifier in format protocol://address#device_id
            (e.g., "bacnet://192.168.1.100#1234").
        points: List of (object_type, instance) tuples to read.
        network: Optional network specification.
        strict: If True, raise on resolution failures.
        **kwargs: Additional protocol-specific options (client_ip, bbmd_ip, etc.)

    Returns:
        ReadPointsResult with list of Point objects containing current values.
    """
    started = utc_now()

    input_data = ReadPointsInput(
        device=device,
        points=points,
        network=network,
        strict=strict,
        metadata=dict(kwargs),
    )

    try:
        resolved_network = _resolve_network(network, strict=strict)
    except RuntimeError as exc:
        finished = utc_now()
        detail = _error("network_resolution_failed", str(exc), device=device)
        return ReadPointsResult(
            input=input_data,
            data=ReadPointsData(points=[]),
            timings=timings(started, finished),
            success=False,
            errors=[detail.message],
            error_details=[detail],
            metadata=scan_context(client_ip=None),
        )

    provided_client_ip = kwargs.get("client_ip")
    try:
        default_client_ip = _resolve_client_ip(
            client_ip=provided_client_ip, strict=strict
        )
    except RuntimeError as exc:
        finished = utc_now()
        detail = _error("client_ip_resolution_failed", str(exc), device=device)
        return ReadPointsResult(
            input=input_data,
            data=ReadPointsData(points=[]),
            timings=timings(started, finished),
            success=False,
            errors=[detail.message],
            error_details=[detail],
            metadata=scan_context(client_ip=None),
        )

    errors: list[str] = []
    error_details: list[DiscoveryError] = []

    try:
        protocol, address, device_id = parse_device_identifier(device)
    except ValueError as exc:
        finished = utc_now()
        return ReadPointsResult(
            input=input_data,
            data=ReadPointsData(points=[]),
            timings=timings(started, finished),
            success=False,
            errors=[str(exc)],
            error_details=[
                _error("invalid_device_identifier", str(exc), device=device)
            ],
            metadata=scan_context(client_ip=default_client_ip),
        )

    client_ip = (
        provided_client_ip
        if provided_client_ip
        else _resolve_client_ip(client_ip=None, device_address=address, strict=strict)
    )

    read_points_list: list[Point] = []

    try:
        if protocol == Protocol.BACNET:
            from .bacnet.scan import read_bacnet_points

            raw_result = await read_bacnet_points(
                address,
                int(device_id),
                points,
                client_ip=client_ip,
                **{k: v for k, v in kwargs.items() if k != "client_ip"},
            )
            if not raw_result.success:
                message = raw_result.error or "BACnet point read failed"
                errors.append(message)
                error_details.append(
                    _error(
                        "protocol_read_failed",
                        message,
                        protocol=protocol.value,
                        device=device,
                    )
                )

            # Convert BACnetObject to Point
            read_points_list = [
                bacnet_object_to_point(obj, network=resolved_network)
                for obj in raw_result.data
            ]
        else:
            raise ValueError(f"Unsupported protocol: {protocol}")
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        errors.append(str(exc))
        error_details.append(
            _error(
                "read_error",
                str(exc),
                protocol=protocol.value,
                device=device,
            )
        )

    finished = utc_now()

    return ReadPointsResult(
        input=input_data,
        data=ReadPointsData(points=read_points_list),
        timings=timings(started, finished),
        success=not errors,
        errors=errors,
        error_details=error_details,
        metadata=scan_context(client_ip=client_ip),
    )


def read_points_sync(
    device: str,
    points: list[tuple[str, int]],
    *,
    network: str | None = None,
    strict: bool = False,
    **kwargs: Any,
) -> ReadPointsResult:
    """Synchronous wrapper for read_points()."""
    from .bacnet._loop import run_sync

    return run_sync(
        read_points(device, points, network=network, strict=strict, **kwargs),
        timeout=60,
    )
