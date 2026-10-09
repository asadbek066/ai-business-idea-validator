import asyncio

import httpx
import pytest
from app import ai_clients, main
from app.ai_clients import ProviderCallGate
from app.main import SlidingWindowLimiter
from app.providers import (
    AIProvider,
    ProviderBusyError,
    ProviderClientLimitError,
    ProviderRequestError,
)


SCENARIO_TIMEOUT = 5.0


def run(coroutine):
    """Run a scenario, failing in seconds instead of waiting on real provider timeouts."""

    return asyncio.run(asyncio.wait_for(coroutine, timeout=SCENARIO_TIMEOUT))


async def _wait_for(predicate, attempts: int = 200) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached")


def test_one_client_cannot_exceed_its_limit_while_others_are_served() -> None:
    async def scenario() -> None:
        gate = ProviderCallGate(4, per_client_limit=2)
        started = 0
        release = asyncio.Event()

        async def blocking() -> str:
            nonlocal started
            started += 1
            await release.wait()
            return "ok"

        hogs = [
            asyncio.create_task(gate.run(blocking, "t", 1, client_key="1.1.1.1")) for _ in range(2)
        ]
        await _wait_for(lambda: started == 2)

        # Third call from the same client is refused and takes no global slot.
        with pytest.raises(ProviderClientLimitError):
            await gate.run(blocking, "t", 1, client_key="1.1.1.1")
        assert started == 2

        # Another client is still served while the hog holds its two slots.
        other = [
            asyncio.create_task(gate.run(blocking, "t", 1, client_key="2.2.2.2")) for _ in range(2)
        ]
        await _wait_for(lambda: started == 4)
        release.set()
        assert await asyncio.gather(*hogs, *other) == ["ok"] * 4
        assert gate._client_counts == {}

    run(scenario())


def test_client_limit_error_is_checked_before_global_capacity(monkeypatch) -> None:
    async def scenario() -> None:
        gate = ProviderCallGate(1, per_client_limit=1)
        release = asyncio.Event()
        entered = asyncio.Event()

        async def blocking() -> None:
            entered.set()
            await release.wait()

        first = asyncio.create_task(gate.run(blocking, "t", 1, client_key="a"))
        await entered.wait()
        # Same client: per-client error (immediately), not the global busy timeout.
        monkeypatch.setattr(ai_clients, "PROVIDER_QUEUE_TIMEOUT_SECONDS", 5)
        with pytest.raises(ProviderClientLimitError):
            await asyncio.wait_for(gate.run(blocking, "t", 1, client_key="a"), timeout=1)
        release.set()
        await first

    run(scenario())


def test_slots_released_on_provider_error_and_map_is_emptied() -> None:
    async def scenario() -> None:
        gate = ProviderCallGate(4, per_client_limit=1)

        async def boom() -> None:
            raise ProviderRequestError("t")

        for _ in range(3):
            with pytest.raises(ProviderRequestError):
                await gate.run(boom, "t", 1, client_key="a")
        assert gate._client_counts == {}
        assert await gate.run(lambda: asyncio.sleep(0, "fine"), "t", 1, client_key="a") == "fine"

    run(scenario())


def test_slots_released_on_cancellation() -> None:
    async def scenario() -> None:
        gate = ProviderCallGate(1, per_client_limit=1)
        entered = asyncio.Event()

        async def hang() -> None:
            entered.set()
            await asyncio.sleep(60)

        task = asyncio.create_task(gate.run(hang, "t", 60, client_key="a"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate._client_counts == {}
        # Global slot was released too.
        assert await gate.run(lambda: asyncio.sleep(0, "ok"), "t", 1, client_key="b") == "ok"

    run(scenario())


def test_queued_cancellation_and_busy_timeout_release_client_slot(monkeypatch) -> None:
    async def scenario() -> None:
        gate = ProviderCallGate(1, per_client_limit=2)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocking() -> None:
            entered.set()
            await release.wait()

        first = asyncio.create_task(gate.run(blocking, "t", 1, client_key="a"))
        await entered.wait()
        monkeypatch.setattr(ai_clients, "PROVIDER_QUEUE_TIMEOUT_SECONDS", 0.01)
        with pytest.raises(ProviderBusyError):
            await gate.run(blocking, "t", 1, client_key="b")
        assert gate._client_counts == {"a": 1}
        release.set()
        await first
        assert gate._client_counts == {}

    run(scenario())


def test_calls_without_client_key_are_not_tracked() -> None:
    async def scenario() -> None:
        gate = ProviderCallGate(2, per_client_limit=1)
        results = await asyncio.gather(
            *(gate.run(lambda: asyncio.sleep(0, 1), "t", 5) for _ in range(2))
        )
        assert results == [1, 1]
        assert gate._client_counts == {}

    run(scenario())


class _Blocking(AIProvider):
    provider_name = "Fake"

    def __init__(self, release: asyncio.Event) -> None:
        self.release = release

    async def analyze(self, idea: str) -> tuple[str, str]:
        await self.release.wait()
        return (
            '{"market_potential":"m","risks":"r","first_steps":"s","verdict":"v"}',
            "openai",
        )

    async def validate(self) -> tuple[bool, str]:
        await self.release.wait()
        return True, "openai"


def _body(path: str) -> dict[str, object]:
    body: dict[str, object] = {
        "ai_providers": {
            "openai": {"enabled": True, "model": "gpt-4o-mini", "api_key": "k" * 12},
            "azure_openai": {"enabled": False},
            "gemini": {"enabled": False},
            "claude": {"enabled": False},
        },
    }
    if path == "/analyze-idea":
        body["idea"] = "A useful product"
    return body


@pytest.mark.parametrize("path", ["/analyze-idea", "/validate-provider"])
def test_endpoint_returns_429_with_retry_after_for_over_limit_client(monkeypatch, path) -> None:
    monkeypatch.setattr(main, "ANALYZE_LIMITER", SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(main, "VALIDATE_LIMITER", SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(ai_clients, "PROVIDER_CALL_GATE", ProviderCallGate(4, per_client_limit=1))
    # Keep any regression-induced wait short; the happy path never reaches these.
    monkeypatch.setattr(ai_clients, "PROVIDER_QUEUE_TIMEOUT_SECONDS", 0.5)

    async def scenario():
        release = asyncio.Event()
        monkeypatch.setattr(
            ai_clients, "_get_selected_provider", lambda _: (_Blocking(release), "openai")
        )

        def client(peer: str) -> httpx.AsyncClient:
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=main.app, client=(peer, 1)),
                base_url="http://testserver",
            )

        async with client("9.9.9.9") as hog, client("8.8.8.8") as other:
            first = asyncio.create_task(hog.post(path, json=_body(path)))
            await _wait_for(lambda: ai_clients.PROVIDER_CALL_GATE._client_counts)
            refused = await hog.post(path, json=_body(path))
            # Another client is unaffected.
            served = asyncio.create_task(other.post(path, json=_body(path)))
            await _wait_for(lambda: len(ai_clients.PROVIDER_CALL_GATE._client_counts) == 2)
            release.set()
            ok = [await first, await served]
        return refused, ok

    refused, ok = run(scenario())
    assert refused.status_code == 429
    assert refused.headers["retry-after"] == "5"
    assert [r.status_code for r in ok] == [200, 200]
    assert ai_clients.PROVIDER_CALL_GATE._client_counts == {}
