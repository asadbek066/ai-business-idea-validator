import pytest
from pydantic import ValidationError

from app.schemas import AIProvidersConfig, AnalyzeIdeaRequest


def valid_providers() -> dict:
    return {
        "openai": {"enabled": True, "model": "gpt-4o-mini", "api_key": "abc"},
        "azure_openai": {"enabled": False},
        "gemini": {"enabled": False},
        "claude": {"enabled": False},
    }


def test_analyze_request_strips_idea() -> None:
    req = AnalyzeIdeaRequest(
        idea="   Validate this idea   ", ai_providers=valid_providers()
    )
    assert req.idea == "Validate this idea"


def test_only_one_provider_can_be_enabled() -> None:
    with pytest.raises(ValidationError):
        AIProvidersConfig(
            openai={"enabled": True, "model": "gpt-4o-mini", "api_key": "abc"},
            gemini={"enabled": True, "model": "gemini-1.5-flash", "api_key": "def"},
        )


def test_analyze_request_requires_provider_configuration() -> None:
    with pytest.raises(ValidationError):
        AnalyzeIdeaRequest(idea="an idea")


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://resource.openai.azure.com",
        "https://127.0.0.1",
        "https://resource.openai.azure.com:8443",
        "https://user:password@resource.openai.azure.com",
        "https://resource.openai.azure.com/?redirect=http://localhost",
        "https://resource.example.com",
    ],
)
def test_azure_endpoint_is_restricted_to_https_azure_resources(endpoint: str) -> None:
    with pytest.raises(ValidationError):
        AIProvidersConfig(
            azure_openai={
                "enabled": True,
                "model": "deployment",
                "api_key": "abc",
                "endpoint": endpoint,
            }
        )


def test_azure_endpoint_is_normalized() -> None:
    config = AIProvidersConfig(
        azure_openai={
            "enabled": True,
            "model": "deployment",
            "api_key": "abc",
            "endpoint": "HTTPS://Resource.OpenAI.Azure.COM/",
        }
    )
    assert config.azure_openai.endpoint == "https://resource.openai.azure.com"


def test_provider_fields_reject_header_or_path_injection() -> None:
    with pytest.raises(ValidationError):
        AIProvidersConfig(
            openai={
                "enabled": True,
                "model": "gpt\n/4",
                "api_key": "abc\r\nX-Leak: yes",
            }
        )


def test_provider_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AIProvidersConfig(
            openai={
                "enabled": True,
                "model": "gpt-4o-mini",
                "api_key": "abc",
                "url": "http://localhost:1234",
            }
        )
