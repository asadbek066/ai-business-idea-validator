"""FastAPI app: POST /analyze-idea with multi-provider AI support."""
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .schemas import AnalyzeIdeaRequest, AnalyzeIdeaResponse
from .ai_clients import analyze_idea

app = FastAPI(
    title="Business Idea Validator API",
    description="Analyze business ideas using multiple AI providers (Ollama, OpenAI, Azure, Gemini, Claude).",
    version="2.0.0",
)

# CORS: allow frontend origins (Vite dev + production)
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
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
    Uses configured AI providers with automatic fallback to Ollama.
    """
    try:
        result, provider_used, fallback_message = await analyze_idea(
            body.idea.strip(),
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
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        # Log error with full traceback for debugging
        import traceback
        print(f"[Error in analyze_idea_endpoint] {type(e).__name__}: {e}")
        traceback.print_exc()
        return AnalyzeIdeaResponse(
            market_potential="Analysis temporarily unavailable. Please try again.",
            risks="",
            first_steps="",
            verdict="",
            provider_used=None,
            fallback_message=None,
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
