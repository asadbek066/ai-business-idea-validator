import asyncio

import httpx
from app import main

ALLOWED = "http://localhost:5173"
DENIED = "https://evil.example"


def request(method: str, path: str, **kwargs) -> httpx.Response:
    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(scenario())


def oversized(origin: str) -> httpx.Response:
    return request(
        "POST",
        "/analyze-idea",
        content=b"x" * (main.MAX_REQUEST_BODY_BYTES + 1),
        headers={"Origin": origin, "Content-Type": "application/json"},
    )


def test_413_for_allowed_origin_carries_cors_headers() -> None:
    response = oversized(ALLOWED)
    assert response.status_code == 413
    assert response.json() == {"detail": "Request body is too large."}
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert "access-control-allow-credentials" not in response.headers
    # Existing hardening headers on the early error are preserved.
    assert response.headers["x-content-type-options"] == "nosniff"


def test_413_for_disallowed_origin_has_no_cors_headers() -> None:
    response = oversized(DENIED)
    assert response.status_code == 413
    assert "access-control-allow-origin" not in response.headers


def test_invalid_length_400_for_allowed_origin_carries_cors_headers() -> None:
    response = request(
        "POST",
        "/analyze-idea",
        headers={"Origin": ALLOWED, "Content-Length": "-1"},
    )
    assert response.status_code == 400
    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_preflight_still_works_and_rejects_disallowed_origin() -> None:
    headers = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    ok = request("OPTIONS", "/analyze-idea", headers={**headers, "Origin": ALLOWED})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == ALLOWED
    bad = request("OPTIONS", "/analyze-idea", headers={**headers, "Origin": DENIED})
    assert bad.status_code == 400
    assert "access-control-allow-origin" not in bad.headers


SECURITY_HEADERS = {
    "cache-control": "no-store",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}
PREFLIGHT = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
}


def assert_security_headers(response: httpx.Response) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, name


def test_security_headers_on_every_response_kind() -> None:
    responses = {
        "preflight-allowed": request(
            "OPTIONS", "/analyze-idea", headers={**PREFLIGHT, "Origin": ALLOWED}
        ),
        "preflight-denied": request(
            "OPTIONS", "/analyze-idea", headers={**PREFLIGHT, "Origin": DENIED}
        ),
        "ok": request("GET", "/health", headers={"Origin": ALLOWED}),
        "413": oversized(ALLOWED),
        "413-denied": oversized(DENIED),
        "400": request(
            "POST", "/analyze-idea", headers={"Origin": ALLOWED, "Content-Length": "-1"}
        ),
    }
    assert responses["preflight-allowed"].status_code == 200
    assert responses["preflight-denied"].status_code == 400
    assert responses["ok"].status_code == 200
    assert responses["413"].status_code == 413
    assert responses["400"].status_code == 400
    for response in responses.values():
        assert_security_headers(response)
    # CORS stays correct alongside them.
    assert responses["preflight-allowed"].headers["access-control-allow-origin"] == ALLOWED
    assert responses["ok"].headers["access-control-allow-origin"] == ALLOWED
    assert responses["413"].headers["access-control-allow-origin"] == ALLOWED
    assert responses["400"].headers["access-control-allow-origin"] == ALLOWED
    for name in ("preflight-denied", "413-denied"):
        assert "access-control-allow-origin" not in responses[name].headers


def test_middleware_order_is_security_then_cors_then_body_limit() -> None:
    # user_middleware lists the outermost first.
    names = [getattr(m.cls, "__name__", str(m.cls)) for m in main.app.user_middleware]
    assert names == ["BaseHTTPMiddleware", "CORSMiddleware", "RequestBodyLimitMiddleware"]
    assert main.app.user_middleware[0].kwargs["dispatch"] is main.security_headers
