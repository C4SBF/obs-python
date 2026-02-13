"""BACnet object scan and read logic."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..types import BACnetDeviceIdentifier, BACnetObject, BACnetObjectIdentifier
from .constants import BACNET_ERRORS

logger = logging.getLogger(__name__)


class ObjectScanMixin:
    """Device object discovery and reads."""

    _initialized: bool
    bacnet: Any
    _scan_lock: asyncio.Lock
    _semaphore: asyncio.Semaphore

    async def scan_device_objects(
        self,
        device_address: str,
        device_id: int,
        max_instance: int = 1000,
        object_list: list[BACnetObjectIdentifier] | None = None,
        rpm_batch_size: int = 10,
    ) -> list[BACnetObject]:
        """Read all objects for a device."""
        if not self._initialized:
            await self.initialize()  # type: ignore[attr-defined]
        if self.bacnet is None:
            raise RuntimeError("BACnet controller not initialized")

        async with self._scan_lock:
            return await self._scan_device_objects_locked(
                device_address,
                device_id,
                max_instance,
                object_list,
                rpm_batch_size,
            )

    async def _scan_device_objects_locked(
        self,
        device_address: str,
        device_id: int,
        max_instance: int,
        object_list: list[BACnetObjectIdentifier] | None,
        rpm_batch_size: int,
    ) -> list[BACnetObject]:
        try:
            logger.info(
                "Starting object scan for device %s:%d", device_address, device_id
            )

            use_object_list = object_list is not None
            if object_list is None:
                object_list = []
                try:
                    obj_list_raw = await asyncio.wait_for(
                        self.bacnet.read(
                            f"{device_address} device:{device_id} objectList"
                        ),
                        timeout=10.0,
                    )
                    if obj_list_raw:
                        object_list = self._parse_object_list(obj_list_raw)  # type: ignore[attr-defined]
                        use_object_list = True
                except BACNET_ERRORS as exc:
                    logger.warning(
                        "Could not read objectList: %s. Falling back to instance scanning",
                        exc,
                    )

            object_types = [
                "analogValue",
                "binaryValue",
                "analogInput",
                "binaryInput",
                "analogOutput",
                "binaryOutput",
            ]

            all_objects: list[tuple[str, int]] = []
            if use_object_list and object_list:
                for obj_type in object_types:
                    all_objects.extend(
                        (obj_type, obj.instance)
                        for obj in object_list
                        if self._normalize_object_type(obj.object_type) == obj_type
                    )
            else:
                logger.info("Falling back to instance scanning (1-%d)", max_instance)
                for obj_type in object_types:
                    all_objects.extend(
                        (obj_type, i) for i in range(1, max_instance + 1)
                    )

            objects = await self.read_objects_rpm(
                device_address,
                device_id,
                all_objects,
                batch_size=rpm_batch_size,
            )

            discovered = [obj for obj in objects if obj is not None]
            logger.info("Object scan complete: Found %d total objects", len(discovered))
            return discovered

        except BACNET_ERRORS as exc:
            logger.error(
                "Error scanning device %s:%d: %s", device_address, device_id, exc
            )
            return []

    async def read_objects_rpm(
        self,
        device_address: str,
        device_id: int,
        objects: list[tuple[str, int]],
        batch_size: int = 10,
        properties: tuple[str, ...] = (
            "objectName",
            "presentValue",
            "description",
            "units",
        ),
    ) -> list[BACnetObject | None]:
        """Batched RPM with adaptive fallback to individual reads."""
        if not objects:
            return []

        results: list[BACnetObject | None] = [None] * len(objects)
        remaining = list(range(len(objects)))
        current_batch_size = batch_size
        use_rpm = True

        while remaining and use_rpm and current_batch_size >= 1:
            failed_indices: list[int] = []

            for batch_start in range(0, len(remaining), current_batch_size):
                batch_indices = remaining[
                    batch_start : batch_start + current_batch_size
                ]
                rpm_objects = {}
                for idx in batch_indices:
                    obj_type, instance = objects[idx]
                    rpm_objects[f"{obj_type}:{instance}"] = list(properties)

                rpm_result = await self.read_multiple(  # type: ignore[attr-defined]
                    device_address, rpm_objects
                )

                if rpm_result is None:
                    if current_batch_size > 1:
                        failed_indices.extend(batch_indices)
                        continue
                    use_rpm = False
                    failed_indices.extend(batch_indices)
                    break

                norm_lookup: dict[str, dict[str, Any]] = {}
                for raw_key, raw_value in rpm_result.items():
                    if not isinstance(raw_value, dict):
                        continue
                    norm_lookup[raw_key] = raw_value
                    if ":" in raw_key:
                        prefix, suffix = raw_key.rsplit(":", maxsplit=1)
                        normalized = self._normalize_object_type(prefix) + ":" + suffix
                        norm_lookup[normalized] = raw_value

                for idx in batch_indices:
                    obj_type, instance = objects[idx]
                    key = f"{obj_type}:{instance}"
                    props = norm_lookup.get(key)
                    if props is not None:
                        results[idx] = self._build_object_from_props(
                            device_address=device_address,
                            device_id=device_id,
                            object_type=obj_type,
                            instance=instance,
                            props=props,
                        )
                    else:
                        failed_indices.append(idx)

            remaining = failed_indices
            if remaining and use_rpm and current_batch_size > 1:
                current_batch_size = max(1, current_batch_size // 2)
                logger.info(
                    "RPM batch reduced to %d for %s", current_batch_size, device_address
                )
            elif remaining and use_rpm and current_batch_size <= 1:
                use_rpm = False

        if remaining:
            logger.info(
                "Individual reads for %d objects on %s", len(remaining), device_address
            )

            async def _read_single(idx: int) -> None:
                async with self._semaphore:
                    obj_type, instance = objects[idx]
                    results[idx] = await self._read_bacnet_object_unlocked(
                        device_address,
                        device_id,
                        obj_type,
                        instance,
                    )

            await asyncio.gather(*[_read_single(idx) for idx in remaining])

        return results

    def _build_object_from_props(
        self,
        *,
        device_address: str,
        device_id: int,
        object_type: str,
        instance: int,
        props: dict[str, Any],
    ) -> BACnetObject:
        device_identifier = BACnetDeviceIdentifier(
            address=device_address, device_id=device_id
        )
        object_identifier = BACnetObjectIdentifier(
            object_type=object_type, instance=instance
        )
        raw_units = props.get("units")
        return BACnetObject(
            uid=self._build_object_uid(  # type: ignore[attr-defined]
                device_address, device_id, object_type, instance
            ),
            device=device_identifier,
            object_identifier=object_identifier,
            name=str(props.get("objectName")) if props.get("objectName") else None,
            value=self._to_native(props.get("presentValue")),
            description=str(props.get("description"))
            if props.get("description")
            else None,
            units=str(raw_units) if raw_units is not None else None,
            unit_id=self._unit_id(raw_units),
            metadata={"source": "rpm"},
        )

    async def _read_bacnet_object_unlocked(
        self,
        device_address: str,
        device_id: int,
        object_type: str,
        instance: int,
    ) -> BACnetObject | None:
        if self.bacnet is None:
            raise RuntimeError("BACnet controller not initialized")
        try:
            name = await asyncio.wait_for(
                self.bacnet.read(
                    f"{device_address} {object_type}:{instance} objectName"
                ),
                timeout=5.0,
            )
            if name is None:
                return None

            try:
                value = await asyncio.wait_for(
                    self.bacnet.read(
                        f"{device_address} {object_type}:{instance} presentValue"
                    ),
                    timeout=5.0,
                )
            except BACNET_ERRORS:
                value = None

            try:
                description = await asyncio.wait_for(
                    self.bacnet.read(
                        f"{device_address} {object_type}:{instance} description"
                    ),
                    timeout=3.0,
                )
            except BACNET_ERRORS:
                description = None

            units: str | None = None
            unit_id: str | None = None
            if object_type.startswith("analog"):
                try:
                    units_code = await asyncio.wait_for(
                        self.bacnet.read(
                            f"{device_address} {object_type}:{instance} units"
                        ),
                        timeout=3.0,
                    )
                    units = str(units_code) if units_code is not None else None
                    unit_id = self._unit_id(units_code)
                except BACNET_ERRORS:
                    pass

            device_identifier = BACnetDeviceIdentifier(
                address=device_address,
                device_id=device_id,
            )
            object_identifier = BACnetObjectIdentifier(
                object_type=object_type,
                instance=instance,
            )
            return BACnetObject(
                uid=self._build_object_uid(  # type: ignore[attr-defined]
                    device_address, device_id, object_type, instance
                ),
                device=device_identifier,
                object_identifier=object_identifier,
                name=str(name) if name else None,
                value=self._to_native(value),
                description=str(description) if description else None,
                units=units,
                unit_id=unit_id,
                metadata={"source": "single_read"},
            )
        except BACNET_ERRORS as exc:
            logger.debug(
                "Error reading %s:%d from %s:%d: %s",
                object_type,
                instance,
                device_address,
                device_id,
                exc,
            )
            return None

    @staticmethod
    def _normalize_object_type(obj_type_str: str) -> str:
        if "-" not in obj_type_str:
            return obj_type_str
        parts = obj_type_str.split("-")
        return parts[0] + "".join(word.capitalize() for word in parts[1:])

    @staticmethod
    def _to_native(value: Any) -> bool | int | float | str | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return bool(value)
        if isinstance(value, float):
            return float(value)
        if isinstance(value, int):
            return int(value)
        return str(value)

    @staticmethod
    def _unit_id(units_code: Any) -> str | None:
        if units_code is None:
            return None
        if hasattr(units_code, "value") and isinstance(units_code.value, int):
            return str(units_code.value)
        if isinstance(units_code, (int, float)):
            return str(int(units_code))
        return str(units_code)
