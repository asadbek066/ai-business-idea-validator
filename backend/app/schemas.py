"""Pydantic models for request/response."""
from pydantic import BaseModel, Field
from typing import Optional


class ProviderConfig(BaseModel):
    """Configuration for a single AI provider."""
    enabled: bool = False
    model: str = ""
    api_key: Optional[str] = None
    url: Optional[str] = None  # For Ollama
    endpoint: Optional[str] = None  # For Azure OpenAI


class AIProvidersConfig(BaseModel):
    """Configuration for all AI providers."""
    ollama: ProviderConfig = ProviderConfig(enabled=True, url="http://localhost:11434")
    openai: ProviderConfig = ProviderConfig()
    azure_openai: ProviderConfig = ProviderConfig()
    gemini: ProviderConfig = ProviderConfig()
    claude: ProviderConfig = ProviderConfig()


class AnalyzeIdeaRequest(BaseModel):
    """Request body for POST /analyze-idea."""
    idea: str = Field(..., min_length=1, max_length=2000)
    ai_providers: Optional[AIProvidersConfig] = None  # Optional: uses defaults if not provided


class AnalyzeIdeaResponse(BaseModel):
    """Structured analysis response from AI."""
    market_potential: str
    risks: str
    first_steps: str
    verdict: str
    provider_used: Optional[str] = None  # Which provider was actually used
    fallback_message: Optional[str] = None  # Message if Ollama fallback was used
