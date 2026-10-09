"""Deterministic regressions for lost cancellation (CPython gh-86296).

Each scenario requests ``cancel()`` in the very event-loop iteration in which
the awaited work completes. Before Python 3.12, ``asyncio.wait_for`` returned
the result and silently dropped the cancellation.
"""

import asyncio
import socket
import threading

import pytest
from app import async_utils, providers
from app.ai_clients import ProviderCallGate
from app.main import _run_until_client_disconnect


def run(coroutine):
    return asyncio.run(coroutine)


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def test_gate_queue_wait_cancelled_as_slot_frees_makes_no_provider_call() -> None:
    async def scenario() -> None:
        gate = ProviderCallGate(1, per_client_limit=1)
        semaphore = gate._semaphore_for_loop()
        await semaphore.acquire()  # another request holds the only slot
        called = False

        async def paid_call() -> str:
            nonlocal called
            called = True
            return "response"

        request = asyncio.ensure_future(
            gate.run(paid_call, "test", deadline_seconds=5, client_key="client")
        )
        await settle()  # request is now queued on the semaphore

        semaphore.release()  # wakes the queued acquire ...
        request.cancel()  # ... and the client disconnects in the same iteration
        done, _ = await asyncio.wait({request}, timeout=5)

        assert request in done
        assert request.cancelled(), "cancellation was swallowed"
        assert called is False, "paid provider call made for a cancelled request"

        # The slot and the per-client reservation were released exactly once.
        assert gate._client_counts == {}
        await asyncio.wait_for(gate.run(paid_call, "test", 1, client_key="client"), 5)
        assert called is True
        assert semaphore.locked() is False

    run(scenario())


def test_azure_dns_wait_cancelled_as_lookup_completes_is_not_swallowed(monkeypatch) -> None:
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(providers, "_AZURE_DNS_LOOKUP_SLOTS", slots)

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        lookup: asyncio.Future = loop.create_future()
        monkeypatch.setattr(loop, "run_in_executor", lambda *_a: lookup, raising=False)

        request = asyncio.ensure_future(
            providers._assert_public_azure_endpoint("https://resource.openai.azure.com")
        )
        await settle()  # request is waiting on the lookup

        lookup.set_result([(socket.AF_INET, 0, 0, "", ("1.1.1.1", 443))])
        request.cancel()
        done, _ = await asyncio.wait({request}, timeout=5)

        assert request in done
        assert request.cancelled(), "cancellation was swallowed; request would go on to the API"

        await settle()
        assert slots.acquire(blocking=False), "DNS slot callback did not fire"
        slots.release()

    run(scenario())


def test_disconnect_poll_cancelled_as_operation_completes_is_not_swallowed() -> None:
    # Harmless on old Pythons (the operation had already finished), but pinned
    # so the shared helper keeps the same behaviour on every interpreter.
    async def scenario() -> None:
        gate_open = asyncio.Event()

        class Connected:
            async def is_disconnected(self) -> bool:
                return False

        async def operation() -> str:
            await gate_open.wait()
            return "done"

        request = asyncio.ensure_future(_run_until_client_disconnect(Connected(), operation))
        await settle()
        gate_open.set()
        await asyncio.sleep(0)  # operation task finishes its step
        request.cancel()
        done, _ = await asyncio.wait({request}, timeout=5)
        assert request in done and request.cancelled()

    run(scenario())


def test_gate_deadline_still_maps_to_domain_errors() -> None:
    async def scenario() -> None:
        gate = ProviderCallGate(1)

        async def slow() -> None:
            await asyncio.sleep(10)

        with pytest.raises(providers.ProviderTimeoutError):
            await gate.run(slow, "test", deadline_seconds=0.01)
        assert gate._semaphore_for_loop().locked() is False

    run(scenario())


# --- helper semantics -------------------------------------------------------


def test_cancel_safe_cancels_inner_on_timeout_and_on_caller_cancel() -> None:
    async def scenario() -> None:
        state: list[str] = []

        async def inner() -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                state.append("cancelled")
                raise

        with pytest.raises(asyncio.TimeoutError):
            await async_utils.wait_for_cancel_safe(inner(), 0.01)
        assert state == ["cancelled"]

        outer = asyncio.ensure_future(async_utils.wait_for_cancel_safe(inner(), 5))
        await settle()
        outer.cancel()
        await asyncio.wait({outer})
        assert outer.cancelled() and state == ["cancelled", "cancelled"]

    run(scenario())


def test_cancel_safe_propagates_result_and_exceptions() -> None:
    async def ok() -> int:
        return 7

    async def boom() -> int:
        raise ValueError("x")

    async def scenario() -> None:
        assert await async_utils.wait_for_cancel_safe(ok(), 1) == 7
        with pytest.raises(ValueError):
            await async_utils.wait_for_cancel_safe(boom(), 1)

    run(scenario())


def test_shielded_wait_never_cancels_the_future() -> None:
    async def scenario() -> None:
        future: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        with pytest.raises(asyncio.TimeoutError):
            await async_utils.wait_for_shielded(future, 0.01)
        assert not future.done()

        outer = asyncio.ensure_future(async_utils.wait_for_shielded(future, 5))
        await settle()
        outer.cancel()
        await asyncio.wait({outer})
        assert outer.cancelled() and not future.done()

        future.set_result(3)
        assert await async_utils.wait_for_shielded(future, 1) == 3

    run(scenario())
