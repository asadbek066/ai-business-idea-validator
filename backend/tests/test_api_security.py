import asyncio
import json

import httpx
import pytest
from app import ai_clients, main
from app.ai_clients import ProviderCallGate
from app.main import (
    ClientDisconnected,
    SlidingWindowLimiter,
    _run_until_client_disconnect,
    app,
)
from app.providers import (
    AIProvider,
    ProviderBusyError,
    ProviderRequestError,
    ProviderResponseError,
)


def run(coroutine):
    return asyncio.run(coroutine)


def providers_payload() -> dict[str, object]:
    return {
        "openai": {"enabled": True, "model": "gpt-4o-mini", "api_key": "secret-key"},
        "azure_openai": {"enabled": False},
        "gemini": {"enabled": False},
        "claude": {"enabled": False},
    }


async def post(path: str, body: object, headers: dict[str, str] | None = None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.post(path, json=body, headers=headers)


class FakeProvider(AIProvider):
    provider_name = "Fake"

    def __init__(self, response: object = None, error: Exception | None = None):
        self.response = response
        self.error = error

    async def analyze(self, idea: str) -> tuple[str, str]:
        if self.error:
            raise self.error
        return self.response, "openai"

    async def validate(self) -> tuple[bool, str]:
        if self.error:
            raise self.error
        return True, "openai"


@pytest.fixture(autouse=True)
def reset_process_limits(monkeypatch):
    monkeypatch.setattr(main, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(main, "ANALYZE_LIMITER", SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(main, "VALIDATE_LIMITER", SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(ai_clients, "PROVIDER_CALL_GATE", ProviderCallGate(4))


def test_successful_analysis_has_contract_and_security_headers(monkeypatch) -> None:
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
    response = run(
        post(
            "/analyze-idea",
            {"idea": "A useful product", "ai_providers": providers_payload()},
        )
    )

    assert response.status_code == 200
    assert response.json() == {
        "market_potential": "Market",
        "risks": "Risks",
        "first_steps": "Steps",
        "verdict": "Verdict",
        "provider_used": "openai",
        "fallback_message": None,
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_real_analysis_path_rejects_malformed_provider_output(monkeypatch) -> None:
    fake = FakeProvider(response='{"market_potential":"only one"}')
    monkeypatch.setattr(ai_clients, "_get_selected_provider", lambda _: (fake, "openai"))
    response = run(
        post(
            "/analyze-idea",
            {"idea": "A useful product", "ai_providers": providers_payload()},
        )
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Provider returned an invalid analysis. Please try again."}
    assert "only one" not in response.text


def test_real_analysis_path_returns_only_a_complete_structured_result(monkeypatch) -> None:
    fake = FakeProvider(
        response=(
            '{"market_potential":"Market","risks":"Risks",'
            '"first_steps":"Steps","verdict":"Verdict"}'
        )
    )
    monkeypatch.setattr(ai_clients, "_get_selected_provider", lambda _: (fake, "openai"))
    response = run(
        post(
            "/analyze-idea",
            {"idea": "A useful product", "ai_providers": providers_payload()},
        )
    )

    assert response.status_code == 200
    assert response.json()["verdict"] == "Verdict"
    assert response.json()["provider_used"] == "openai"


def test_provider_failure_is_not_a_success_and_is_non_sensitive(monkeypatch) -> None:
    fake = FakeProvider(error=ProviderRequestError("OpenAI"))
    monkeypatch.setattr(ai_clients, "_get_selected_provider", lambda _: (fake, "openai"))
    response = run(
        post(
            "/analyze-idea",
            {"idea": "A useful product", "ai_providers": providers_payload()},
        )
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "The analysis service is temporarily unavailable. Please try again."
    }
    assert "OpenAI" not in response.text


def test_unexpected_provider_runtime_error_is_not_returned_as_success(
    monkeypatch,
) -> None:
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
    assert "secret-token" not in response.text
    assert response.json()["detail"] == (
        "The analysis service is temporarily unavailable. Please try again."
    )


def test_analysis_timeout_is_explicit(monkeypatch) -> None:
    fake = FakeProvider(
        response='{"market_potential":"m","risks":"r","first_steps":"s","verdict":"v"}'
    )
    monkeypatch.setattr(ai_clients, "_get_selected_provider", lambda _: (fake, "openai"))
    monkeypatch.setattr(ai_clients, "ANALYZE_DEADLINE_SECONDS", 0.01)

    async def slow_call(_: str):
        await asyncio.sleep(0.05)
        return "never", "openai"

    monkeypatch.setattr(fake, "analyze", slow_call)
    response = run(
        post(
            "/analyze-idea",
            {"idea": "A useful product", "ai_providers": providers_payload()},
        )
    )
    assert response.status_code == 504
    assert "too long" in response.json()["detail"]


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


def test_provider_validation_success_contract(monkeypatch) -> None:
    async def validate(*args, **kwargs):
        return True, "openai"

    monkeypatch.setattr(main, "validate_provider", validate)
    response = run(post("/validate-provider", {"ai_providers": providers_payload()}))

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "provider_used": "openai",
        "message": "Provider configuration is valid.",
    }


def test_cors_allows_configured_origin_without_credentials(monkeypatch) -> None:
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
    body = {"idea": "A useful product", "ai_providers": providers_payload()}
    allowed = run(post("/analyze-idea", body, {"Origin": "http://localhost:5173"}))
    denied = run(post("/analyze-idea", body, {"Origin": "https://evil.example"}))

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in allowed.headers
    assert "access-control-allow-origin" not in denied.headers


def test_provider_validation_invalid_success_is_not_ok(monkeypatch) -> None:
    async def invalid(*args, **kwargs):
        raise ProviderResponseError("OpenAI")

    monkeypatch.setattr(main, "validate_provider", invalid)
    response = run(post("/validate-provider", {"ai_providers": providers_payload()}))

    assert response.status_code == 502
    assert response.json() == {"detail": "Provider returned an invalid validation response."}


def test_missing_provider_configuration_is_a_validation_error(monkeypatch) -> None:
    called = False

    async def should_not_run(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(main, "analyze_idea", should_not_run)
    response = run(post("/analyze-idea", {"idea": "A useful product"}))

    assert response.status_code == 422
    assert called is False


@pytest.mark.parametrize("path", ["/analyze-idea", "/validate-provider"])
@pytest.mark.parametrize(
    "sentinel",
    [
        "SECRET-SENTINEL-DO-NOT-REFLECT\nINTERNAL",
        "SECRET-SENTINEL-DO-NOT-REFLECT" + "x" * 600,
    ],
)
def test_validation_errors_do_not_reflect_api_keys(path: str, sentinel: str) -> None:
    body: object
    if path == "/analyze-idea":
        body = {
            "idea": "A useful product",
            "ai_providers": {
                **providers_payload(),
                "openai": {
                    "enabled": True,
                    "model": "gpt-4o-mini",
                    "api_key": sentinel,
                },
            },
        }
    else:
        body = {
            "ai_providers": {
                **providers_payload(),
                "openai": {
                    "enabled": True,
                    "model": "gpt-4o-mini",
                    "api_key": sentinel,
                },
            }
        }
    response = run(post(path, body))
    assert response.status_code == 422
    assert sentinel.strip() not in response.text
    assert "input" not in response.json()["detail"][0]


def test_oversized_chunked_body_is_rejected_before_endpoint() -> None:
    async def scenario():
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/analyze-idea",
            "raw_path": b"/analyze-idea",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
        }
        chunks = [b"{" + b"x" * main.MAX_REQUEST_BODY_BYTES, b"}"]
        sent = []

        async def receive():
            if chunks:
                body = chunks.pop(0)
                return {"type": "http.request", "body": body, "more_body": bool(chunks)}
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        await app(scope, receive, send)
        return sent

    events = run(scenario())
    start = next(event for event in events if event["type"] == "http.response.start")
    body = next(event for event in events if event["type"] == "http.response.body")
    assert start["status"] == 413
    assert json.loads(body["body"]) == {"detail": "Request body is too large."}


def test_provider_gate_rejects_when_capacity_queue_is_full(monkeypatch) -> None:
    async def scenario():
        gate = ProviderCallGate(1)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocking():
            entered.set()
            await release.wait()

        first = asyncio.create_task(gate.run(blocking, "test", deadline_seconds=1))
        await entered.wait()
        monkeypatch.setattr(ai_clients, "PROVIDER_QUEUE_TIMEOUT_SECONDS", 0.01)
        with pytest.raises(ProviderBusyError):
            await gate.run(lambda: asyncio.sleep(0), "test", deadline_seconds=1)
        release.set()
        await first

    run(scenario())


def test_client_disconnect_cancels_in_flight_operation() -> None:
    async def scenario() -> bool:
        class DisconnectedRequest:
            async def is_disconnected(self) -> bool:
                return True

        cancelled = False

        async def operation() -> None:
            nonlocal cancelled
            try:
                await asyncio.sleep(1)
            finally:
                cancelled = True

        with pytest.raises(ClientDisconnected):
            await _run_until_client_disconnect(DisconnectedRequest(), operation)
        return cancelled

    assert run(scenario()) is True
