"""Pure data definitions for protocol-agnostic discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "DiscoveryError",
    "Protocol",
    "EntityKind",
    "ProtocolRef",
    "Entity",
    "Device",
    "Point",
    "DiscoveryScanTimings",
    "DiscoveryNetworkScanInput",
    "DiscoveryObjectsInput",
    "DiscoveryFullScanInput",
    "DiscoveryObjectsData",
    "DiscoveryFullScanData",
    "DiscoveryNetworkScanResult",
    "DiscoveryObjectsResult",
    "DiscoveryFullScanResult",
]


@dataclass(slots=True)
class DiscoveryError:
    code: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Protocol(StrEnum):
    BACNET = "bacnet"


class EntityKind(StrEnum):
    DEVICE = "device"
    POINT = "point"


@dataclass(slots=True)
class ProtocolRef:
    """Protocol-specific addressing and raw discovery payload."""

    protocol: Protocol
    address: str
    object_id: str | None = None
    device_id: str | None = None
    network: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Entity:
    """Protocol-agnostic base for all discoverable objects."""

    uid: str
    kind: EntityKind
    name: str
    description: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    protocol_ref: ProtocolRef | None = None


@dataclass(slots=True)
class Device(Entity):
    """A discovered controller, gateway, or networked device."""

    manufacturer: str | None = None
    model: str | None = None
    firmware: str | None = None
    points: list["Point"] = field(default_factory=list)


@dataclass(slots=True)
class Point(Entity):
    """A discovered point (sensor, command, setpoint, alarm)."""

    # Values are canonical strings when standardized, raw strings when unknown, or None.
    data_type: str | None = None
    unit: str | None = None
    unit_id: str | None = None
    access: str | None = None
    value: Any = None
    point_type: str | None = None
    quantity: str | None = None
    medium: str | None = None


@dataclass(slots=True)
class DiscoveryScanTimings:
    started_at_utc: str
    finished_at_utc: str
    duration_seconds: float


@dataclass(slots=True)
class DiscoveryNetworkScanInput:
    protocols: list[Protocol]
    network: str | None = None
    strict: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DiscoveryObjectsInput:
    device: str
    network: str | None = None
    strict: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DiscoveryFullScanInput:
    protocols: list[Protocol]
    network: str | None
    strict: bool
    max_concurrent: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DiscoveryObjectsData:
    device: Device


@dataclass(slots=True)
class DiscoveryFullScanData:
    devices: list[Device]


@dataclass(slots=True)
class DiscoveryNetworkScanResult:
    input: DiscoveryNetworkScanInput
    data: list[Device]
    timings: DiscoveryScanTimings
    success: bool
    errors: list[str] = field(default_factory=list)
    error_details: list[DiscoveryError] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DiscoveryObjectsResult:
    input: DiscoveryObjectsInput
    data: DiscoveryObjectsData
    timings: DiscoveryScanTimings
    success: bool
    errors: list[str] = field(default_factory=list)
    error_details: list[DiscoveryError] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DiscoveryFullScanResult:
    input: DiscoveryFullScanInput
    data: DiscoveryFullScanData
    timings: DiscoveryScanTimings
    success: bool
    errors: list[str] = field(default_factory=list)
    error_details: list[DiscoveryError] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
