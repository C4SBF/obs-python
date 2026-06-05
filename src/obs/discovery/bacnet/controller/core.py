"""BACnet controller core lifecycle."""

from __future__ import annotations

import asyncio
import logging
import socket
import sys
from io import StringIO
from typing import Any

from .census import CensusMixin
from .direct_read import DirectReadMixin
from .network_scan import NetworkScanMixin
from .object_scan import ObjectScanMixin

logger = logging.getLogger(__name__)


class BACnetController(NetworkScanMixin, CensusMixin, ObjectScanMixin, DirectReadMixin):
    """Singleton BAC0 wrapper for all BACnet operations."""

    def __init__(
        self,
        client_ip: str | None = None,
        bbmd_ip: str | None = None,
        bbmd_ttl: int = 900,
        max_concurrent: int = 10,
    ):
        self.bacnet: Any = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(max_concurrent)
        self._scan_lock = asyncio.Lock()

        self.client_ip = client_ip or self._auto_detect_ip()
        self.bbmd_ip = bbmd_ip or ""
        self.bbmd_ttl = bbmd_ttl

        logger.info("BACnet controller created - client_ip: %s", self.client_ip)
        if self.bbmd_ip:
            logger.info("BBMD configured: %s (TTL=%ss)", self.bbmd_ip, self.bbmd_ttl)

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
                    bbmd_ip = self.bbmd_ip.strip() if self.bbmd_ip else None

                    if bbmd_ip:
                        self.bacnet = BAC0.lite(
                            ip=self.client_ip,
                            port=47808,
                            bbmdAddress=bbmd_ip,
                            bbmdTTL=self.bbmd_ttl,
                        )
                    else:
                        self.bacnet = BAC0.lite(ip=self.client_ip, port=47808)

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
