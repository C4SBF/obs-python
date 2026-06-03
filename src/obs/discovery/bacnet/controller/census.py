"""BACnet census + RPM helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..types import BACnetDevice, BACnetDeviceIdentifier, BACnetObjectIdentifier
from .constants import BACNET_ERRORS

logger = logging.getLogger(__name__)


class CensusMixin:
    """Device census and RPM helpers."""

    bacnet: Any

    async def read_device_census(
        self, device_address: str, device_id: int
    ) -> BACnetDevice:
        """Read device metadata and objectList — RPM with individual fallback."""
        if self.bacnet is None:
            raise RuntimeError("BACnet controller not initialized")

        device_name: str | None = None
        vendor: str | None = None
        model: str | None = None
        firmware: str | None = None
        object_list: list[BACnetObjectIdentifier] = []

        rpm_objects = {
            f"device:{device_id}": [
                "objectName",
                "vendorName",
                "modelName",
                "firmwareRevision",
                "objectList",
            ]
        }
        rpm_result = await self.read_multiple(device_address, rpm_objects)

        if rpm_result is not None:
            try:
                dev_key = f"device:{device_id}"
                if dev_key in rpm_result:
                    props = rpm_result[dev_key]
                    if props.get("objectName"):
                        device_name = str(props.get("objectName"))
                    if props.get("vendorName"):
                        vendor = str(props.get("vendorName"))
                    if props.get("modelName"):
                        model = str(props.get("modelName"))
                    if props.get("firmwareRevision"):
                        firmware = str(props.get("firmwareRevision"))
                    obj_list_raw = props.get("objectList")
                    if obj_list_raw:
                        object_list = self._parse_object_list(obj_list_raw)
            except (TypeError, ValueError, AttributeError) as exc:
                logger.debug("Error parsing RPM census result: %s", exc)

        if device_name is None:
            try:
                name = await asyncio.wait_for(
                    self.bacnet.read(f"{device_address} device:{device_id} objectName"),
                    timeout=5.0,
                )
                device_name = str(name) if name else None
            except BACNET_ERRORS:
                pass

        if vendor is None:
            try:
                vendor_name = await asyncio.wait_for(
                    self.bacnet.read(f"{device_address} device:{device_id} vendorName"),
                    timeout=5.0,
                )
                vendor = str(vendor_name) if vendor_name else None
            except BACNET_ERRORS:
                pass

        if model is None:
            try:
                model_name = await asyncio.wait_for(
                    self.bacnet.read(f"{device_address} device:{device_id} modelName"),
                    timeout=5.0,
                )
                model = str(model_name) if model_name else None
            except BACNET_ERRORS:
                pass

        if firmware is None:
            try:
                firmware_revision = await asyncio.wait_for(
                    self.bacnet.read(
                        f"{device_address} device:{device_id} firmwareRevision"
                    ),
                    timeout=5.0,
                )
                firmware = str(firmware_revision) if firmware_revision else None
            except BACNET_ERRORS:
                pass

        if not object_list:
            try:
                obj_list_raw = await asyncio.wait_for(
                    self.bacnet.read(f"{device_address} device:{device_id} objectList"),
                    timeout=10.0,
                )
                if obj_list_raw:
                    object_list = self._parse_object_list(obj_list_raw)
            except BACNET_ERRORS:
                pass

        identifier = BACnetDeviceIdentifier(address=device_address, device_id=device_id)
        return BACnetDevice(
            uid=self._build_device_uid(device_address, device_id),  # type: ignore[attr-defined]
            identifier=identifier,
            name=device_name,
            vendor=vendor,
            model=model,
            firmware=firmware,
            object_list=object_list,
        )

    async def read_multiple(
        self,
        device_address: str,
        objects: dict[str, list[str]],
        timeout: float = 10.0,
    ) -> dict[str, dict[str, Any]] | None:
        """Read multiple properties via RPM. Returns None if unsupported."""
        if self.bacnet is None:
            raise RuntimeError("BACnet controller not initialized")

        try:
            request_dict = {"address": device_address, "objects": objects}
            result = await asyncio.wait_for(
                self.bacnet.readMultiple(
                    "", request_dict=request_dict, timeout=timeout
                ),
                timeout=timeout + 2,
            )
            if isinstance(result, dict):
                return result
            return None
        except IndexError as exc:
            # BAC0.readMultiple() needs an I-Am cached before sending RPM and
            # indexes _iam[0]; devices that don't respond to Who-Is raise
            # IndexError here. Fall through so the caller can retry with
            # per-property read(), which doesn't require I-Am.
            logger.warning(
                "RPM unavailable for %s (no I-Am response from device): %s",
                device_address,
                exc,
            )
            return None
        except Exception as exc:
            error_name = type(exc).__name__
            if error_name in (
                "SegmentationNotSupported",
                "UnrecognizedService",
                "AbortPDU",
            ):
                logger.info("RPM not supported by %s: %s", device_address, error_name)
                return None
            if isinstance(exc, BACNET_ERRORS):
                logger.debug("RPM failed for %s: %s", device_address, exc)
                return None
            raise

    def _parse_object_list(self, object_list_raw: Any) -> list[BACnetObjectIdentifier]:
        parsed: list[BACnetObjectIdentifier] = []
        for obj in object_list_raw:
            try:
                if isinstance(obj, tuple) and len(obj) >= 2:
                    parsed.append(
                        BACnetObjectIdentifier(
                            object_type=str(obj[0]), instance=int(obj[1])
                        )
                    )
            except (TypeError, ValueError):
                continue
        return parsed
