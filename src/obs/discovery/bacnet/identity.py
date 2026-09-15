"""Identity of the local BACnet device.

Every ``BACnetController`` starts a BAC0 instance. That instance is itself a
BACnet device on the network, even when it is only used to scan: it answers
Who-Is with I-Am and exposes a Device Object that other devices and BMS tools
read. ``LocalDeviceIdentity`` describes that Device Object.

This is the opposite side from ``BACnetDevice`` in ``types.py``. That class
describes devices *found* on the network. This one describes the device *this
process is*. BACnet, BAC0 and bacpypes3 all call that the "local device".

Two identifiers matter most:

- ``device_id`` is the address. Every read or write from another device is
  aimed at this number, and a BMS stores every point reference against it.
  It must be unique on the whole BACnet internetwork, and it should never
  change once external systems bind to it.
- ``device_name`` is the label. It appears next to the number in a BMS device
  tree. Changing it is cosmetic for almost every client.

The two version fields describe different layers of the host:

- ``firmware_revision`` is the platform build, the layer you would reflash.
- ``application_software_version`` is the program running on that platform.

Fields are applied through two routes, because BAC0 only honors part of what
``BAC0.lite()`` accepts:

- ``device_id``, ``device_name``, ``model_name`` and ``vendor_id`` are passed
  to ``BAC0.lite()``. See :meth:`LocalDeviceIdentity.bac0_lite_kwargs`.
- ``vendor_name``, ``description``, ``location``, ``firmware_revision`` and
  ``application_software_version`` are written onto the bacpypes3
  ``DeviceObject`` after BAC0 has built it. BAC0 accepts most of them as
  arguments but never applies them. See
  :meth:`LocalDeviceIdentity.device_object_properties`.

The controller does the applying. This module only knows the mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from importlib.metadata import PackageNotFoundError, version
from typing import Any

__all__ = [
    "LocalDeviceIdentity",
    "MAX_DEVICE_INSTANCE",
    "MAX_VENDOR_ID",
    "MIN_DEVICE_INSTANCE",
    "default_application_software_version",
]

# Object instance numbers are 22 bits wide. 4194303 (all ones) is the
# "unconfigured" wildcard and is not a real device instance.
MAX_DEVICE_INSTANCE = 4194302

# BAC0 tests ``deviceId`` for truthiness and falls back to a random instance
# when it is 0. Instance 0 is legal BACnet, but it cannot be requested through
# BAC0, so it is rejected here rather than silently replaced.
MIN_DEVICE_INSTANCE = 1

# Vendor_Identifier is Unsigned16 in the standard.
MAX_VENDOR_ID = 65535

_DISTRIBUTION_NAME = "openbuildingstack"

# Identity field -> keyword accepted and honored by ``BAC0.lite()``.
_BAC0_LITE_KWARGS: dict[str, str] = {
    "device_id": "deviceId",
    "device_name": "localObjName",
    "model_name": "modelName",
    "vendor_id": "vendorId",
}

# Identity field -> bacpypes3 ``DeviceObject`` attribute.
_DEVICE_OBJECT_ATTRS: dict[str, str] = {
    "vendor_name": "vendorName",
    "description": "description",
    "location": "location",
    "firmware_revision": "firmwareRevision",
    "application_software_version": "applicationSoftwareVersion",
}


def default_application_software_version() -> str:
    """Return the value used for Application_Software_Version when unset.

    bacpypes3 defaults this property to the string ``"1.0"``, which looks like
    a real version but is not. When the caller does not say what application
    is running, the library is the application, so its own name and version
    are the true answer.
    """
    try:
        return f"{_DISTRIBUTION_NAME} {version(_DISTRIBUTION_NAME)}"
    except PackageNotFoundError:
        return _DISTRIBUTION_NAME


@dataclass(frozen=True, slots=True)
class LocalDeviceIdentity:
    """Identity announced by the local BACnet device.

    Every field is optional. ``None`` keeps the BAC0 or bacpypes3 default for
    that property. Values are validated once, at construction, so a bad
    identity fails before anything reaches the network.

    Attributes:
        device_id: Device Object instance, 1 to 4194302. Must be unique on the
            BACnet internetwork. This is the number every other device uses to
            address this one, so it should not change once a client has bound
            to it.
        device_name: Device Object ``Object_Name`` (BAC0: ``localObjName``).
            Shown as the device name in BMS tools.
        vendor_id: ASHRAE-assigned ``Vendor_Identifier``, 0 to 65535. Use only
            an identifier assigned to your own organization. Another vendor's
            number makes BMS tools apply that vendor's proprietary handling
            and routes support requests to them. Must be set together with
            ``vendor_name``.
        vendor_name: ``Vendor_Name`` as registered with ASHRAE for
            ``vendor_id``. Must be set together with ``vendor_id``.
        model_name: ``Model_Name``. The product this device is, for example a
            gateway model or a tool name.
        description: ``Description``. Free text about this deployment.
        location: ``Location``. Where the device physically is.
        firmware_revision: ``Firmware_Revision``. The platform build of the
            host, the layer that would be reflashed.
        application_software_version: ``Application_Software_Version``. The
            release of the program running on the host. Defaults to this
            library's own name and version when unset.
    """

    device_id: int | None = None
    device_name: str | None = None
    vendor_id: int | None = None
    vendor_name: str | None = None
    model_name: str | None = None
    description: str | None = None
    location: str | None = None
    firmware_revision: str | None = None
    application_software_version: str | None = None

    def __post_init__(self) -> None:
        """Validate ranges, pairing and string content."""
        if self.device_id is not None and not (
            MIN_DEVICE_INSTANCE <= self.device_id <= MAX_DEVICE_INSTANCE
        ):
            raise ValueError(
                f"device_id must be between {MIN_DEVICE_INSTANCE} and "
                f"{MAX_DEVICE_INSTANCE}, got {self.device_id}"
            )
        if self.vendor_id is not None and not (0 <= self.vendor_id <= MAX_VENDOR_ID):
            raise ValueError(
                f"vendor_id must be between 0 and {MAX_VENDOR_ID}, got {self.vendor_id}"
            )
        if (self.vendor_id is None) != (self.vendor_name is None):
            raise ValueError(
                "vendor_id and vendor_name must be set together; "
                "both identify the same ASHRAE registration"
            )
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, str) and (not value or value != value.strip()):
                raise ValueError(
                    f"{field.name} must not be empty or have leading/trailing "
                    f"whitespace, got {value!r}"
                )

    def bac0_lite_kwargs(self) -> dict[str, Any]:
        """Return the fields BAC0 honors, keyed the way ``BAC0.lite()`` expects.

        Only set fields are included, so BAC0 keeps its own default for the
        rest.
        """
        return {
            bac0_name: getattr(self, field_name)
            for field_name, bac0_name in _BAC0_LITE_KWARGS.items()
            if getattr(self, field_name) is not None
        }

    def device_object_properties(self) -> dict[str, str]:
        """Return the fields written onto the bacpypes3 ``DeviceObject``.

        These are the properties ``BAC0.lite()`` does not apply. Keys are
        bacpypes3 attribute names. Only set fields are included.
        """
        return {
            attr: getattr(self, field_name)
            for field_name, attr in _DEVICE_OBJECT_ATTRS.items()
            if getattr(self, field_name) is not None
        }
