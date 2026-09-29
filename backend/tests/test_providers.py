import asyncio
import json
import threading

import httpx
import pytest
from app import providers
from app.prompts import SYSTEM_PROMPT
from app.providers import (
    AzureOpenAIProvider,
    ClaudeProvider,
    GeminiProvider,
    OpenAIProvider,
    ProviderBusyError,
    ProviderConfigurationError,
    ProviderRequestError,
    ProviderResponseError,
)


def run(coroutine):
    return asyncio.run(coroutine)


def with_transport(monkeypatch, handler):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    )
    monkeypatch.setattr(providers, "_get_http_client", lambda: client)

    async def allow_test_endpoint(_: str) -> None:
        return None

    monkeypatch.setattr(providers, "_assert_public_azure_endpoint", allow_test_endpoint)
    return client


def provider_success(provider_name: str) -> dict[str, object]:
    if provider_name in {"OpenAI", "Azure OpenAI"}:
        return {"choices": [{"message": {"content": "{}"}}]}
    if provider_name == "Gemini":
        return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}
    return {"content": [{"text": "{}"}]}


def test_gemini_uses_header_and_native_system_instruction(monkeypatch) -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=provider_success("Gemini"))

    client = with_transport(monkeypatch, handler)
    try:
        result = run(GeminiProvider("secret-token", "gemini-2.5-flash").analyze("idea"))
    finally:
        run(client.aclose())

    assert result == ("{}", "gemini")
    assert len(captured) == 1
    request = captured[0]
    assert request.url.query == b""
    assert request.headers["x-goog-api-key"] == "secret-token"
    body = json.loads(request.content)
    assert body["systemInstruction"]["parts"][0]["text"] == SYSTEM_PROMPT
    assert body["contents"][0]["role"] == "user"
    assert SYSTEM_PROMPT not in body["contents"][0]["parts"][0]["text"]


def test_claude_uses_top_level_system_prompt(monkeypatch) -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=provider_success("Claude"))

    client = with_transport(monkeypatch, handler)
    try:
        result = run(ClaudeProvider("secret-token", "claude-3-5-haiku").analyze("idea"))
    finally:
        run(client.aclose())

    assert result == ("{}", "claude")
    body = json.loads(captured[0].content)
    assert body["system"] == SYSTEM_PROMPT
    assert body["messages"][0]["role"] == "user"
    assert SYSTEM_PROMPT not in body["messages"][0]["content"]


def test_azure_uses_safe_path_and_query_params(monkeypatch) -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=provider_success("Azure OpenAI"))

    client = with_transport(monkeypatch, handler)
    try:
        result = run(
            AzureOpenAIProvider(
                "https://resource.openai.azure.com/",
                "secret-token",
                "deployment name",
                api_version="2025-01-01-preview",
            ).analyze("idea")
        )
    finally:
        run(client.aclose())

    assert result == ("{}", "azure_openai")
    request = captured[0]
    assert request.headers["api-key"] == "secret-token"
    assert "/deployments/deployment%20name/" in str(request.url)
    assert request.url.params["api-version"] == "2025-01-01-preview"


@pytest.mark.parametrize(
    "provider",
    [
        OpenAIProvider("secret-token", "gpt-4o-mini"),
        AzureOpenAIProvider("https://resource.openai.azure.com", "secret-token", "deployment"),
        GeminiProvider("secret-token", "gemini-2.5-flash"),
        ClaudeProvider("secret-token", "claude-3-5-haiku"),
    ],
)
def test_provider_validation_rejects_empty_success_envelopes(monkeypatch, provider) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client = with_transport(monkeypatch, handler)
    try:
        with pytest.raises(ProviderResponseError):
            run(provider.validate())
    finally:
        run(client.aclose())


def test_gemini_validation_uses_a_minimal_generation_budget(monkeypatch) -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=provider_success("Gemini"))

    client = with_transport(monkeypatch, handler)
    try:
        result = run(GeminiProvider("secret-token", "gemini-2.5-flash").validate())
    finally:
        run(client.aclose())

    assert result == (True, "gemini")
    body = json.loads(captured[0].content)
    assert body["generationConfig"] == {"maxOutputTokens": 1}


def test_azure_dns_guard_rejects_private_resolution(monkeypatch) -> None:
    monkeypatch.setattr(
        providers.socket,
        "getaddrinfo",
        lambda *args: [(0, 0, 0, "", ("10.0.0.8", 443))],
    )

    with pytest.raises(ProviderConfigurationError):
        run(providers._assert_public_azure_endpoint("https://resource.openai.azure.com"))


def test_azure_dns_guard_accepts_global_resolution(monkeypatch) -> None:
    monkeypatch.setattr(
        providers.socket,
        "getaddrinfo",
        lambda *args: [(0, 0, 0, "", ("1.1.1.1", 443))],
    )
    run(providers._assert_public_azure_endpoint("https://resource.openai.azure.com"))


def test_azure_dns_timeout_retains_capacity_until_resolver_finishes(monkeypatch) -> None:
    slots = threading.BoundedSemaphore(1)
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def blocked_getaddrinfo(*_: object) -> list[tuple[object, ...]]:
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=2)
        return [(0, 0, 0, "", ("1.1.1.1", 443))]

    monkeypatch.setattr(providers, "_AZURE_DNS_LOOKUP_SLOTS", slots)
    monkeypatch.setattr(providers, "AZURE_DNS_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(providers.socket, "getaddrinfo", blocked_getaddrinfo)

    async def exercise() -> None:
        try:
            with pytest.raises(ProviderRequestError):
                await providers._assert_public_azure_endpoint("https://resource.openai.azure.com")

            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.005)
            assert started.is_set()

            with pytest.raises(ProviderBusyError):
                await providers._assert_public_azure_endpoint("https://another.openai.azure.com")
            assert calls == 1
        finally:
            release.set()

        for _ in range(100):
            try:
                await providers._assert_public_azure_endpoint("https://another.openai.azure.com")
                break
            except ProviderBusyError:
                await asyncio.sleep(0.005)
        else:
            pytest.fail("DNS lookup capacity was not released after the resolver finished")

        assert calls == 2

    run(exercise())


def test_provider_failure_is_non_sensitive_and_not_retried(monkeypatch) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": "secret-token"})

    client = with_transport(monkeypatch, handler)
    try:
        with pytest.raises(ProviderRequestError, match="^OpenAI request failed$") as error:
            run(OpenAIProvider("secret-token", "gpt-4o-mini").analyze("idea"))
    finally:
        run(client.aclose())

    assert calls == 1
    assert "secret-token" not in str(error.value)


def test_retry_helper_honors_transient_status_only_when_explicit(monkeypatch) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, headers={"Retry-After": "1"}, json={})
        return httpx.Response(200, json={"ok": True})

    client = with_transport(monkeypatch, handler)
    monkeypatch.setattr(OpenAIProvider, "_wait_before_retry", staticmethod(_no_wait))
    try:
        result = run(
            OpenAIProvider("secret-token", "gpt-4o-mini")._post_json_with_retry(
                "https://api.openai.com/test", {}, retries=1, provider_name="OpenAI"
            )
        )
    finally:
        run(client.aclose())

    assert result == {"ok": True}
    assert calls == 2


async def _no_wait(_: str | None, __: int) -> None:
    return None


def test_oversized_provider_response_fails_without_retry(monkeypatch) -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            content=b"x" * (providers.MAX_PROVIDER_RESPONSE_BYTES + 1),
        )

    client = with_transport(monkeypatch, handler)
    try:
        with pytest.raises(ProviderResponseError):
            run(OpenAIProvider("secret-token", "gpt-4o-mini").analyze("idea"))
    finally:
        run(client.aclose())
    assert calls == 1
