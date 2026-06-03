"""Direct bacpypes3 ReadProperty side-channel.

Bypasses BAC0's Who-Is / I-Am handshake by calling the underlying
bacpypes3 Application.read_property() directly. Used as a tertiary
fallback for devices that don't reply to Who-Is — for those, BAC0's
own read() also fails because it caches I-Am before reading.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bacpypes3.apdu import ErrorRejectAbortNack
from bacpypes3.basetypes import PropertyIdentifier
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier

logger = logging.getLogger(__name__)


class DirectReadMixin:
    """ReadProperty straight to a known address, no discovery."""

    bacnet: Any

    async def direct_read_property(
        self,
        device_address: str,
        object_type: str,
        instance: int,
        property_name: str,
        *,
        timeout: float = 5.0,
    ) -> Any | None:
        """Read a single property via bacpypes3, bypassing BAC0's Who-Is.

        Returns the raw property value, or None if the read fails.
        """
        if self.bacnet is None:
            raise RuntimeError("BACnet controller not initialized")

        app = self._bacpypes3_app()
        if app is None:
            logger.debug(
                "Direct read unavailable: bacpypes3 application handle not exposed"
            )
            return None

        try:
            response = await asyncio.wait_for(
                app.read_property(
                    Address(device_address),
                    ObjectIdentifier((object_type, instance)),
                    PropertyIdentifier(property_name),
                    None,
                ),
                timeout=timeout,
            )
        except (
            ErrorRejectAbortNack,
            TimeoutError,
            asyncio.TimeoutError,
            RuntimeError,
            OSError,
            ValueError,
            TypeError,
        ) as exc:
            logger.debug(
                "Direct read %s %s:%s.%s failed: %s",
                device_address,
                object_type,
                instance,
                property_name,
                exc,
            )
            return None

        if isinstance(response, ErrorRejectAbortNack):
            logger.debug(
                "Direct read %s %s:%s.%s returned error: %s",
                device_address,
                object_type,
                instance,
                property_name,
                response,
            )
            return None
        return response

    def _bacpypes3_app(self) -> Any | None:
        """Reach into BAC0 to grab the underlying bacpypes3 Application.

        BAC0 layout: bacnet -> this_application (BAC0Application) -> app (bacpypes3 Application).
        Returns None if the chain isn't there (e.g. in tests with a bare Mock).
        """
        this_application = getattr(self.bacnet, "this_application", None)
        if this_application is None:
            return None
        return getattr(this_application, "app", None)
