"""FastAPI app: POST /analyze-idea with multi-provider AI support."""
import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .schemas import (
    AnalyzeIdeaRequest,
    AnalyzeIdeaResponse,
    ValidateProviderRequest,
    ValidateProviderResponse,
)
from .ai_clients import analyze_idea, validate_provider

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Business Idea Validator API",
    description="Analyze business ideas using cloud AI providers (OpenAI, Azure, Gemini, Claude).",
    version="2.0.0",
)

# CORS: allow frontend origins (Vite dev + production)
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Health check for Render/deployment."""
    return {"status": "ok"}


@app.post("/analyze-idea", response_model=AnalyzeIdeaResponse)
async def analyze_idea_endpoint(body: AnalyzeIdeaRequest):
    """
    Analyze a business idea. Returns market_potential, risks, first_steps, verdict.
    Uses the single selected provider.
    """
    try:
        result, provider_used, fallback_message = await analyze_idea(
            body.idea,
            providers_config=body.ai_providers
        )
        
        # Ensure we always return valid response even if result is malformed
        if not isinstance(result, dict):
            result = {}
        
        return AnalyzeIdeaResponse(
            market_potential=str(result.get("market_potential", "") or ""),
            risks=str(result.get("risks", "") or ""),
            first_steps=str(result.get("first_steps", "") or ""),
            verdict=str(result.get("verdict", "") or ""),
            provider_used=provider_used,
            fallback_message=fallback_message,
        )
    except RuntimeError as e:
        logger.warning("Provider pipeline failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected error in analyze_idea endpoint.")
        return AnalyzeIdeaResponse(
            market_potential="Analysis temporarily unavailable. Please try again.",
            risks="",
            first_steps="",
            verdict="",
            provider_used=None,
            fallback_message=None,
        )


@app.post("/validate-provider", response_model=ValidateProviderResponse)
async def validate_provider_endpoint(body: ValidateProviderRequest):
    """Validate selected provider credentials/connectivity quickly."""
    try:
        ok, provider_used = await validate_provider(body.ai_providers)
        return ValidateProviderResponse(
            ok=ok,
            provider_used=provider_used,
            message="Provider configuration is valid.",
        )
    except RuntimeError as e:
        logger.warning("Provider validation failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        logger.exception("Unexpected error in validate_provider endpoint.")
        raise HTTPException(status_code=500, detail="Provider validation failed.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
