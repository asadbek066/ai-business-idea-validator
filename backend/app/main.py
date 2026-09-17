"""FastAPI application for the BYOK business-idea analysis API."""

import asyncio
import json
import logging
import os
import time
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, NoReturn, TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .ai_clients import analyze_idea, validate_provider
from .providers import (
    ProviderBusyError,
    ProviderConfigurationError,
    ProviderError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTimeoutError,
    close_http_clients,
)
from .schemas import (
    AnalyzeIdeaRequest,
    AnalyzeIdeaResponse,
    ValidateProviderRequest,
    ValidateProviderResponse,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
T = TypeVar("T")


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


MAX_REQUEST_BODY_BYTES = _bounded_env_int(
    "MAX_REQUEST_BODY_BYTES",
    default=64 * 1024,
    minimum=4 * 1024,
    maximum=2 * 1024 * 1024,
)


class RequestBodyLimitMiddleware:
    """Enforce request size even when clients omit ``Content-Length``."""

    def __init__(self, app: Any, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    @staticmethod
    async def _send_error(send: Any, status_code: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
            (b"referrer-policy", b"no-referrer"),
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
        ]
        await send({"type": "http.response.start", "status": status_code, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except (TypeError, ValueError):
                await self._send_error(send, 400, "Invalid request length.")
                return
            if declared_length < 0:
                await self._send_error(send, 400, "Invalid request length.")
                return
            if declared_length > self.max_body_bytes:
                await self._send_error(send, 413, "Request body is too large.")
                return

        total_bytes = 0
        oversized = False

        async def limited_receive() -> Any:
            nonlocal total_bytes, oversized
            message = await receive()
            if message.get("type") == "http.request":
                total_bytes += len(message.get("body", b""))
                if total_bytes > self.max_body_bytes:
                    if not oversized:
                        oversized = True
                        await self._send_error(send, 413, "Request body is too large.")
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Any) -> None:
            if not oversized:
                await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not oversized:
                raise


class ClientDisconnected(Exception):
    """The caller closed the request while provider work was running."""


async def _run_until_client_disconnect(
    request: Request, operation: Callable[[], Awaitable[T]]
) -> T:
    """Cancel provider work when the HTTP client disappears."""

    async def invoke() -> T:
        return await operation()

    task: asyncio.Task[T] = asyncio.create_task(invoke())
    try:
        while True:
            if task.done():
                return task.result()
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=0.25)
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise ClientDisconnected from None
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def _parse_cors_origins() -> list[str]:
    origins = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    ]
    if "*" in origins:
        raise RuntimeError("CORS_ORIGINS must be an explicit origin allowlist.")
    return origins


class SlidingWindowLimiter:
    """Small process-local abuse guard for unauthenticated provider calls."""

    def __init__(self, limit: int, window_seconds: int, max_keys: int = 4096):
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def retry_after(self, key: str) -> int | None:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = deque()
                self._hits[key] = hits
            while hits and hits[0] <= cutoff:
                hits.popleft()
            self._hits.move_to_end(key)
            if len(hits) >= self.limit:
                return max(1, int(hits[0] + self.window_seconds - now) + 1)
            hits.append(now)
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)
            return None


RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
RATE_LIMIT_WINDOW_SECONDS = _bounded_env_int(
    "RATE_LIMIT_WINDOW_SECONDS", default=60, minimum=1, maximum=3_600
)
ANALYZE_LIMITER = SlidingWindowLimiter(
    _bounded_env_int("ANALYZE_RATE_LIMIT", default=10, minimum=1, maximum=1_000),
    RATE_LIMIT_WINDOW_SECONDS,
)
VALIDATE_LIMITER = SlidingWindowLimiter(
    _bounded_env_int("VALIDATE_PROVIDER_RATE_LIMIT", default=20, minimum=1, maximum=1_000),
    RATE_LIMIT_WINDOW_SECONDS,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_http_clients()


app = FastAPI(
    title="Business Idea Validator API",
    description="Analyze business ideas using cloud AI providers (OpenAI, Azure, Gemini, Claude).",
    version="2.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


# Keep this outermost so it can reject chunked bodies before any downstream
# middleware or FastAPI parser buffers them.
app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=MAX_REQUEST_BODY_BYTES)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Return useful validation locations without reflecting BYOK secrets."""

    details: list[dict[str, object]] = []
    for error in exc.errors():
        location = tuple(error.get("loc", ()))
        is_api_key = "api_key" in location
        details.append(
            {
                "loc": list(location),
                "msg": "Invalid API key value."
                if is_api_key
                else error.get("msg", "Invalid request."),
                "type": "value_error" if is_api_key else error.get("type", "value_error"),
            }
        )
    return JSONResponse(status_code=422, content={"detail": details})


async def _enforce_rate_limit(request: Request, limiter: SlidingWindowLimiter) -> None:
    if not RATE_LIMIT_ENABLED:
        return
    client_host = request.client.host if request.client else "unknown"
    retry_after = await limiter.retry_after(client_host)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def _raise_analysis_http_error(error: ProviderError) -> NoReturn:
    if isinstance(error, ProviderConfigurationError):
        raise HTTPException(
            status_code=422,
            detail="Selected provider configuration is incomplete.",
        ) from None
    if isinstance(error, ProviderResponseError):
        raise HTTPException(
            status_code=502,
            detail="Provider returned an invalid analysis. Please try again.",
        ) from None
    if isinstance(error, ProviderTimeoutError):
        raise HTTPException(
            status_code=504,
            detail="The provider took too long to respond. Please try again.",
            headers={"Retry-After": "5"},
        ) from None
    if isinstance(error, ProviderBusyError):
        raise HTTPException(
            status_code=503,
            detail="The analysis service is busy. Please try again shortly.",
            headers={"Retry-After": "5"},
        ) from None
    if isinstance(error, ProviderRequestError):
        raise HTTPException(
            status_code=503,
            detail="The analysis service is temporarily unavailable. Please try again.",
        ) from None
    raise HTTPException(status_code=503, detail="Analysis service is unavailable.") from None


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check for deployment platforms."""

    return {"status": "ok"}


@app.post("/analyze-idea", response_model=AnalyzeIdeaResponse)
async def analyze_idea_endpoint(
    request: Request, body: AnalyzeIdeaRequest
) -> AnalyzeIdeaResponse | Response:
    """Analyze an idea with the one provider selected by the caller."""

    await _enforce_rate_limit(request, ANALYZE_LIMITER)
    try:
        result, provider_used, fallback_message = await _run_until_client_disconnect(
            request,
            lambda: analyze_idea(
                body.idea,
                providers_config=body.ai_providers,
            ),
        )
        return AnalyzeIdeaResponse(
            market_potential=result["market_potential"],
            risks=result["risks"],
            first_steps=result["first_steps"],
            verdict=result["verdict"],
            provider_used=provider_used,
            fallback_message=fallback_message,
        )
    except ClientDisconnected:
        logger.info("Analysis client disconnected before completion")
        return Response(status_code=499)
    except ProviderError as error:
        logger.warning("Analysis request failed: %s", type(error).__name__)
        _raise_analysis_http_error(error)
    except RuntimeError as error:
        logger.warning("Analysis provider failure: %s", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="The analysis service is temporarily unavailable. Please try again.",
        ) from None
    except Exception as error:
        logger.error("Unexpected analysis error: %s", type(error).__name__)
        raise HTTPException(status_code=500, detail="Analysis failed. Please try again.") from None


@app.post("/validate-provider", response_model=ValidateProviderResponse)
async def validate_provider_endpoint(
    request: Request, body: ValidateProviderRequest
) -> ValidateProviderResponse | Response:
    """Validate selected provider credentials/connectivity quickly."""

    await _enforce_rate_limit(request, VALIDATE_LIMITER)
    try:
        ok, provider_used = await _run_until_client_disconnect(
            request, lambda: validate_provider(body.ai_providers)
        )
        return ValidateProviderResponse(
            ok=ok,
            provider_used=provider_used,
            message="Provider configuration is valid.",
        )
    except ClientDisconnected:
        logger.info("Provider validation client disconnected before completion")
        return Response(status_code=499)
    except ProviderConfigurationError as error:
        logger.info("Provider validation rejected: %s", error.provider_name)
        raise HTTPException(
            status_code=422,
            detail="Selected provider configuration is incomplete.",
        ) from None
    except ProviderResponseError:
        logger.warning("Provider validation returned an invalid response")
        raise HTTPException(
            status_code=502,
            detail="Provider returned an invalid validation response.",
        ) from None
    except ProviderTimeoutError:
        logger.warning("Provider validation timed out")
        raise HTTPException(
            status_code=504,
            detail="Provider validation timed out. Please try again.",
            headers={"Retry-After": "5"},
        ) from None
    except ProviderBusyError:
        logger.warning("Provider validation capacity is busy")
        raise HTTPException(
            status_code=503,
            detail="Provider validation is busy. Please try again shortly.",
            headers={"Retry-After": "5"},
        ) from None
    except ProviderRequestError:
        logger.warning("Provider validation request failed")
        raise HTTPException(
            status_code=503,
            detail="Provider validation is temporarily unavailable. Please try again.",
        ) from None
    except Exception as error:
        logger.error("Unexpected provider validation error: %s", type(error).__name__)
        raise HTTPException(status_code=500, detail="Provider validation failed.") from None


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=8000)
