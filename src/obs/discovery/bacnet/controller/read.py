"""BACnet point value reading operations."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..types import BACnetDeviceIdentifier, BACnetObject, BACnetObjectIdentifier
from .constants import BACNET_ERRORS

logger = logging.getLogger(__name__)


class ReadMixin:
    """Point value reading operations."""

    _initialized: bool
    bacnet: Any
    _semaphore: asyncio.Semaphore

    async def read_point(
        self,
        device_address: str,
        device_id: int,
        object_type: str,
        instance: int,
        timeout: float = 5.0,
    ) -> BACnetObject | None:
        """Read a single BACnet point's present value.

        Args:
            device_address: IP address of the BACnet device.
            device_id: BACnet device ID.
            object_type: Object type (e.g., "analogValue").
            instance: Object instance number.
            timeout: Read timeout in seconds.

        Returns:
            BACnetObject with current value, or None if read failed.
        """
        if not self._initialized:
            await self.initialize()  # type: ignore[attr-defined]
        if self.bacnet is None:
            raise RuntimeError("BACnet controller not initialized")

        async with self._semaphore:
            return await self._read_point_unlocked(
                device_address, device_id, object_type, instance, timeout
            )

    async def _read_point_unlocked(
        self,
        device_address: str,
        device_id: int,
        object_type: str,
        instance: int,
        timeout: float = 5.0,
    ) -> BACnetObject | None:
        """Read a single point without semaphore (for internal batch use)."""
        try:
            # Read presentValue
            value = await asyncio.wait_for(
                self.bacnet.read(
                    f"{device_address} {object_type}:{instance} presentValue"
                ),
                timeout=timeout,
            )

            # Optionally read name for context
            name: str | None = None
            try:
                name_raw = await asyncio.wait_for(
                    self.bacnet.read(
                        f"{device_address} {object_type}:{instance} objectName"
                    ),
                    timeout=3.0,
                )
                name = str(name_raw) if name_raw else None
            except BACNET_ERRORS:
                pass

            # Read units for analog objects
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
                    unit_id = self._unit_id(units_code)  # type: ignore[attr-defined]
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
                name=name,
                value=self._to_native(value),  # type: ignore[attr-defined]
                units=units,
                unit_id=unit_id,
                metadata={"source": "read_point"},
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

    async def read_points(
        self,
        device_address: str,
        device_id: int,
        points: list[tuple[str, int]],
        timeout: float = 10.0,
    ) -> list[BACnetObject | None]:
        """Read multiple BACnet point values using RPM with fallback.

        Args:
            device_address: IP address of the BACnet device.
            device_id: BACnet device ID.
            points: List of (object_type, instance) tuples to read.
            timeout: RPM timeout in seconds.

        Returns:
            List of BACnetObject (or None for failed reads), same order as input.
        """
        if not self._initialized:
            await self.initialize()  # type: ignore[attr-defined]
        if self.bacnet is None:
            raise RuntimeError("BACnet controller not initialized")

        if not points:
            return []

        results: list[BACnetObject | None] = [None] * len(points)

        # Try RPM first for efficiency
        rpm_objects = {}
        for obj_type, instance in points:
            rpm_objects[f"{obj_type}:{instance}"] = [
                "presentValue",
                "objectName",
                "units",
            ]

        rpm_result = await self.read_multiple(device_address, rpm_objects, timeout)  # type: ignore[attr-defined]

        failed_indices: list[int] = []
        if rpm_result is not None:
            # Build normalized lookup
            norm_lookup: dict[str, dict[str, Any]] = {}
            for raw_key, raw_value in rpm_result.items():
                if not isinstance(raw_value, dict):
                    continue
                norm_lookup[raw_key] = raw_value
                if ":" in raw_key:
                    prefix, suffix = raw_key.rsplit(":", maxsplit=1)
                    normalized = self._normalize_object_type(prefix) + ":" + suffix  # type: ignore[attr-defined]
                    norm_lookup[normalized] = raw_value

            for idx, (obj_type, instance) in enumerate(points):
                key = f"{obj_type}:{instance}"
                props = norm_lookup.get(key)
                if props is not None:
                    results[idx] = self._build_read_result(
                        device_address=device_address,
                        device_id=device_id,
                        object_type=obj_type,
                        instance=instance,
                        props=props,
                    )
                else:
                    failed_indices.append(idx)
        else:
            # RPM not supported, fall back to individual reads
            failed_indices = list(range(len(points)))

        # Individual reads for failures
        if failed_indices:
            logger.debug(
                "Individual reads for %d points on %s",
                len(failed_indices),
                device_address,
            )

            async def _read_single(idx: int) -> None:
                async with self._semaphore:
                    obj_type, instance = points[idx]
                    results[idx] = await self._read_point_unlocked(
                        device_address, device_id, obj_type, instance
                    )

            await asyncio.gather(*[_read_single(idx) for idx in failed_indices])

        return results

    def _build_read_result(
        self,
        *,
        device_address: str,
        device_id: int,
        object_type: str,
        instance: int,
        props: dict[str, Any],
    ) -> BACnetObject:
        """Build BACnetObject from RPM read result."""
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
            value=self._to_native(props.get("presentValue")),  # type: ignore[attr-defined]
            units=str(raw_units) if raw_units is not None else None,
            unit_id=self._unit_id(raw_units),  # type: ignore[attr-defined]
            metadata={"source": "rpm_read"},
        )
