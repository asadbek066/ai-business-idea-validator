import asyncio
import math

import httpx
import pytest
from app import ai_clients, main, providers
from app.ai_clients import ProviderCallGate
from app.main import SlidingWindowLimiter
from app.providers import (
    AzureOpenAIProvider,
    ClaudeProvider,
    GeminiProvider,
    OpenAIProvider,
    ProviderBusyError,
    ProviderClientLimitError,
    ProviderConfigurationError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTimeoutError,
)

KEY = "sentinel-key-material-1234567890"


def run(coroutine):
    return asyncio.run(coroutine)


def with_transport(monkeypatch, handler):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False
    )
    monkeypatch.setattr(providers, "_get_http_client", lambda: client)

    async def allow(_: str) -> None:
        return None

    monkeypatch.setattr(providers, "_assert_public_azure_endpoint", allow)
    return client


# --- /validate-provider error mapping -------------------------------------


def _validate_body() -> dict[str, object]:
    return {
        "ai_providers": {
            "openai": {"enabled": True, "model": "gpt-4o-mini", "api_key": KEY},
            "azure_openai": {"enabled": False},
            "gemini": {"enabled": False},
            "claude": {"enabled": False},
        }
    }


def _post_validate(monkeypatch, error: Exception) -> httpx.Response:
    monkeypatch.setattr(main, "RATE_LIMIT_ENABLED", False)

    async def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(main, "validate_provider", fail)

    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
        ) as client:
            return await client.post("/validate-provider", json=_validate_body())

    return run(scenario())


@pytest.mark.parametrize(
    ("error", "status", "retry_after"),
    [
        (ProviderConfigurationError("OpenAI"), 422, None),
        (ProviderResponseError("OpenAI"), 502, None),
        (ProviderTimeoutError("OpenAI"), 504, "5"),
        (ProviderBusyError("OpenAI"), 503, "5"),
        (ProviderClientLimitError("OpenAI"), 429, "5"),
        (ProviderRequestError("OpenAI", status_code=401), 503, None),
        (ProviderRequestError("OpenAI"), 503, None),
        (RuntimeError(f"boom {KEY}"), 500, None),
        (ValueError(f"boom {KEY}"), 500, None),
    ],
)
def test_validate_provider_maps_each_error_class(monkeypatch, error, status, retry_after) -> None:
    response = _post_validate(monkeypatch, error)
    assert response.status_code == status
    assert response.headers.get("retry-after") == retry_after
    assert KEY not in response.text
    assert "sentinel" not in response.text
    assert set(response.json()) == {"detail"}


@pytest.mark.parametrize(
    ("make", "status"),
    [
        (lambda: OpenAIProvider(KEY, "m"), 401),
        (lambda: GeminiProvider(KEY, "m"), 403),
        (lambda: ClaudeProvider(KEY, "m"), 401),
        (lambda: AzureOpenAIProvider("https://x.openai.azure.com", KEY, "m"), 401),
    ],
)
def test_every_provider_upstream_rejection_maps_to_503_without_key(
    monkeypatch, make, status
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": f"bad key {KEY}"})

    client = with_transport(monkeypatch, handler)
    monkeypatch.setattr(main, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(ai_clients, "PROVIDER_CALL_GATE", ProviderCallGate(4))
    monkeypatch.setattr(ai_clients, "_get_selected_provider", lambda _: (make(), "p"))
    monkeypatch.setattr(main, "VALIDATE_LIMITER", SlidingWindowLimiter(100, 60))

    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
        ) as api:
            return await api.post("/validate-provider", json=_validate_body())

    try:
        response = run(scenario())
    finally:
        run(client.aclose())
    assert response.status_code == 503
    assert KEY not in response.text


# --- network / status retry loop ------------------------------------------


def _post(monkeypatch, handler, *, retries: int, sleeps: list[float] | None = None):
    client = with_transport(monkeypatch, handler)
    if sleeps is not None:
        real_sleep = asyncio.sleep

        async def fake_sleep(delay: float, *a):
            sleeps.append(delay)
            await real_sleep(0)

        monkeypatch.setattr(providers.asyncio, "sleep", fake_sleep)
    try:
        return run(
            OpenAIProvider(KEY, "m")._post_json_with_retry(
                "https://api.openai.com/test", {}, retries=retries, provider_name="OpenAI"
            )
        )
    finally:
        run(client.aclose())


def test_network_error_is_retried_then_succeeds(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, json={"ok": True})

    assert _post(monkeypatch, handler, retries=2, sleeps=sleeps) == {"ok": True}
    assert calls == 3
    assert sleeps == [0.4, 0.8]


def test_network_error_attempt_cap_and_non_sensitive_error(monkeypatch) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout(f"timeout {KEY}", request=request)

    with pytest.raises(ProviderRequestError) as error:
        _post(monkeypatch, handler, retries=2, sleeps=[])
    assert calls == 3
    assert error.value.retryable is True
    assert KEY not in str(error.value)


def test_retry_count_is_capped_at_two_even_if_caller_asks_for_more(monkeypatch) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={})

    with pytest.raises(ProviderRequestError) as error:
        _post(monkeypatch, handler, retries=50, sleeps=[])
    assert calls == 3
    assert error.value.status_code == 503


def test_negative_retry_count_means_a_single_attempt(monkeypatch) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(ProviderRequestError):
        _post(monkeypatch, handler, retries=-3, sleeps=[])
    assert calls == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_non_retryable_client_errors_are_not_retried(monkeypatch, status) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": KEY})

    with pytest.raises(ProviderRequestError) as error:
        _post(monkeypatch, handler, retries=2, sleeps=[])
    assert calls == 1
    assert error.value.retryable is False
    assert error.value.status_code == status
    assert KEY not in str(error.value)


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_retryable_statuses_are_retried_up_to_the_cap(monkeypatch, status) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={})

    with pytest.raises(ProviderRequestError) as error:
        _post(monkeypatch, handler, retries=2, sleeps=[])
    assert calls == 3
    assert error.value.retryable is True


@pytest.mark.parametrize(
    ("header", "expected"),
    [("1", 1.0), ("9999", 5.0), ("inf", 5.0), ("-4", 0.4), ("junk", 0.4), ("nan", 0.4)],
)
def test_retry_after_is_clamped_to_the_time_budget(monkeypatch, header, expected) -> None:
    calls = 0
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, headers={"Retry-After": header}, json={})
        return httpx.Response(200, json={"ok": True})

    assert _post(monkeypatch, handler, retries=1, sleeps=sleeps) == {"ok": True}
    assert sleeps == [expected]
    assert all(
        math.isfinite(delay) and delay <= providers.MAX_RETRY_AFTER_SECONDS for delay in sleeps
    )


def test_total_retry_wait_is_bounded(monkeypatch) -> None:
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"Retry-After": "9999"}, json={})

    with pytest.raises(ProviderRequestError):
        _post(monkeypatch, handler, retries=2, sleeps=sleeps)
    assert sum(sleeps) <= 2 * providers.MAX_RETRY_AFTER_SECONDS


def test_gate_deadline_cuts_off_a_retry_loop_that_never_finishes(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10)
        return httpx.Response(200, json={})

    client = with_transport(monkeypatch, handler)
    gate = ProviderCallGate(1)
    provider = OpenAIProvider(KEY, "m")
    try:
        with pytest.raises(ProviderTimeoutError):
            run(
                gate.run(
                    lambda: provider._post_json_with_retry(
                        "https://api.openai.com/test", {}, retries=2, provider_name="OpenAI"
                    ),
                    "OpenAI",
                    deadline_seconds=0.05,
                )
            )
    finally:
        run(client.aclose())
