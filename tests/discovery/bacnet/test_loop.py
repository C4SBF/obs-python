from __future__ import annotations

import asyncio

from obs.discovery.bacnet import _loop


def test_run_sync_executes_coroutine_and_returns_result() -> None:
    # given
    async def _work() -> str:
        return "ok"

    # when
    result = _loop.run_sync(_work(), timeout=2.0)

    # then
    assert result == "ok"


def test_run_sync_reuses_same_background_loop() -> None:
    # given
    async def _loop_id() -> int:
        return id(asyncio.get_running_loop())

    # when
    first = _loop.run_sync(_loop_id(), timeout=2.0)
    second = _loop.run_sync(_loop_id(), timeout=2.0)

    # then
    assert first == second


def test_ensure_loop_returns_loop_created_while_waiting_for_lock(monkeypatch) -> None:
    # given
    injected_loop = asyncio.new_event_loop()

    class InjectingLock:
        def __enter__(self):
            _loop._loop = injected_loop
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(_loop, "_loop", None)
    monkeypatch.setattr(_loop, "_lock", InjectingLock())

    # when
    result = _loop._ensure_loop()

    # then
    assert result is injected_loop
    injected_loop.close()
