"""FastAPI app for business-idea analysis with cloud AI providers."""

import asyncio
import logging
import os
import time
from collections import OrderedDict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .ai_clients import analyze_idea, validate_provider
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


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


class SlidingWindowLimiter:
    """Small process-local abuse guard for the unauthenticated provider API."""

    def __init__(self, limit: int, window_seconds: int, max_keys: int = 4096) -> None:
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
    _bounded_env_int(
        "VALIDATE_PROVIDER_RATE_LIMIT", default=20, minimum=1, maximum=1_000
    ),
    RATE_LIMIT_WINDOW_SECONDS,
)

app = FastAPI(
    title="Business Idea Validator API",
    description="Analyze business ideas using cloud AI providers (OpenAI, Azure, Gemini, Claude).",
    version="2.0.0",
)

# The API has no cookie-authenticated browser session, so credentials are not
# needed and broad wildcard methods/headers are unnecessary.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def request_safety_headers(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            length = int(content_length)
            if length < 0:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid request length."},
                )
            if length > 64 * 1024:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body is too large."},
                )
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid request length."},
            )

    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response


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


@app.get("/health")
async def health():
    """Health check for Render/deployment."""
    return {"status": "ok"}


@app.post("/analyze-idea", response_model=AnalyzeIdeaResponse)
async def analyze_idea_endpoint(request: Request, body: AnalyzeIdeaRequest):
    """Analyze an idea using the one provider selected by the caller."""
    await _enforce_rate_limit(request, ANALYZE_LIMITER)
    try:
        result, provider_used, fallback_message = await analyze_idea(
            body.idea,
            providers_config=body.ai_providers,
        )
        return AnalyzeIdeaResponse(
            market_potential=result.get("market_potential", ""),
            risks=result.get("risks", ""),
            first_steps=result.get("first_steps", ""),
            verdict=result.get("verdict", ""),
            provider_used=provider_used,
            fallback_message=fallback_message,
        )
    except RuntimeError as error:
        logger.warning("Analysis request failed: %s", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="Analysis service is temporarily unavailable. Please try again.",
        ) from error
    except Exception as error:
        logger.error(
            "Unexpected error in analyze_idea endpoint: %s",
            type(error).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="Analysis failed. Please try again.",
        ) from error


@app.post("/validate-provider", response_model=ValidateProviderResponse)
async def validate_provider_endpoint(request: Request, body: ValidateProviderRequest):
    """Validate selected provider credentials/connectivity quickly."""
    await _enforce_rate_limit(request, VALIDATE_LIMITER)
    try:
        ok, provider_used = await validate_provider(body.ai_providers)
        return ValidateProviderResponse(
            ok=ok,
            provider_used=provider_used,
            message="Provider configuration is valid.",
        )
    except RuntimeError as error:
        logger.warning("Provider validation request failed: %s", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="Provider validation is temporarily unavailable. Please try again.",
        ) from error
    except Exception as error:
        logger.error(
            "Unexpected error in validate_provider endpoint: %s",
            type(error).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="Provider validation failed.",
        ) from error


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
