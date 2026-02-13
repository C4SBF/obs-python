"""BACnet controller package facade."""

from __future__ import annotations

import asyncio
import gc
import logging
import threading

from ..types import (
    BACnetDevice,
    BACnetDeviceIdentifier,
    BACnetObject,
    BACnetObjectIdentifier,
)
from .constants import BACNET_ERRORS, BACNET_OPERATION_TIMEOUT
from .core import BACnetController

__all__ = [
    "get_bacnet_controller",
    "clear_controller_cache",
    "BACnetController",
    "BACnetDevice",
    "BACnetDeviceIdentifier",
    "BACnetObject",
    "BACnetObjectIdentifier",
    "BACNET_OPERATION_TIMEOUT",
    "BACNET_ERRORS",
]

logger = logging.getLogger(__name__)

_bacnet_controller: BACnetController | None = None
_bacnet_controllers: dict[
    tuple[str | None, str | None, int, int], BACnetController
] = {}
_controller_lock = threading.Lock()


def _controller_key(
    *,
    client_ip: str | None,
    bbmd_ip: str | None,
    bbmd_ttl: int,
    max_concurrent: int,
) -> tuple[str | None, str | None, int, int]:
    return (client_ip, bbmd_ip, bbmd_ttl, max_concurrent)


def clear_controller_cache() -> None:
    """Clear the cached BACnet controller and disconnect BAC0."""
    global _bacnet_controller, _bacnet_controllers
    controllers: list[BACnetController]
    with _controller_lock:
        controllers = list(_bacnet_controllers.values())
        if _bacnet_controller is not None:
            controllers.append(_bacnet_controller)
        _bacnet_controllers = {}
        _bacnet_controller = None

    seen: set[int] = set()
    for controller in controllers:
        if id(controller) in seen:
            continue
        seen.add(id(controller))
        try:
            bacnet_instance = getattr(controller, "bacnet", None)
            if bacnet_instance:
                from .._loop import _loop as bg_loop

                if bg_loop and not bg_loop.is_closed():

                    async def cleanup() -> None:
                        try:
                            await bacnet_instance.disconnect()
                        except (RuntimeError, TimeoutError, OSError) as exc:
                            logger.warning("Error in cleanup: %s", exc)

                    coro = cleanup()
                    try:
                        future = asyncio.run_coroutine_threadsafe(coro, bg_loop)
                        future.result(timeout=60.0)
                    except (RuntimeError, TimeoutError, OSError) as exc:
                        logger.warning("Cleanup failed: %s", exc)
                    finally:
                        coro.close()

            controller.bacnet = None
            controller._initialized = False
            controller._semaphore = None  # type: ignore[assignment]
        except (RuntimeError, TimeoutError, OSError, AttributeError, TypeError) as exc:
            logger.warning("Error during BAC0 cleanup: %s", exc)

    gc.collect()
    logger.info("Cleared BACnet controller cache")


def get_bacnet_controller(
    client_ip: str | None = None,
    bbmd_ip: str | None = None,
    bbmd_ttl: int = 900,
    max_concurrent: int = 10,
) -> BACnetController:
    """Get or create a controller instance scoped by transport parameters."""
    global _bacnet_controller
    key = _controller_key(
        client_ip=client_ip,
        bbmd_ip=bbmd_ip,
        bbmd_ttl=bbmd_ttl,
        max_concurrent=max_concurrent,
    )
    with _controller_lock:
        cached = _bacnet_controllers.get(key)
        if cached is not None:
            return cached

        created = BACnetController(
            client_ip=client_ip,
            bbmd_ip=bbmd_ip,
            bbmd_ttl=bbmd_ttl,
            max_concurrent=max_concurrent,
        )
        _bacnet_controllers[key] = created
        # Legacy compatibility handle used by existing tests/tools.
        if _bacnet_controller is None:
            _bacnet_controller = created
        return created
