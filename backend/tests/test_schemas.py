import pytest
from pydantic import ValidationError

from app.schemas import AIProvidersConfig, AnalyzeIdeaRequest


def test_analyze_request_strips_idea() -> None:
    req = AnalyzeIdeaRequest(idea="   Validate this idea   ")
    assert req.idea == "Validate this idea"


def test_only_one_provider_can_be_enabled() -> None:
    with pytest.raises(ValidationError):
        AIProvidersConfig(
            ollama={"enabled": True},
            openai={"enabled": True, "model": "gpt-4o-mini", "api_key": "abc"},
        )
