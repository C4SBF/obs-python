"""BACnet controller package facade."""

from __future__ import annotations

import asyncio
import gc
import logging
import threading

from ..identity import LocalDeviceIdentity
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
    "set_default_local_device_identity",
    "get_default_local_device_identity",
    "BACnetController",
    "LocalDeviceIdentity",
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

# Identity used for every controller created without an explicit one. An
# application's BACnet identity is a process-wide fact: one IP/port hosts one
# device. Setting it once at startup covers controllers created internally by
# scan_network() and discover_objects(), which have no identity parameter.
_default_identity: LocalDeviceIdentity | None = None


def set_default_local_device_identity(identity: LocalDeviceIdentity | None) -> None:
    """Set the identity for controllers created from now on.

    Call this once at application startup, before the first
    :func:`get_bacnet_controller` call. Controllers that already exist keep
    the identity they were created with; requesting one of them with a
    different identity raises. ``None`` clears the default.
    :func:`clear_controller_cache` does not touch this value.
    """
    global _default_identity
    with _controller_lock:
        _default_identity = identity


def get_default_local_device_identity() -> LocalDeviceIdentity | None:
    """Return the identity set by :func:`set_default_local_device_identity`."""
    return _default_identity


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
    identity: LocalDeviceIdentity | None = None,
) -> BACnetController:
    """Get or create a controller instance scoped by transport parameters.

    The cache key is the transport only. One IP/port can host exactly one
    BACnet device, so ``identity`` describes that device; it does not select
    between devices. ``None`` means "use the default set by
    :func:`set_default_local_device_identity`, or BAC0's defaults if none".

    Raises:
        ValueError: A controller for this transport already exists with a
            different identity. BAC0 reads the identity once at start-up, so
            it cannot be changed on a live controller. Set the identity before
            the first call for this transport.
    """
    global _bacnet_controller
    key = _controller_key(
        client_ip=client_ip,
        bbmd_ip=bbmd_ip,
        bbmd_ttl=bbmd_ttl,
        max_concurrent=max_concurrent,
    )
    with _controller_lock:
        if identity is None:
            identity = _default_identity

        cached = _bacnet_controllers.get(key)
        if cached is not None:
            if identity is not None and cached.identity != identity:
                raise ValueError(
                    "A BACnet controller for this transport already exists with "
                    f"a different local device identity: {cached.identity!r} "
                    f"vs requested {identity!r}. Set the identity before the "
                    "first get_bacnet_controller() call, for example with "
                    "set_default_local_device_identity() at application startup."
                )
            return cached

        created = BACnetController(
            client_ip=client_ip,
            bbmd_ip=bbmd_ip,
            bbmd_ttl=bbmd_ttl,
            max_concurrent=max_concurrent,
            identity=identity,
        )
        _bacnet_controllers[key] = created
        # Legacy compatibility handle used by existing tests/tools.
        if _bacnet_controller is None:
            _bacnet_controller = created
        return created
