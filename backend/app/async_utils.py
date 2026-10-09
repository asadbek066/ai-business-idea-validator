"""Timeout helpers that never swallow the caller's cancellation.

Before Python 3.12, ``asyncio.wait_for(aw, timeout)`` returns the inner result
and drops the caller's ``CancelledError`` when the awaited work completes in
the same event-loop iteration in which ``cancel()`` arrives (CPython
gh-86296). For this backend that would let a request whose client has already
gone continue on to a paid provider call. ``asyncio.timeout()`` would fix it
but only exists on 3.11+, and this project supports 3.10.

``asyncio.wait()`` has no such race: it raises ``CancelledError`` in the caller
without consuming the inner result, so both helpers are built on it and behave
identically on every supported interpreter.
"""

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")


async def _cancel_and_drain(future: "asyncio.Future[T]") -> None:
    """Cancel ``future``, wait for it to finish, and retrieve any exception."""

    future.cancel()
    await asyncio.wait({future})
    if not future.cancelled():
        future.exception()  # mark retrieved; avoids "exception never retrieved"


async def _wait_for(future: "asyncio.Future[T]", timeout: float, *, cancel_inner: bool) -> T:
    try:
        done, _ = await asyncio.wait({future}, timeout=timeout)
    except asyncio.CancelledError:
        if cancel_inner:
            await _cancel_and_drain(future)
        raise
    if future in done:
        return future.result()
    if cancel_inner:
        await _cancel_and_drain(future)
        # Like wait_for: work that finished while being cancelled still wins.
        if not future.cancelled():
            return future.result()
    raise asyncio.TimeoutError


async def wait_for_cancel_safe(awaitable: Awaitable[T], timeout: float) -> T:
    """Drop-in for ``asyncio.wait_for`` that cannot lose the caller's cancel.

    On timeout, or when the caller is cancelled, the inner work is cancelled
    and awaited before returning, as ``wait_for`` does. If the caller is
    cancelled, a result produced in the same iteration is discarded, so
    callers that must release a resource acquired by the inner work should
    record it with a side-effect flag set inside the awaited coroutine.
    Raises ``asyncio.TimeoutError`` on timeout.
    """

    return await _wait_for(asyncio.ensure_future(awaitable), timeout, cancel_inner=True)


async def wait_for_shielded(future: "asyncio.Future[T]", timeout: float) -> T:
    """Equivalent of ``wait_for(shield(future), timeout)`` without the race.

    The future is never cancelled by a timeout or by the caller's
    cancellation; it keeps running and its owner remains responsible for it.
    Raises ``asyncio.TimeoutError`` on timeout.
    """

    return await _wait_for(future, timeout, cancel_inner=False)
