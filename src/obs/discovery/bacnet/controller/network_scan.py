"""BACnet network scan logic."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..types import BACnetDevice
from .constants import BACNET_ERRORS

logger = logging.getLogger(__name__)


class NetworkScanMixin:
    """Who-Is network scan + census fanout."""

    _initialized: bool
    bacnet: Any
    _semaphore: Any

    async def scan_network(self, timeout: int = 30) -> list[BACnetDevice]:
        """Who-Is broadcast + concurrent census reads."""
        if not self._initialized:
            await self.initialize()  # type: ignore[attr-defined]
        if self.bacnet is None:
            raise RuntimeError("BACnet controller not initialized")

        try:
            logger.info("Starting network scan (Who-Is broadcast)...")
            who_is_responses = await self.bacnet.who_is()

            if not who_is_responses:
                logger.info("Network scan complete: 0 devices found")
                return []

            logger.info(
                "Found %d devices, reading census data...", len(who_is_responses)
            )

            own_device_id = None
            try:
                own_device_id = self.bacnet.localDevice.objectIdentifier[1]
            except (AttributeError, IndexError, TypeError):
                pass

            raw_devices: list[tuple[int, str]] = []
            for response in who_is_responses:
                try:
                    device_id = int(response.iAmDeviceIdentifier[1])
                    if device_id == own_device_id:
                        continue
                    raw_devices.append((device_id, str(response.pduSource)))
                except (ValueError, TypeError, AttributeError, IndexError) as exc:
                    logger.debug("Error parsing Who-Is response: %s", exc)

            async def _read_census(
                device_id: int, device_address: str
            ) -> BACnetDevice | None:
                try:
                    async with self._semaphore:
                        return await self.read_device_census(  # type: ignore[attr-defined]
                            device_address, device_id
                        )
                except BACNET_ERRORS as exc:
                    logger.warning(
                        "Failed to read census for %s:%d: %s",
                        device_address,
                        device_id,
                        exc,
                    )
                    return None

            results = await asyncio.gather(
                *[
                    _read_census(device_id, address)
                    for device_id, address in raw_devices
                ]
            )
            devices = [device for device in results if device is not None]
            logger.info("Network scan complete: %d devices found", len(devices))
            return devices

        except BACNET_ERRORS as exc:
            logger.error("Error during network scan: %s", exc)
            return []
