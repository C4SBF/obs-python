"""Internal helpers for discovery device identifiers."""

from __future__ import annotations

from .types import Device, Protocol


def device_identifier_from_device(device: Device) -> str:
    if not device.protocol_ref:
        raise ValueError(f"Device {device.uid} has no protocol_ref")
    if not device.protocol_ref.device_id:
        raise ValueError(f"Device {device.uid} has no protocol_ref.device_id")
    # Use '#' delimiter to avoid ambiguity with address formats containing '/'.
    return (
        f"{device.protocol_ref.protocol}://"
        f"{device.protocol_ref.address}#{device.protocol_ref.device_id}"
    )


def parse_device_identifier(device: str) -> tuple[Protocol, str, str]:
    try:
        proto_raw, address_and_device = device.split("://", maxsplit=1)
    except ValueError as exc:
        raise ValueError(
            "Device identifier must be in format protocol://address#device_id"
        ) from exc

    if "#" in address_and_device:
        address, device_id = address_and_device.rsplit("#", maxsplit=1)
    else:
        # Backward-compatible fallback for older format.
        try:
            address, device_id = address_and_device.rsplit("/", maxsplit=1)
        except ValueError as exc:
            raise ValueError(
                "Device identifier must be in format protocol://address#device_id"
            ) from exc

    if not address or not device_id:
        raise ValueError(
            "Device identifier must be in format protocol://address#device_id"
        )

    try:
        protocol = Protocol(proto_raw)
    except ValueError as exc:
        raise ValueError(f"Unsupported protocol in identifier: {proto_raw}") from exc

    return protocol, address, device_id
