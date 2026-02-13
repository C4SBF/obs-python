"""Shared async/sync bridge — persistent background event loop."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Coroutine
from typing import TypeVar

__all__ = ["run_sync"]

logger = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()

_T = TypeVar("_T")


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Return the persistent background event loop, creating it if needed."""
    global _loop

    if _loop is not None and not _loop.is_closed():
        return _loop

    with _lock:
        if _loop is not None and not _loop.is_closed():
            return _loop

        loop = asyncio.new_event_loop()

        def _run(lp: asyncio.AbstractEventLoop) -> None:
            asyncio.set_event_loop(lp)
            lp.run_forever()

        thread = threading.Thread(target=_run, args=(loop,), daemon=True)
        thread.start()

        _loop = loop
        logger.debug("Started persistent event loop in background thread")
        return loop


def run_sync(coro: Coroutine[object, object, _T], *, timeout: float) -> _T:
    """Run an async coroutine from a sync context and return its result."""
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)
