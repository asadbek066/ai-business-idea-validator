"""Pydantic models for request/response."""
from pydantic import BaseModel, Field
from pydantic import field_validator, model_validator
from typing import Optional


class ProviderConfig(BaseModel):
    """Configuration for a single AI provider."""
    enabled: bool = False
    model: str = ""
    api_key: Optional[str] = None
    endpoint: Optional[str] = None  # For Azure OpenAI

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("api_key", "endpoint", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("endpoint")
    @classmethod
    def validate_http_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        return value


class AIProvidersConfig(BaseModel):
    """Configuration for all AI providers."""
    openai: ProviderConfig = ProviderConfig()
    azure_openai: ProviderConfig = ProviderConfig()
    gemini: ProviderConfig = ProviderConfig()
    claude: ProviderConfig = ProviderConfig()

    @model_validator(mode="after")
    def validate_single_enabled_provider(self) -> "AIProvidersConfig":
        enabled_count = sum(
            [
                self.openai.enabled,
                self.azure_openai.enabled,
                self.gemini.enabled,
                self.claude.enabled,
            ]
        )
        if enabled_count != 1:
            raise ValueError("Enable exactly one AI provider.")
        return self


class AnalyzeIdeaRequest(BaseModel):
    """Request body for POST /analyze-idea."""
    idea: str = Field(..., min_length=1, max_length=2000)
    ai_providers: Optional[AIProvidersConfig] = None  # Optional: uses defaults if not provided

    @field_validator("idea", mode="before")
    @classmethod
    def normalize_idea(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Idea cannot be empty.")
        return cleaned


class AnalyzeIdeaResponse(BaseModel):
    """Structured analysis response from AI."""
    market_potential: str
    risks: str
    first_steps: str
    verdict: str
    provider_used: Optional[str] = None  # Which provider was actually used
    fallback_message: Optional[str] = None
