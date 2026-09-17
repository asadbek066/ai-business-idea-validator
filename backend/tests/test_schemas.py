import pytest
from app.schemas import AIProvidersConfig, AnalyzeIdeaRequest
from pydantic import ValidationError


def openai_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "enabled": True,
        "model": "gpt-4o-mini",
        "api_key": "secret-key",
    }
    config.update(overrides)
    return config


def providers_config(**overrides: object) -> AIProvidersConfig:
    payload: dict[str, object] = {
        "openai": openai_config(),
        "azure_openai": {"enabled": False},
        "gemini": {"enabled": False},
        "claude": {"enabled": False},
    }
    payload.update(overrides)
    return AIProvidersConfig.model_validate(payload)


def test_analyze_request_strips_idea() -> None:
    request = AnalyzeIdeaRequest(idea="   Validate this idea   ", ai_providers=providers_config())
    assert request.idea == "Validate this idea"


def test_analyze_request_requires_provider_configuration() -> None:
    with pytest.raises(ValidationError):
        AnalyzeIdeaRequest(idea="A useful product")


def test_only_one_provider_can_be_enabled() -> None:
    with pytest.raises(ValidationError):
        AIProvidersConfig(
            openai=openai_config(),
            gemini={"enabled": True, "model": "gemini-2.5-flash", "api_key": "key"},
        )


def test_provider_key_is_masked_in_model_representation() -> None:
    config = providers_config()
    assert "secret-key" not in repr(config)
    assert config.openai.api_key is not None


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://resource.openai.azure.com/",
        "https://resource.openai.azure.us",
        "https://resource.openai.azure.cn",
        "https://resource.services.ai.azure.com",
    ],
)
def test_allowed_azure_endpoint_is_canonicalized(endpoint: str) -> None:
    config = providers_config(
        openai={"enabled": False},
        azure_openai={
            "enabled": True,
            "model": "deployment",
            "api_key": "secret-key",
            "endpoint": endpoint,
        },
    )
    assert config.azure_openai.endpoint == endpoint.rstrip("/")


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://resource.openai.azure.com",
        "https://127.0.0.1",
        "https://[::1]",
        "https://localhost",
        "https://169.254.169.254",
        "https://resource.openai.azure.com.evil.example",
        "https://resource.evil.example",
        "https://user:password@resource.openai.azure.com",
        "https://resource.openai.azure.com?next=http://169.254.169.254",
        "https://resource.openai.azure.com/#fragment",
        "https://resource.openai.azure.com/openai",
        "https://resource.openai.azure.com:444",
        "https://openai.azure.com",
    ],
)
def test_unsafe_azure_endpoints_are_rejected(endpoint: str) -> None:
    with pytest.raises(ValidationError):
        providers_config(
            openai={"enabled": False},
            azure_openai={
                "enabled": True,
                "model": "deployment",
                "api_key": "secret-key",
                "endpoint": endpoint,
            },
        )


@pytest.mark.parametrize(
    "model", ["deployment/name", "model?query", "model#fragment", "model\nname"]
)
def test_model_cannot_change_provider_request_path(model: str) -> None:
    with pytest.raises(ValidationError):
        providers_config(openai=openai_config(model=model))


def test_unknown_request_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        AnalyzeIdeaRequest(
            idea="A useful product",
            ai_providers=providers_config(),
            unexpected="value",
        )


def test_idea_length_is_bounded() -> None:
    with pytest.raises(ValidationError):
        AnalyzeIdeaRequest(
            idea="x" * 2_001,
            ai_providers=providers_config(),
        )
