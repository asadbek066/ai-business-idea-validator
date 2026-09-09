"""Model-output parsing regressions."""

import pytest

from app.ai_clients import _extract_and_normalize


def test_structured_json_is_normalized_and_bounded() -> None:
    result = _extract_and_normalize(
        '{"market_potential":" market ","risks":" risks ",'
        '"first_steps":" steps ","verdict":" verdict "}'
    )
    assert result == {
        "market_potential": "market",
        "risks": "risks",
        "first_steps": "steps",
        "verdict": "verdict",
    }


def test_section_fallback_requires_all_sections() -> None:
    result = _extract_and_normalize(
        "## Market Potential\nmarket\n"
        "## Risks\nrisks\n"
        "## First Steps\nsteps\n"
        "## Verdict\nverdict"
    )
    assert result["verdict"] == "verdict"

    with pytest.raises(ValueError, match="expected analysis format"):
        _extract_and_normalize("## Market Potential\nonly one section")


def test_non_string_fields_are_rejected_instead_of_stringified() -> None:
    with pytest.raises(ValueError, match="expected analysis format"):
        _extract_and_normalize(
            '{"market_potential":[],"risks":"risks",'
            '"first_steps":"steps","verdict":"verdict"}'
        )


def test_model_output_is_truncated_per_field() -> None:
    long_value = "x" * 9_000
    result = _extract_and_normalize(
        f'{{"market_potential":"{long_value}","risks":"risks",'
        '"first_steps":"steps","verdict":"verdict"}'
    )
    assert len(result["market_potential"]) == 8_000
