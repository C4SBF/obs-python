"""BACnet controller core lifecycle."""

from __future__ import annotations

import asyncio
import logging
import socket
import sys
from io import StringIO
from typing import Any

from ..identity import LocalDeviceIdentity, default_application_software_version
from .census import CensusMixin
from .direct_read import DirectReadMixin
from .network_scan import NetworkScanMixin
from .object_scan import ObjectScanMixin

logger = logging.getLogger(__name__)


class BACnetController(NetworkScanMixin, CensusMixin, ObjectScanMixin, DirectReadMixin):
    """Singleton BAC0 wrapper for all BACnet operations.

    Args:
        client_ip: Local address to bind, as ``ip/prefix``. Auto-detected when
            omitted.
        bbmd_ip: BBMD to register with as a foreign device, if any.
        bbmd_ttl: Foreign device registration lifetime in seconds.
        max_concurrent: Upper bound on concurrent BACnet requests.
        identity: What this process announces itself as on the BACnet network.
            ``None`` keeps BAC0's defaults (random device instance, name
            ``"BAC0"``). The identity is read once, in :meth:`initialize`; it
            cannot change on a live BAC0 instance.
    """

    def __init__(
        self,
        client_ip: str | None = None,
        bbmd_ip: str | None = None,
        bbmd_ttl: int = 900,
        max_concurrent: int = 10,
        identity: LocalDeviceIdentity | None = None,
    ):
        self.bacnet: Any = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(max_concurrent)
        self._scan_lock = asyncio.Lock()

        self.client_ip = client_ip or self._auto_detect_ip()
        self.bbmd_ip = bbmd_ip or ""
        self.bbmd_ttl = bbmd_ttl
        self.identity = identity

        logger.info("BACnet controller created - client_ip: %s", self.client_ip)
        if self.bbmd_ip:
            logger.info("BBMD configured: %s (TTL=%ss)", self.bbmd_ip, self.bbmd_ttl)
        if self.identity is not None:
            logger.info("Local device identity: %s", self.identity)

    @staticmethod
    def _auto_detect_ip() -> str:
        """Best-effort local address discovery; falls back to wildcard."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return f"{sock.getsockname()[0]}/24"
        except OSError as exc:
            logger.warning("Could not auto-detect client IP: %s", exc)
            return "0.0.0.0/24"

    @staticmethod
    def _build_device_uid(address: str, device_id: int) -> str:
        return f"bacnet://{address}/{device_id}"

    @staticmethod
    def _build_object_uid(
        address: str, device_id: int, object_type: str, instance: int
    ) -> str:
        return f"bacnet://{address}/{device_id}/{object_type}:{instance}"

    def _bac0_lite_kwargs(self) -> dict[str, Any]:
        """Build the keyword arguments for ``BAC0.lite()``.

        Transport first, then the identity fields BAC0 honors. See
        ``LocalDeviceIdentity.bac0_lite_kwargs`` for which those are.
        """
        kwargs: dict[str, Any] = {"ip": self.client_ip, "port": 47808}
        bbmd_ip = self.bbmd_ip.strip() if self.bbmd_ip else None
        if bbmd_ip:
            kwargs["bbmdAddress"] = bbmd_ip
            kwargs["bbmdTTL"] = self.bbmd_ttl
        if self.identity is not None:
            kwargs.update(self.identity.bac0_lite_kwargs())
        if "deviceId" not in kwargs:
            # BAC0 picks 3056177 + random(0..1000). Other devices address this
            # node by that number, so every restart looks like a new device to
            # them. Worth a warning even though it is the historical default.
            logger.warning(
                "No device_id set; this BACnet device will announce a new random "
                "device instance on every start. Set a stable one with "
                "LocalDeviceIdentity(device_id=...) via "
                "set_default_local_device_identity()."
            )
        return kwargs

    def _apply_device_object_properties(self) -> None:
        """Write the Device Object properties ``BAC0.lite()`` does not apply.

        BAC0 accepts ``vendorName``, ``description``, ``location`` and
        ``firmwareRevision`` as arguments but never uses them, and it gives
        no way to set ``applicationSoftwareVersion`` at all. bacpypes3 exposes
        the live ``DeviceObject``, so these are written there directly, right
        after BAC0 has built it and before the device is reported ready.

        A property that cannot be written is logged and skipped. These are
        labels; a failed label must not take down the BACnet node.
        """
        properties: dict[str, str] = {}
        if self.identity is not None:
            properties = self.identity.device_object_properties()
        properties.setdefault(
            "applicationSoftwareVersion", default_application_software_version()
        )

        device_object = getattr(self._bacpypes3_app(), "device_object", None)
        if device_object is None:
            logger.warning(
                "Local Device Object not reachable; properties not applied: %s",
                sorted(properties),
            )
            return

        for attr, value in properties.items():
            try:
                setattr(device_object, attr, value)
            except (AttributeError, TypeError, ValueError) as exc:
                logger.warning(
                    "Could not set Device Object %s=%r: %s", attr, value, exc
                )

    async def initialize(self) -> bool:
        """Initialize the BAC0 connection. Returns True on success."""
        if self._initialized and self.bacnet:
            return True

        async with self._init_lock:
            if self._initialized and self.bacnet:
                return True

            try:
                logger.info("Initializing BAC0 instance...")
                import BAC0

                original_stdout = sys.stdout
                original_stderr = sys.stderr
                sys.stdout = StringIO()
                sys.stderr = StringIO()

                try:
                    BAC0.log_level("silence")
                    self.bacnet = BAC0.lite(**self._bac0_lite_kwargs())
                    self._apply_device_object_properties()

                    BAC0.log_level("silence")
                    import logging as log

                    for name in ("BAC0", "bacpypes", "bacpypes3"):
                        log.getLogger(name).setLevel(log.CRITICAL)
                finally:
                    sys.stdout = original_stdout
                    sys.stderr = original_stderr

                await asyncio.sleep(2)
                self._initialized = True
                logger.info("BAC0 instance initialized successfully on port 47808")
                return True

            except (
                ImportError,
                ModuleNotFoundError,
                RuntimeError,
                TimeoutError,
                OSError,
                ValueError,
                TypeError,
                AttributeError,
            ) as exc:
                logger.error("Error initializing BAC0: %s", exc)
                return False
