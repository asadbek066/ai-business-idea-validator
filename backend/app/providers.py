"""Multi-provider AI client abstraction."""

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import quote

import httpx

from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)
HTTP_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
MAX_PROVIDER_RESPONSE_BYTES = 256 * 1024
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class AIProvider(ABC):
    """Base class for AI providers."""

    @abstractmethod
    async def analyze(self, idea: str) -> tuple[str, str]:
        """
        Analyze business idea. Returns (response_text, provider_name).
        Raises exception on failure.
        """
        raise NotImplementedError

    @abstractmethod
    async def validate(self) -> tuple[bool, str]:
        """
        Validate provider credentials/connectivity quickly.
        Returns (is_valid, provider_name). Raises on failure.
        """
        raise NotImplementedError

    async def _post_json_with_retry(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 60.0,
        retries: int = 2,
        provider_name: str = "provider",
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        timeout = httpx.Timeout(timeout_seconds)
        async with httpx.AsyncClient(
            timeout=timeout,
            limits=HTTP_LIMITS,
            follow_redirects=False,
        ) as client:
            for attempt in range(retries + 1):
                try:
                    async with client.stream(
                        "POST", url, json=payload, headers=headers
                    ) as resp:
                        resp.raise_for_status()
                        content_length = resp.headers.get("content-length")
                        if (
                            content_length
                            and int(content_length) > MAX_PROVIDER_RESPONSE_BYTES
                        ):
                            raise ValueError(
                                "Provider response exceeded the size limit."
                            )
                        chunks: list[bytes] = []
                        total_bytes = 0
                        async for chunk in resp.aiter_bytes():
                            total_bytes += len(chunk)
                            if total_bytes > MAX_PROVIDER_RESPONSE_BYTES:
                                raise ValueError(
                                    "Provider response exceeded the size limit."
                                )
                            chunks.append(chunk)
                    data = json.loads(b"".join(chunks))
                    if not isinstance(data, dict):
                        raise TypeError("Provider returned non-object JSON.")
                    return data
                except httpx.HTTPStatusError as error:
                    last_error = error
                    if error.response.status_code not in RETRYABLE_STATUS_CODES:
                        break
                    if attempt < retries:
                        logger.warning(
                            "%s request failed (attempt %s/%s): HTTPStatusError",
                            provider_name,
                            attempt + 1,
                            retries + 1,
                        )
                        await asyncio.sleep(0.4 * (attempt + 1))
                except (httpx.RequestError, TypeError, ValueError) as error:
                    last_error = error
                    if attempt < retries:
                        logger.warning(
                            "%s request failed (attempt %s/%s): %s",
                            provider_name,
                            attempt + 1,
                            retries + 1,
                            type(error).__name__,
                        )
                        await asyncio.sleep(0.4 * (attempt + 1))

        logger.warning(
            "%s request failed after %s attempts: %s",
            provider_name,
            retries + 1,
            type(last_error).__name__ if last_error else "unknown",
        )
        raise RuntimeError(f"{provider_name} request failed")


class OpenAIProvider(AIProvider):
    """OpenAI provider."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def analyze(self, idea: str) -> tuple[str, str]:
        """Call OpenAI API."""
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(idea=idea)},
            ],
            "temperature": 0.6,
        }
        data = await self._post_json_with_retry(
            url=url,
            payload=payload,
            headers=headers,
            timeout_seconds=60.0,
            retries=1,
            provider_name="OpenAI",
        )

        choices = data.get("choices")
        message = ""
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            model_message = choices[0].get("message")
            if isinstance(model_message, dict) and isinstance(
                model_message.get("content"), str
            ):
                message = model_message["content"].strip()
        if not message:
            raise ValueError("Empty response from OpenAI")
        return message, "openai"

    async def validate(self) -> tuple[bool, str]:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
        }
        await self._post_json_with_retry(
            url=url,
            payload=payload,
            headers=headers,
            timeout_seconds=5.0,
            retries=0,
            provider_name="OpenAI",
        )
        return True, "openai"


class AzureOpenAIProvider(AIProvider):
    """Azure OpenAI provider."""

    def __init__(
        self, endpoint: str, api_key: str, model: str, api_version: str | None = None
    ):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.api_version = (
            (api_version or "").strip()
            or os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview").strip()
            or "2025-01-01-preview"
        )

    async def analyze(self, idea: str) -> tuple[str, str]:
        """Call Azure OpenAI API."""
        url = (
            f"{self.endpoint}/openai/deployments/{quote(self.model, safe='-._~')}/chat/completions"
            f"?api-version={quote(self.api_version, safe='-._~')}"
        )
        headers = {"api-key": self.api_key}
        payload = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(idea=idea)},
            ],
            "temperature": 0.6,
        }
        data = await self._post_json_with_retry(
            url=url,
            payload=payload,
            headers=headers,
            timeout_seconds=60.0,
            retries=1,
            provider_name="Azure OpenAI",
        )

        choices = data.get("choices")
        message = ""
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            model_message = choices[0].get("message")
            if isinstance(model_message, dict) and isinstance(
                model_message.get("content"), str
            ):
                message = model_message["content"].strip()
        if not message:
            raise ValueError("Empty response from Azure OpenAI")
        return message, "azure_openai"

    async def validate(self) -> tuple[bool, str]:
        url = (
            f"{self.endpoint}/openai/deployments/{quote(self.model, safe='-._~')}/chat/completions"
            f"?api-version={quote(self.api_version, safe='-._~')}"
        )
        headers = {"api-key": self.api_key}
        payload = {
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
        }
        await self._post_json_with_retry(
            url=url,
            payload=payload,
            headers=headers,
            timeout_seconds=6.0,
            retries=0,
            provider_name="Azure OpenAI",
        )
        return True, "azure_openai"


class GeminiProvider(AIProvider):
    """Google Gemini provider."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def analyze(self, idea: str) -> tuple[str, str]:
        """Call Gemini API."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(self.model, safe='-._~')}:generateContent"
        headers = {"x-goog-api-key": self.api_key}
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": f"{SYSTEM_PROMPT}\n\n{USER_PROMPT_TEMPLATE.format(idea=idea)}"
                        }
                    ]
                }
            ]
        }
        data = await self._post_json_with_retry(
            url=url,
            payload=payload,
            headers=headers,
            timeout_seconds=60.0,
            retries=1,
            provider_name="Gemini",
        )

        candidates = data.get("candidates", [])
        if (
            not isinstance(candidates, list)
            or not candidates
            or not isinstance(candidates[0], dict)
        ):
            raise ValueError("No candidates in Gemini response")
        content = candidates[0].get("content")
        parts = content.get("parts", []) if isinstance(content, dict) else []
        if not isinstance(parts, list) or not parts or not isinstance(parts[0], dict):
            raise ValueError("No parts in Gemini response")
        message = parts[0].get("text", "")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Empty response from Gemini")
        return message.strip(), "gemini"

    async def validate(self) -> tuple[bool, str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(self.model, safe='-._~')}:generateContent"
        headers = {"x-goog-api-key": self.api_key}
        payload = {"contents": [{"parts": [{"text": "ping"}]}]}
        await self._post_json_with_retry(
            url=url,
            payload=payload,
            headers=headers,
            timeout_seconds=6.0,
            retries=0,
            provider_name="Gemini",
        )
        return True, "gemini"


class ClaudeProvider(AIProvider):
    """Anthropic Claude provider."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def analyze(self, idea: str) -> tuple[str, str]:
        """Call Claude API."""
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 2000,
            "messages": [
                {
                    "role": "user",
                    "content": f"{SYSTEM_PROMPT}\n\n{USER_PROMPT_TEMPLATE.format(idea=idea)}",
                }
            ],
        }
        data = await self._post_json_with_retry(
            url=url,
            payload=payload,
            headers=headers,
            timeout_seconds=60.0,
            retries=1,
            provider_name="Claude",
        )

        content = data.get("content", [])
        if (
            not isinstance(content, list)
            or not content
            or not isinstance(content[0], dict)
        ):
            raise ValueError("Empty content in Claude response")
        message = content[0].get("text", "")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Empty response from Claude")
        return message.strip(), "claude"

    async def validate(self) -> tuple[bool, str]:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}],
        }
        await self._post_json_with_retry(
            url=url,
            payload=payload,
            headers=headers,
            timeout_seconds=6.0,
            retries=0,
            provider_name="Claude",
        )
        return True, "claude"
