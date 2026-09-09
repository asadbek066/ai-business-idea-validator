"""API and provider-boundary regression tests."""

import asyncio

import httpx
import pytest

from app import main
from app.main import SlidingWindowLimiter, app
from app.providers import GeminiProvider, OpenAIProvider


def run(coroutine):
    return asyncio.run(coroutine)


def providers_payload() -> dict:
    return {
        "openai": {"enabled": True, "model": "gpt-4o-mini", "api_key": "secret"},
        "azure_openai": {"enabled": False},
        "gemini": {"enabled": False},
        "claude": {"enabled": False},
    }


async def post(path: str, body: dict, headers: dict | None = None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.post(path, json=body, headers=headers)


def test_provider_failure_has_generic_public_error(monkeypatch) -> None:
    async def fail(*args, **kwargs):
        raise RuntimeError("provider failed with secret-token and endpoint")

    monkeypatch.setattr(main, "analyze_idea", fail)
    response = run(
        post(
            "/analyze-idea",
            {"idea": "A useful product", "ai_providers": providers_payload()},
        )
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Analysis service is temporarily unavailable. Please try again."
    }
    assert "secret-token" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_unexpected_error_is_not_returned_as_a_success(monkeypatch) -> None:
    async def fail(*args, **kwargs):
        raise ValueError("private provider response")

    monkeypatch.setattr(main, "analyze_idea", fail)
    response = run(
        post(
            "/analyze-idea",
            {"idea": "A useful product", "ai_providers": providers_payload()},
        )
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Analysis failed. Please try again."}
    assert "private provider response" not in response.text


def test_analysis_rate_limit_is_bounded_and_explicit(monkeypatch) -> None:
    async def succeed(*args, **kwargs):
        return (
            {
                "market_potential": "Market",
                "risks": "Risks",
                "first_steps": "Steps",
                "verdict": "Verdict",
            },
            "openai",
            None,
        )

    monkeypatch.setattr(main, "analyze_idea", succeed)
    monkeypatch.setattr(main, "ANALYZE_LIMITER", SlidingWindowLimiter(1, 60))
    body = {"idea": "A useful product", "ai_providers": providers_payload()}

    first = run(post("/analyze-idea", body))
    second = run(post("/analyze-idea", body))

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"].isdigit()
    assert second.json()["detail"] == "Too many requests. Please try again later."


def test_request_body_limit_rejects_oversized_content_length() -> None:
    response = run(
        post(
            "/health",
            {},
            headers={"content-length": str(64 * 1024 + 1)},
        )
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Request body is too large."}


def test_gemini_key_is_sent_in_a_header_not_the_url(monkeypatch) -> None:
    captured = []
    real_async_client = httpx.AsyncClient

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]},
        )

    transport = httpx.MockTransport(handler)

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("app.providers.httpx.AsyncClient", client_factory)
    result = run(GeminiProvider("secret-token", "gemini-2.0-flash").analyze("idea"))

    assert result == ("{}", "gemini")
    assert len(captured) == 1
    assert captured[0].url.query == b""
    assert "secret-token" not in str(captured[0].url)
    assert captured[0].headers["x-goog-api-key"] == "secret-token"


def test_provider_failure_does_not_include_request_url_or_key(monkeypatch) -> None:
    real_async_client = httpx.AsyncClient
    captured = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(401, json={"error": "invalid"})

    transport = httpx.MockTransport(handler)

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("app.providers.httpx.AsyncClient", client_factory)
    with pytest.raises(RuntimeError, match="^Gemini request failed$") as error:
        run(GeminiProvider("secret-token", "gemini-2.0-flash").validate())

    assert "secret-token" not in str(error.value)
    assert len(captured) == 1


def test_transient_provider_status_is_retried(monkeypatch) -> None:
    real_async_client = httpx.AsyncClient
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}]},
        )

    transport = httpx.MockTransport(handler)

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("app.providers.httpx.AsyncClient", client_factory)
    result = run(OpenAIProvider("secret-token", "gpt-4o-mini").analyze("idea"))

    assert result == ("{}", "openai")
    assert calls == 2
