"""Typed BACnet models for discovery operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "BACnetObjectIdentifier",
    "BACnetDeviceIdentifier",
    "BACnetDevice",
    "BACnetObject",
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
