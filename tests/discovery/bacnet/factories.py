from __future__ import annotations

from dataclasses import dataclass

from obs.discovery.bacnet.types import (
    BACnetDevice,
    BACnetDeviceIdentifier,
    BACnetObject,
    BACnetObjectIdentifier,
)


def make_device_identifier(
    address: str = "192.168.1.10",
    device_id: int = 1001,
) -> BACnetDeviceIdentifier:
    return BACnetDeviceIdentifier(address=address, device_id=device_id)


def make_object_identifier(
    object_type: str = "analogInput",
    instance: int = 1,
) -> BACnetObjectIdentifier:
    return BACnetObjectIdentifier(object_type=object_type, instance=instance)


def make_bacnet_device(
    address: str = "192.168.1.10",
    device_id: int = 1001,
    name: str | None = "AHU-1",
    vendor: str | None = "Acme",
) -> BACnetDevice:
    identifier = make_device_identifier(address=address, device_id=device_id)
    return BACnetDevice(
        uid=f"bacnet://{address}/{device_id}",
        identifier=identifier,
        name=name,
        vendor=vendor,
        object_list=[make_object_identifier()],
    )


def make_bacnet_object(
    address: str = "192.168.1.10",
    device_id: int = 1001,
    object_type: str = "analogInput",
    instance: int = 1,
    value: bool | int | float | str | None = 12.3,
) -> BACnetObject:
    identifier = make_device_identifier(address=address, device_id=device_id)
    object_identifier = make_object_identifier(
        object_type=object_type,
        instance=instance,
    )
    return BACnetObject(
        uid=f"bacnet://{address}/{device_id}/{object_type}:{instance}",
        device=identifier,
        object_identifier=object_identifier,
        name=f"{object_type}-{instance}",
        description="desc",
        units="C",
        value=value,
    )


@dataclass
class FakeWhoIsResponse:
    device_id: int
    source: str

    @property
    def iAmDeviceIdentifier(self) -> tuple[str, int]:
        return ("device", self.device_id)

    @property
    def pduSource(self) -> str:
        return self.source
