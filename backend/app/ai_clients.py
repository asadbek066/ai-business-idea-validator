"""Provider selection, bounded calls, and fail-closed response parsing."""

import asyncio
import json
import logging
import os
import re
import threading
import weakref
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast

from pydantic import SecretStr

from .prompts import RESPONSE_KEYS, SECTION_LABELS
from .providers import (
    AIProvider,
    AzureOpenAIProvider,
    ClaudeProvider,
    GeminiProvider,
    OpenAIProvider,
    ProviderBusyError,
    ProviderConfigurationError,
    ProviderError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from .schemas import MAX_RESPONSE_FIELD_CHARS, AIProvidersConfig

logger = logging.getLogger(__name__)
T = TypeVar("T")


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


PROVIDER_CONCURRENCY_LIMIT = _bounded_int(
    "PROVIDER_CONCURRENCY_LIMIT", default=4, minimum=1, maximum=32
)
PROVIDER_QUEUE_TIMEOUT_SECONDS = _bounded_float(
    "PROVIDER_QUEUE_TIMEOUT_SECONDS", default=3.0, minimum=0.1, maximum=30.0
)
ANALYZE_DEADLINE_SECONDS = _bounded_float(
    "ANALYZE_DEADLINE_SECONDS", default=75.0, minimum=5.0, maximum=180.0
)
VALIDATE_DEADLINE_SECONDS = _bounded_float(
    "VALIDATE_DEADLINE_SECONDS", default=12.0, minimum=3.0, maximum=60.0
)


class ProviderCallGate:
    """Bound in-flight provider work per event loop without unbounded queuing."""

    def __init__(self, limit: int):
        self.limit = max(1, limit)
        self._semaphores: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, asyncio.Semaphore
        ] = weakref.WeakKeyDictionary()
        self._lock = threading.Lock()

    def _semaphore_for_loop(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        with self._lock:
            semaphore = self._semaphores.get(loop)
            if semaphore is None:
                semaphore = asyncio.Semaphore(self.limit)
                self._semaphores[loop] = semaphore
            return semaphore

    async def run(
        self,
        call: Callable[[], Awaitable[T]],
        provider_name: str,
        deadline_seconds: float,
    ) -> T:
        semaphore = self._semaphore_for_loop()
        acquired = False
        try:
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout=PROVIDER_QUEUE_TIMEOUT_SECONDS)
                acquired = True
            except asyncio.TimeoutError as error:
                raise ProviderBusyError(provider_name) from error

            try:
                return await asyncio.wait_for(call(), timeout=deadline_seconds)
            except asyncio.TimeoutError as error:
                raise ProviderTimeoutError(provider_name) from error
        finally:
            if acquired:
                semaphore.release()


PROVIDER_CALL_GATE = ProviderCallGate(PROVIDER_CONCURRENCY_LIMIT)


class InvalidAnalysisResponse(ValueError):
    """The model response did not satisfy the application result contract."""


def _extract_balanced_brace_blocks(text: str) -> list[str]:
    """Extract balanced object candidates in one bounded pass.

    The old implementation restarted a scan at every opening brace, making
    malformed brace-heavy output quadratic. Provider responses are already
    byte-bounded, and this scanner is deliberately single-pass so malformed
    output cannot monopolize the event loop.
    """

    if not text or "{" not in text:
        return []

    candidates: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if start is None:
            if char == "{":
                start = index
                depth = 1
                in_string = False
                escaped = False
            continue

        if escaped:
            escaped = False
            continue
        if in_string:
            if char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidates.append(text[start : index + 1])
                if len(candidates) >= 4:
                    break
                start = None

    return candidates


def _safe_json_loads(text: str) -> dict[str, object] | None:
    if not text or not text.strip():
        return None
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _parse_json_response(text: str) -> dict[str, object] | None:
    """Accept strict JSON, fenced JSON, or a strict embedded object."""

    parsed = _safe_json_loads(text)
    if parsed is not None:
        return parsed

    for marker in ("```json", "```"):
        start = text.lower().find(marker)
        if start == -1:
            continue
        start += len(marker)
        end = text.find("```", start)
        if end == -1:
            continue
        parsed = _safe_json_loads(text[start:end].strip())
        if parsed is not None:
            return parsed

    for candidate in _extract_balanced_brace_blocks(text):
        parsed = _safe_json_loads(candidate)
        if parsed is not None:
            return parsed
    return None


def _normalize_parsed(data: object) -> dict[str, str] | None:
    """Require every result field to be a bounded, non-empty string."""

    if not isinstance(data, dict):
        return None
    result: dict[str, str] = {}
    for key in RESPONSE_KEYS:
        value = data.get(key)
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        if not cleaned or len(cleaned) > MAX_RESPONSE_FIELD_CHARS:
            return None
        result[key] = cleaned
    return result


def _parse_structured_response_fallback(text: str) -> dict[str, str]:
    """Parse the documented section format for providers that ignore JSON."""

    result = {key: "" for key in RESPONSE_KEYS}
    text = text.strip()
    if not text:
        return result

    if "---SECTION---" in text:
        parts = [part.strip() for part in text.split("---SECTION---")]
        for index, key in enumerate(RESPONSE_KEYS):
            if index < len(parts):
                result[key] = parts[index]
        return result

    for key, label in SECTION_LABELS:
        patterns = (
            rf"##\s*{label}\s*\n(.*?)(?=##\s|\Z)",
            rf"SECTION:\s*{label}\s*\n(.*?)(?=SECTION:\s|---SECTION---|\Z)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                result[key] = match.group(1).strip()
                break
    return result


def _extract_and_normalize(raw: str) -> dict[str, str]:
    """Return a valid analysis or fail closed with ``InvalidAnalysisResponse``."""

    if not isinstance(raw, str):
        raise InvalidAnalysisResponse(
            "Provider response did not match the expected analysis format."
        )
    text = raw.strip()
    parsed = _normalize_parsed(_parse_json_response(text))
    if parsed is not None:
        return parsed

    fallback = _normalize_parsed(_parse_structured_response_fallback(text))
    if fallback is not None:
        return fallback
    raise InvalidAnalysisResponse("Provider response did not match the expected analysis format.")


async def _run_provider_call(
    call: Callable[[], Awaitable[T]], provider_name: str, deadline_seconds: float
) -> T:
    return await PROVIDER_CALL_GATE.run(call, provider_name, deadline_seconds)


def _selected_api_key(config: object) -> str | None:
    value = getattr(config, "api_key", None)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return None


def _get_selected_provider(
    providers_config: AIProvidersConfig,
) -> tuple[AIProvider, str]:
    configurations = (
        (providers_config.openai, "openai"),
        (providers_config.azure_openai, "azure_openai"),
        (providers_config.gemini, "gemini"),
        (providers_config.claude, "claude"),
    )
    for config, name in configurations:
        if not config.enabled:
            continue
        api_key = _selected_api_key(config)
        if name == "openai" and api_key and config.model:
            return OpenAIProvider(api_key, config.model), name
        if name == "azure_openai" and api_key and config.endpoint and config.model:
            return AzureOpenAIProvider(config.endpoint, api_key, config.model), name
        if name == "gemini" and api_key and config.model:
            return GeminiProvider(api_key, config.model), name
        if name == "claude" and api_key and config.model:
            return ClaudeProvider(api_key, config.model), name
        raise ProviderConfigurationError(name)
    raise ProviderConfigurationError("provider")


async def analyze_idea(
    idea: str, providers_config: AIProvidersConfig | None = None
) -> tuple[dict[str, str], str, str | None]:
    """Analyze using the selected provider; never return a fake result."""

    if providers_config is None:
        raise ProviderConfigurationError("provider")
    if not isinstance(idea, str):
        raise ProviderConfigurationError("provider")
    normalized_idea = idea.strip()
    if not normalized_idea:
        raise ProviderConfigurationError("provider")

    provider, provider_name = _get_selected_provider(providers_config)
    logger.info("Starting provider analysis: %s", provider_name)
    try:
        raw_response, used_provider = await _run_provider_call(
            lambda: provider.analyze(normalized_idea),
            provider_name,
            ANALYZE_DEADLINE_SECONDS,
        )
    except ProviderError:
        logger.warning("Provider analysis failed: %s", provider_name)
        raise
    except Exception as error:
        logger.warning("Provider analysis failed: %s (%s)", provider_name, type(error).__name__)
        raise ProviderRequestError(provider_name) from None

    try:
        result = _extract_and_normalize(raw_response)
    except InvalidAnalysisResponse:
        logger.warning("Provider returned invalid analysis format: %s", provider_name)
        raise ProviderResponseError(provider_name) from None
    logger.info("Provider analysis succeeded: %s", used_provider)
    return result, used_provider, None


async def validate_provider(
    providers_config: AIProvidersConfig | None = None,
) -> tuple[bool, str]:
    """Validate the selected provider with a bounded, minimal request."""

    if providers_config is None:
        raise ProviderConfigurationError("provider")
    provider, provider_name = _get_selected_provider(providers_config)
    try:
        ok, used_provider = await _run_provider_call(
            provider.validate, provider_name, VALIDATE_DEADLINE_SECONDS
        )
    except ProviderError:
        logger.warning("Provider validation failed: %s", provider_name)
        raise
    except Exception as error:
        logger.warning(
            "Provider validation failed: %s (%s)",
            provider_name,
            type(error).__name__,
        )
        raise ProviderRequestError(provider_name) from None
    if not ok:
        raise ProviderResponseError(provider_name)
    return True, used_provider or provider_name
