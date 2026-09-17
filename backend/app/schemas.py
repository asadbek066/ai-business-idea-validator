"""Pydantic models for the public API and provider configuration."""

from ipaddress import ip_address
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    ValidationInfo,
    field_validator,
    model_validator,
)

MAX_IDEA_CHARS = 2_000
MAX_MODEL_CHARS = 128
MAX_API_KEY_CHARS = 512
MAX_ENDPOINT_CHARS = 512
MAX_RESPONSE_FIELD_CHARS = 8_000

_AZURE_OPENAI_HOST_SUFFIXES = (
    ".openai.azure.com",
    ".openai.azure.us",
    ".openai.azure.cn",
    ".services.ai.azure.com",
)


def _require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")
    return value.strip()


class StrictModel(BaseModel):
    """Reject unknown request fields so contracts do not silently drift."""

    model_config = ConfigDict(extra="forbid")


class ProviderConfig(StrictModel):
    """Configuration for one provider supplied for the current request."""

    enabled: StrictBool = False
    model: str = Field(default="", max_length=MAX_MODEL_CHARS)
    api_key: SecretStr | None = Field(default=None, max_length=MAX_API_KEY_CHARS)
    endpoint: str | None = Field(default=None, max_length=MAX_ENDPOINT_CHARS)

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: object) -> str:
        cleaned = "" if value is None else _require_string(value, "Model")
        if any(ord(char) < 32 or ord(char) == 127 or char in "/?#" for char in cleaned):
            raise ValueError("Model must not contain control characters or URL separators.")
        return cleaned

    @field_validator("api_key", "endpoint", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: object | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        field_name = "API key" if info.field_name == "api_key" else "Endpoint"
        cleaned = _require_string(value, field_name)
        if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
            raise ValueError(f"{field_name} must not contain control characters.")
        return cleaned or None

    @field_validator("endpoint")
    @classmethod
    def validate_azure_endpoint(cls, value: str | None) -> str | None:
        """Allow only canonical Azure-owned HTTPS resource hosts.

        The endpoint is supplied by an unauthenticated caller, so accepting an
        arbitrary URL would turn this BYOK API into a credential-forwarding
        SSRF primitive. The path is intentionally normalized away after
        validation because the provider owns the request path.
        """

        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            hostname = (parsed.hostname or "").lower().rstrip(".")
            port = parsed.port
        except ValueError:
            raise ValueError("Endpoint must be a valid Azure OpenAI URL.") from None

        if parsed.scheme != "https":
            raise ValueError("Azure OpenAI endpoint must use https://.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "Azure OpenAI endpoint must not contain credentials, query, or fragment data."
            )
        if parsed.path not in ("", "/"):
            raise ValueError("Azure OpenAI endpoint must contain only the resource host.")
        if port not in (None, 443):
            raise ValueError("Azure OpenAI endpoint must use the default HTTPS port.")

        try:
            ip_address(hostname)
        except ValueError:
            pass
        else:
            raise ValueError("Azure OpenAI endpoint must use an Azure resource hostname.")

        if not hostname or not any(
            hostname.endswith(suffix) and hostname != suffix.removeprefix(".")
            for suffix in _AZURE_OPENAI_HOST_SUFFIXES
        ):
            raise ValueError("Endpoint must be an Azure OpenAI resource hostname.")

        return f"https://{hostname}"


class AIProvidersConfig(StrictModel):
    """Configuration for exactly one provider."""

    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    azure_openai: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    claude: ProviderConfig = Field(default_factory=ProviderConfig)

    @model_validator(mode="after")
    def validate_single_enabled_provider(self) -> "AIProvidersConfig":
        enabled_count = sum(
            provider.enabled
            for provider in (
                self.openai,
                self.azure_openai,
                self.gemini,
                self.claude,
            )
        )
        if enabled_count != 1:
            raise ValueError("Enable exactly one AI provider.")
        return self


class AnalyzeIdeaRequest(StrictModel):
    """Request body for ``POST /analyze-idea``."""

    idea: str = Field(..., min_length=1, max_length=MAX_IDEA_CHARS)
    ai_providers: AIProvidersConfig

    @field_validator("idea", mode="before")
    @classmethod
    def normalize_idea(cls, value: object) -> str:
        cleaned = _require_string(value, "Idea")
        if not cleaned:
            raise ValueError("Idea cannot be empty.")
        return cleaned


class AnalyzeIdeaResponse(StrictModel):
    """Successful structured analysis response from the provider."""

    market_potential: str = Field(..., min_length=1, max_length=MAX_RESPONSE_FIELD_CHARS)
    risks: str = Field(..., min_length=1, max_length=MAX_RESPONSE_FIELD_CHARS)
    first_steps: str = Field(..., min_length=1, max_length=MAX_RESPONSE_FIELD_CHARS)
    verdict: str = Field(..., min_length=1, max_length=MAX_RESPONSE_FIELD_CHARS)
    provider_used: str | None = None
    fallback_message: str | None = None


class ValidateProviderRequest(StrictModel):
    """Request body for ``POST /validate-provider``."""

    ai_providers: AIProvidersConfig


class ValidateProviderResponse(StrictModel):
    """Response for provider connectivity validation."""

    ok: bool
    provider_used: str
    message: str
