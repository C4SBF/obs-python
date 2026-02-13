"""Shared BACnet controller constants."""

from __future__ import annotations

from bacpypes3.apdu import ErrorRejectAbortNack

BACNET_OPERATION_TIMEOUT = 150
BACNET_ERRORS: tuple[type[BaseException], ...] = (
    RuntimeError,
    TimeoutError,
    OSError,
    ValueError,
    TypeError,
    ErrorRejectAbortNack,
)
