"""Internal adapters from protocol-native payloads to discovery models."""

from __future__ import annotations

from typing import Any

from ._normalization import (
    BACNET_ACCESS_BY_OBJECT_TYPE,
    BACNET_CANONICAL_UNITS_BY_ID,
    BACNET_CANONICAL_UNITS_BY_NAME,
    BACNET_DATA_TYPE_BY_OBJECT_TYPE,
    BACNET_DATA_TYPE_PREFIXES,
    BACNET_MEDIUM_BY_OBJECT_TYPE,
    BACNET_MEDIUM_BY_PREFIX,
    BACNET_QUANTITY_BY_UNIT,
    NORMALIZATION_VERSION,
)
from .types import Device, EntityKind, Point, Protocol, ProtocolRef


def _bacnet_data_type(object_type: str) -> str | None:
    ot = object_type.lower()
    if ot in BACNET_DATA_TYPE_BY_OBJECT_TYPE:
        return BACNET_DATA_TYPE_BY_OBJECT_TYPE[ot]
    for prefix, dtype in BACNET_DATA_TYPE_PREFIXES.items():
        if ot.startswith(prefix):
            return dtype
    return None


def _bacnet_access_mode(object_type: str) -> str | None:
    ot = object_type.lower()
    if ot in BACNET_ACCESS_BY_OBJECT_TYPE:
        return BACNET_ACCESS_BY_OBJECT_TYPE[ot]
    if "input" in ot:
        return "read"
    if "output" in ot or "value" in ot:
        return "read-write"
    return None


def _quantity_from_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    return BACNET_QUANTITY_BY_UNIT.get(unit.lower())


def _medium_from_object_type(object_type: str) -> str | None:
    ot = object_type.lower()
    if ot in BACNET_MEDIUM_BY_OBJECT_TYPE:
        return BACNET_MEDIUM_BY_OBJECT_TYPE[ot]
    for prefix, medium in BACNET_MEDIUM_BY_PREFIX.items():
        if ot.startswith(prefix):
            return medium
    return None


def _canonical_unit(unit: str | None, unit_id: str | None) -> str | None:
    if unit is None and unit_id is None:
        return None
    if unit is not None:
        return BACNET_CANONICAL_UNITS_BY_NAME.get(unit.lower(), unit)
    return BACNET_CANONICAL_UNITS_BY_ID.get(str(unit_id), str(unit_id))


def bacnet_device_to_device(raw_device: Any, *, network: str | None = None) -> Device:
    object_list = [
        (obj.object_type, obj.instance)
        for obj in getattr(raw_device, "object_list", [])
    ]
    return Device(
        uid=raw_device.uid,
        kind=EntityKind.DEVICE,
        name=raw_device.name or f"device-{raw_device.identifier.device_id}",
        manufacturer=raw_device.vendor,
        model=getattr(raw_device, "model", None),
        firmware=getattr(raw_device, "firmware", None),
        protocol_ref=ProtocolRef(
            protocol=Protocol.BACNET,
            address=raw_device.identifier.address,
            device_id=str(raw_device.identifier.device_id),
            network=network,
            raw={"object_list": object_list},
        ),
    )


def bacnet_object_to_point(raw_object: Any, *, network: str | None = None) -> Point:
    object_type = raw_object.object_identifier.object_type
    object_id = f"{object_type}:{raw_object.object_identifier.instance}"
    unit_id = getattr(raw_object, "unit_id", None)
    unit = _canonical_unit(raw_object.units, unit_id)
    source = (
        raw_object.metadata.get("source")
        if isinstance(raw_object.metadata, dict)
        else None
    )
    return Point(
        uid=raw_object.uid,
        kind=EntityKind.POINT,
        name=raw_object.name or object_id,
        description=raw_object.description,
        unit=unit,
        unit_id=unit_id,
        value=raw_object.value,
        data_type=_bacnet_data_type(object_type),
        access=_bacnet_access_mode(object_type),
        point_type=object_type,
        quantity=_quantity_from_unit(unit),
        medium=_medium_from_object_type(object_type),
        extra={
            "source": source,
            "normalization_version": NORMALIZATION_VERSION,
        },
        protocol_ref=ProtocolRef(
            protocol=Protocol.BACNET,
            address=raw_object.device.address,
            device_id=str(raw_object.device.device_id),
            object_id=object_id,
            network=network,
            raw=raw_object.metadata,
        ),
    )
