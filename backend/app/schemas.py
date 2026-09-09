"""Pydantic models for request/response."""

from ipaddress import ip_address
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

_AZURE_OPENAI_HOST_SUFFIXES = (
    ".openai.azure.com",
    ".openai.azure.us",
    ".openai.azure.cn",
)


def _require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")
    return value.strip()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderConfig(StrictModel):
    """Configuration for a single AI provider."""

    enabled: bool = False
    model: str = Field(default="", max_length=128)
    api_key: str | None = Field(default=None, max_length=512)
    endpoint: str | None = Field(default=None, max_length=512)  # For Azure OpenAI

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: object) -> str:
        cleaned = "" if value is None else _require_string(value, "Model")
        if any(ord(char) < 32 or char in "/?#" for char in cleaned):
            raise ValueError(
                "Model must not contain control characters or URL separators."
            )
        return cleaned

    @field_validator("api_key", "endpoint", mode="before")
    @classmethod
    def normalize_optional_strings(
        cls, value: object | None, info: ValidationInfo
    ) -> str | None:
        if value is None:
            return None
        field_name = "API key" if info.field_name == "api_key" else "Endpoint"
        cleaned = _require_string(value, field_name)
        if any(char in cleaned for char in ("\r", "\n")):
            raise ValueError(f"{field_name} must not contain newlines.")
        return cleaned or None

    @field_validator("endpoint")
    @classmethod
    def validate_http_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            hostname = (parsed.hostname or "").lower().rstrip(".")
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Endpoint must be a valid Azure OpenAI URL.") from exc

        if parsed.scheme != "https":
            raise ValueError("Azure OpenAI endpoint must use https://.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "Azure OpenAI endpoint must not contain credentials, query, or fragment data."
            )
        if port not in (None, 443):
            raise ValueError("Azure OpenAI endpoint must use the default HTTPS port.")
        try:
            ip_address(hostname)
        except ValueError:
            pass
        else:
            raise ValueError("Azure OpenAI endpoint must use an Azure hostname.")
        if not hostname or not any(
            hostname.endswith(suffix) for suffix in _AZURE_OPENAI_HOST_SUFFIXES
        ):
            raise ValueError("Endpoint must be an Azure OpenAI resource hostname.")
        return f"https://{hostname}"


class AIProvidersConfig(StrictModel):
    """Configuration for all AI providers."""

    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    azure_openai: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    claude: ProviderConfig = Field(default_factory=ProviderConfig)

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


class AnalyzeIdeaRequest(StrictModel):
    """Request body for POST /analyze-idea."""

    idea: str = Field(..., min_length=1, max_length=2000)
    ai_providers: AIProvidersConfig

    @field_validator("idea", mode="before")
    @classmethod
    def normalize_idea(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Idea cannot be empty.")
        return cleaned


class AnalyzeIdeaResponse(StrictModel):
    """Structured analysis response from AI."""

    market_potential: str
    risks: str
    first_steps: str
    verdict: str
    provider_used: str | None = None  # Which provider was actually used
    fallback_message: str | None = None


class ValidateProviderRequest(StrictModel):
    """Request body for POST /validate-provider."""

    ai_providers: AIProvidersConfig


class ValidateProviderResponse(StrictModel):
    """Response for provider validation endpoint."""

    ok: bool
    provider_used: str
    message: str
