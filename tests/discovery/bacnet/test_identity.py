from __future__ import annotations

import pytest

from obs.discovery.bacnet.identity import (
    MAX_DEVICE_INSTANCE,
    MAX_VENDOR_ID,
    LocalDeviceIdentity,
    default_application_software_version,
)


def test_empty_identity_maps_to_nothing() -> None:
    # given
    identity = LocalDeviceIdentity()

    # when / then
    assert identity.bac0_lite_kwargs() == {}
    assert identity.device_object_properties() == {}


def test_fields_split_between_bac0_lite_and_device_object() -> None:
    # given
    identity = LocalDeviceIdentity(
        device_id=1234567,
        device_name="scanner-01",
        vendor_id=842,
        vendor_name="Servisys, Inc.",
        model_name="scan-tool",
        description="lab bench",
        location="room 12",
        firmware_revision="os 2.3.0",
        application_software_version="scan-tool 2.1.0",
    )

    # when
    lite_kwargs = identity.bac0_lite_kwargs()
    properties = identity.device_object_properties()

    # then
    assert lite_kwargs == {
        "deviceId": 1234567,
        "localObjName": "scanner-01",
        "modelName": "scan-tool",
        "vendorId": 842,
    }
    assert properties == {
        "vendorName": "Servisys, Inc.",
        "description": "lab bench",
        "location": "room 12",
        "firmwareRevision": "os 2.3.0",
        "applicationSoftwareVersion": "scan-tool 2.1.0",
    }


def test_unset_fields_are_omitted_so_defaults_survive() -> None:
    # given
    identity = LocalDeviceIdentity(device_id=7, description="only these two")

    # when / then
    assert identity.bac0_lite_kwargs() == {"deviceId": 7}
    assert identity.device_object_properties() == {"description": "only these two"}


@pytest.mark.parametrize("device_id", [1, MAX_DEVICE_INSTANCE])
def test_device_id_bounds_are_inclusive(device_id: int) -> None:
    # when / then
    assert LocalDeviceIdentity(device_id=device_id).device_id == device_id


@pytest.mark.parametrize("device_id", [0, -1, MAX_DEVICE_INSTANCE + 1])
def test_device_id_out_of_range_is_rejected(device_id: int) -> None:
    # when / then
    with pytest.raises(ValueError, match="device_id must be between"):
        LocalDeviceIdentity(device_id=device_id)


@pytest.mark.parametrize("vendor_id", [-1, MAX_VENDOR_ID + 1])
def test_vendor_id_out_of_range_is_rejected(vendor_id: int) -> None:
    # when / then
    with pytest.raises(ValueError, match="vendor_id must be between"):
        LocalDeviceIdentity(vendor_id=vendor_id, vendor_name="x")


def test_vendor_id_without_name_is_rejected() -> None:
    # when / then
    with pytest.raises(ValueError, match="set together"):
        LocalDeviceIdentity(vendor_id=842)


def test_vendor_name_without_id_is_rejected() -> None:
    # when / then
    with pytest.raises(ValueError, match="set together"):
        LocalDeviceIdentity(vendor_name="Servisys, Inc.")


@pytest.mark.parametrize("value", ["", "   ", " padded", "padded ", "tab\t"])
def test_blank_or_padded_strings_are_rejected(value: str) -> None:
    # when / then
    with pytest.raises(ValueError, match="device_name must not be empty"):
        LocalDeviceIdentity(device_name=value)


def test_identity_is_frozen_and_hashable() -> None:
    # given
    identity = LocalDeviceIdentity(device_id=5)

    # when / then
    with pytest.raises(AttributeError):
        identity.device_id = 6  # type: ignore[misc]
    assert hash(identity) == hash(LocalDeviceIdentity(device_id=5))


def test_default_application_software_version_names_the_library() -> None:
    # when
    value = default_application_software_version()

    # then
    assert value.startswith("openbuildingstack")


def test_default_application_software_version_without_metadata(monkeypatch) -> None:
    # given
    import obs.discovery.bacnet.identity as identity_module
    from importlib.metadata import PackageNotFoundError

    def missing(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(identity_module, "version", missing)

    # when / then
    assert default_application_software_version() == "openbuildingstack"
