"""BACnet discovery entry points (async-first with sync wrappers)."""

from __future__ import annotations

from datetime import datetime

from .._context import utc_now
from ._loop import run_sync
from .controller import BACNET_ERRORS, BACNET_OPERATION_TIMEOUT, get_bacnet_controller
from .types import (
    BACnetDeviceIdentifier,
    BACnetNetworkScanInput,
    BACnetNetworkScanResult,
    BACnetObjectIdentifier,
    BACnetObjectsDiscoveryInput,
    BACnetObjectsDiscoveryResult,
    BACnetScanTimings,
)

_SCAN_FAILURES: tuple[type[BaseException], ...] = (
    ImportError,
    ModuleNotFoundError,
    RuntimeError,
    TimeoutError,
    OSError,
    ValueError,
    TypeError,
) + BACNET_ERRORS

__all__ = [
    "scan_bacnet_network",
    "scan_bacnet_network_sync",
    "discover_bacnet_objects",
    "discover_bacnet_objects_sync",
]


def _timings(started: datetime, finished: datetime) -> BACnetScanTimings:
    return BACnetScanTimings(
        started_at_utc=started.isoformat(),
        finished_at_utc=finished.isoformat(),
        duration_seconds=(finished - started).total_seconds(),
    )


async def scan_bacnet_network(
    timeout: int = 120,
    network: str | None = None,
    client_ip: str | None = None,
    bbmd_ip: str | None = None,
) -> BACnetNetworkScanResult:
    """Scan BACnet network and return discovered BACnet devices."""
    scan_input = BACnetNetworkScanInput(
        timeout=timeout,
        network=network,
        client_ip=client_ip,
        bbmd_ip=bbmd_ip,
    )
    started = utc_now()

    try:
        controller = get_bacnet_controller(client_ip=client_ip, bbmd_ip=bbmd_ip)
        if not controller._initialized:
            await controller.initialize()

        devices = await controller.scan_network(timeout=timeout)
        finished = utc_now()
        return BACnetNetworkScanResult(
            input=scan_input,
            data=devices,
            timings=_timings(started, finished),
            success=True,
        )
    except _SCAN_FAILURES as exc:
        finished = utc_now()
        return BACnetNetworkScanResult(
            input=scan_input,
            data=[],
            timings=_timings(started, finished),
            success=False,
            error=str(exc),
        )


def scan_bacnet_network_sync(
    timeout: int = 120,
    network: str | None = None,
    client_ip: str | None = None,
    bbmd_ip: str | None = None,
) -> BACnetNetworkScanResult:
    """Synchronous wrapper for scan_bacnet_network()."""
    return run_sync(
        scan_bacnet_network(
            timeout=timeout,
            network=network,
            client_ip=client_ip,
            bbmd_ip=bbmd_ip,
        ),
        timeout=timeout + 30,
    )


async def discover_bacnet_objects(
    device_address: str,
    device_id: int,
    *,
    client_ip: str | None = None,
    bbmd_ip: str | None = None,
    object_list: list[BACnetObjectIdentifier] | None = None,
    rpm_batch_size: int = 10,
    max_instance: int = 1000,
) -> BACnetObjectsDiscoveryResult:
    """Discover BACnet objects for one BACnet device address/id."""
    device_identifier = BACnetDeviceIdentifier(
        address=device_address, device_id=device_id
    )
    discover_input = BACnetObjectsDiscoveryInput(
        device=device_identifier,
        object_list=object_list,
        rpm_batch_size=rpm_batch_size,
        max_instance=max_instance,
        client_ip=client_ip,
        bbmd_ip=bbmd_ip,
    )
    started = utc_now()

    try:
        controller = get_bacnet_controller(client_ip=client_ip, bbmd_ip=bbmd_ip)
        if not controller._initialized:
            await controller.initialize()

        objects = await controller.scan_device_objects(
            device_address,
            device_id,
            max_instance=max_instance,
            object_list=object_list,
            rpm_batch_size=rpm_batch_size,
        )
        finished = utc_now()
        return BACnetObjectsDiscoveryResult(
            input=discover_input,
            data=objects,
            timings=_timings(started, finished),
            success=True,
        )
    except _SCAN_FAILURES as exc:
        finished = utc_now()
        return BACnetObjectsDiscoveryResult(
            input=discover_input,
            data=[],
            timings=_timings(started, finished),
            success=False,
            error=str(exc),
        )


def discover_bacnet_objects_sync(
    device_address: str,
    device_id: int,
    *,
    client_ip: str | None = None,
    bbmd_ip: str | None = None,
    object_list: list[BACnetObjectIdentifier] | None = None,
    rpm_batch_size: int = 10,
    max_instance: int = 1000,
) -> BACnetObjectsDiscoveryResult:
    """Synchronous wrapper for discover_bacnet_objects()."""
    return run_sync(
        discover_bacnet_objects(
            device_address,
            device_id,
            client_ip=client_ip,
            bbmd_ip=bbmd_ip,
            object_list=object_list,
            rpm_batch_size=rpm_batch_size,
            max_instance=max_instance,
        ),
        timeout=BACNET_OPERATION_TIMEOUT,
    )
