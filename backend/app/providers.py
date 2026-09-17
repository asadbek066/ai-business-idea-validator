"""Provider HTTP clients with bounded, non-sensitive failure semantics."""

import asyncio
import json
import logging
import os
import re
import socket
import threading
import weakref
from abc import ABC, abstractmethod
from collections.abc import Mapping
from ipaddress import ip_address
from typing import Any, cast
from urllib.parse import quote

import httpx

from .prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)

HTTP_LIMITS = httpx.Limits(max_connections=4, max_keepalive_connections=2)
MAX_PROVIDER_RESPONSE_BYTES = 256 * 1024
MAX_OUTPUT_TOKENS = 1_200
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
MAX_RETRY_AFTER_SECONDS = 5.0
DEFAULT_AZURE_API_VERSION = "2025-01-01-preview"
AZURE_DNS_TIMEOUT_SECONDS = 2.0

_HTTP_CLIENTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient] = (
    weakref.WeakKeyDictionary()
)
_HTTP_CLIENTS_LOCK = threading.Lock()


def _get_http_client() -> httpx.AsyncClient:
    """Return one connection pool per event loop for connection reuse."""

    loop = asyncio.get_running_loop()
    with _HTTP_CLIENTS_LOCK:
        client = _HTTP_CLIENTS.get(loop)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(
                limits=HTTP_LIMITS,
                follow_redirects=False,
                trust_env=False,
            )
            _HTTP_CLIENTS[loop] = client
        return client


async def close_http_clients() -> None:
    """Close all loop-local pools during application shutdown."""

    with _HTTP_CLIENTS_LOCK:
        clients = list(_HTTP_CLIENTS.values())
        _HTTP_CLIENTS.clear()
    if clients:
        await asyncio.gather(*(client.aclose() for client in clients))


class ProviderError(RuntimeError):
    """Base class whose string representation never contains provider data."""

    def __init__(self, provider_name: str):
        self.provider_name = provider_name
        super().__init__(f"{provider_name} request failed")


class ProviderRequestError(ProviderError):
    """The provider could not complete the HTTP request."""

    def __init__(
        self,
        provider_name: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ):
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(provider_name)


class ProviderTimeoutError(ProviderRequestError):
    """The bounded end-to-end provider deadline elapsed."""

    def __init__(self, provider_name: str):
        super().__init__(provider_name, retryable=True)


class ProviderBusyError(ProviderRequestError):
    """The process-wide provider capacity queue is full."""

    def __init__(self, provider_name: str):
        super().__init__(provider_name, retryable=True)


class ProviderResponseError(ProviderError):
    """The provider returned a successful HTTP response we cannot trust."""

    def __init__(self, provider_name: str):
        super().__init__(provider_name)


class ProviderConfigurationError(ProviderError):
    """The selected provider configuration is incomplete or unsafe."""

    def __init__(self, provider_name: str):
        super().__init__(provider_name)


def _bounded_positive_float(value: str | None, default: float, maximum: float) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum)


PROVIDER_REQUEST_TIMEOUT_SECONDS = _bounded_positive_float(
    os.getenv("PROVIDER_REQUEST_TIMEOUT_SECONDS"), default=60.0, maximum=120.0
)


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


async def _assert_public_azure_endpoint(endpoint: str) -> None:
    """Reject Azure hosts that resolve to non-global addresses.

    The schema allowlist prevents arbitrary hostnames. This second check
    protects the server from local DNS, private-link surprises, and metadata
    destinations before a caller's API key is sent. Deployment egress policy
    remains the final defense against DNS rebinding and is documented.
    """

    try:
        hostname = endpoint.split("://", 1)[1].split("/", 1)[0]
        infos = await asyncio.wait_for(
            asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                443,
                0,
                socket.SOCK_STREAM,
            ),
            timeout=AZURE_DNS_TIMEOUT_SECONDS,
        )
    except (OSError, ValueError, asyncio.TimeoutError):
        raise ProviderRequestError("Azure OpenAI") from None

    addresses: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        if isinstance(sockaddr, tuple) and sockaddr and isinstance(sockaddr[0], str):
            addresses.add(sockaddr[0])
    if not addresses:
        raise ProviderRequestError("Azure OpenAI")

    try:
        if any(not ip_address(address).is_global for address in addresses):
            raise ProviderConfigurationError("Azure OpenAI")
    except ValueError:
        raise ProviderRequestError("Azure OpenAI") from None


def _provider_text(data: object, provider_name: str, *path: str) -> str:
    current: object = data
    for key in path:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and key.isdecimal():
            index = int(key)
            current = current[index] if index < len(current) else None
        else:
            raise ProviderResponseError(provider_name)
    if not isinstance(current, str) or not current.strip():
        raise ProviderResponseError(provider_name)
    return current.strip()


def _provider_list(data: object, provider_name: str, key: str) -> list[object]:
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise ProviderResponseError(provider_name)
    values = cast(list[object], data[key])
    if not values:
        raise ProviderResponseError(provider_name)
    return values


class AIProvider(ABC):
    """Base class for one selected provider."""

    provider_name = "provider"

    @abstractmethod
    async def analyze(self, idea: str) -> tuple[str, str]:
        """Analyze an idea and return raw provider text plus its name."""
        raise NotImplementedError

    @abstractmethod
    async def validate(self) -> tuple[bool, str]:
        """Validate credentials/connectivity and return the provider name."""
        raise NotImplementedError

    async def _post_json_with_retry(
        self,
        url: str,
        payload: dict[str, Any],
        headers: Mapping[str, str] | None = None,
        *,
        params: Mapping[str, str] | None = None,
        timeout_seconds: float = PROVIDER_REQUEST_TIMEOUT_SECONDS,
        retries: int = 0,
        provider_name: str | None = None,
    ) -> dict[str, Any]:
        """POST bounded JSON without exposing request or provider content.

        The public analysis methods deliberately use zero retries: a timed-out
        POST may have been accepted and billed upstream, so retrying it would
        create an ambiguous duplicate charge. The helper still supports a
        caller-selected retry count for operations proven safe by that caller.
        """

        name = provider_name or self.provider_name
        retry_count = max(0, min(int(retries), 2))
        timeout = httpx.Timeout(
            connect=min(timeout_seconds, 10.0),
            read=timeout_seconds,
            write=min(timeout_seconds, 30.0),
            pool=5.0,
        )
        last_request_error: ProviderRequestError | None = None

        client = _get_http_client()
        for attempt in range(retry_count + 1):
            try:
                async with client.stream(
                    "POST",
                    url,
                    params=params,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                ) as response:
                    status_code = response.status_code
                    if not 200 <= status_code < 300:
                        retryable = status_code in RETRYABLE_STATUS_CODES
                        error = ProviderRequestError(
                            name,
                            status_code=status_code,
                            retryable=retryable,
                        )
                        if retryable and attempt < retry_count:
                            last_request_error = error
                            await self._wait_before_retry(
                                response.headers.get("retry-after"), attempt
                            )
                            continue
                        raise error

                    raw_body = await self._read_response_body(response, name)

                try:
                    parsed = json.loads(raw_body)
                except (json.JSONDecodeError, TypeError, ValueError):
                    logger.warning("%s returned invalid JSON", name)
                    raise ProviderResponseError(name) from None
                if not isinstance(parsed, dict):
                    raise ProviderResponseError(name)
                return parsed
            except ProviderError:
                raise
            except httpx.RequestError as error:
                request_error = ProviderRequestError(name, retryable=True)
                if attempt < retry_count:
                    last_request_error = request_error
                    logger.warning(
                        "%s request failed (attempt %s/%s): %s",
                        name,
                        attempt + 1,
                        retry_count + 1,
                        type(error).__name__,
                    )
                    await self._wait_before_retry(None, attempt)
                    continue
                raise request_error from None

        if last_request_error is not None:
            raise last_request_error
        raise ProviderRequestError(name)

    @staticmethod
    async def _wait_before_retry(retry_after: str | None, attempt: int) -> None:
        delay = _retry_after_seconds(retry_after)
        if delay is None:
            delay = min(0.4 * (attempt + 1), MAX_RETRY_AFTER_SECONDS)
        await asyncio.sleep(delay)

    @staticmethod
    async def _read_response_body(response: httpx.Response, provider_name: str) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                raise ProviderResponseError(provider_name) from None
            if declared_length < 0 or declared_length > MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderResponseError(provider_name)

        chunks = bytearray()
        async for chunk in response.aiter_bytes():
            chunks.extend(chunk)
            if len(chunks) > MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderResponseError(provider_name)
        return bytes(chunks)


class OpenAIProvider(AIProvider):
    """OpenAI Chat Completions provider."""

    provider_name = "OpenAI"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def analyze(self, idea: str) -> tuple[str, str]:
        data = await self._post_json_with_retry(
            url="https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            payload={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(idea)},
                ],
                "temperature": 0.6,
                "max_tokens": MAX_OUTPUT_TOKENS,
            },
            provider_name=self.provider_name,
        )
        choices = _provider_list(data, self.provider_name, "choices")
        return _provider_text(choices[0], self.provider_name, "message", "content"), "openai"

    async def validate(self) -> tuple[bool, str]:
        data = await self._post_json_with_retry(
            url="https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            payload={
                "model": self.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
            },
            timeout_seconds=8.0,
            provider_name=self.provider_name,
        )
        choices = _provider_list(data, self.provider_name, "choices")
        _provider_text(choices[0], self.provider_name, "message", "content")
        return True, "openai"


class AzureOpenAIProvider(AIProvider):
    """Azure OpenAI deployment-based Chat Completions provider."""

    provider_name = "Azure OpenAI"

    def __init__(self, endpoint: str, api_key: str, model: str, api_version: str | None = None):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        configured_version = (
            (api_version or "").strip()
            or os.getenv("AZURE_OPENAI_API_VERSION", DEFAULT_AZURE_API_VERSION).strip()
            or DEFAULT_AZURE_API_VERSION
        )
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", configured_version):
            raise ProviderConfigurationError(self.provider_name)
        self.api_version = configured_version

    def _url(self) -> str:
        return (
            f"{self.endpoint}/openai/deployments/{quote(self.model, safe='-._~')}/chat/completions"
        )

    async def analyze(self, idea: str) -> tuple[str, str]:
        await _assert_public_azure_endpoint(self.endpoint)
        data = await self._post_json_with_retry(
            url=self._url(),
            params={"api-version": self.api_version},
            headers={"api-key": self.api_key},
            payload={
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(idea)},
                ],
                "temperature": 0.6,
                "max_tokens": MAX_OUTPUT_TOKENS,
            },
            provider_name=self.provider_name,
        )
        choices = _provider_list(data, self.provider_name, "choices")
        return (
            _provider_text(choices[0], self.provider_name, "message", "content"),
            "azure_openai",
        )

    async def validate(self) -> tuple[bool, str]:
        await _assert_public_azure_endpoint(self.endpoint)
        data = await self._post_json_with_retry(
            url=self._url(),
            params={"api-version": self.api_version},
            headers={"api-key": self.api_key},
            payload={
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
            },
            timeout_seconds=8.0,
            provider_name=self.provider_name,
        )
        choices = _provider_list(data, self.provider_name, "choices")
        _provider_text(choices[0], self.provider_name, "message", "content")
        return True, "azure_openai"


class GeminiProvider(AIProvider):
    """Google Gemini GenerateContent provider."""

    provider_name = "Gemini"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def _url(self) -> str:
        return (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(self.model, safe='-._~')}:generateContent"
        )

    def _payload(
        self,
        text: str,
        *,
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
        response_mime_type: str | None = "application/json",
    ) -> dict[str, Any]:
        generation_config: dict[str, Any] = {"maxOutputTokens": max_output_tokens}
        if response_mime_type is not None:
            generation_config["responseMimeType"] = response_mime_type
        return {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": generation_config,
        }

    async def analyze(self, idea: str) -> tuple[str, str]:
        data = await self._post_json_with_retry(
            url=self._url(),
            headers={"x-goog-api-key": self.api_key},
            payload=self._payload(build_user_prompt(idea)),
            provider_name=self.provider_name,
        )
        candidates = _provider_list(data, self.provider_name, "candidates")
        return (
            _provider_text(candidates[0], self.provider_name, "content", "parts", "0", "text"),
            "gemini",
        )

    async def validate(self) -> tuple[bool, str]:
        data = await self._post_json_with_retry(
            url=self._url(),
            headers={"x-goog-api-key": self.api_key},
            payload=self._payload("ping", max_output_tokens=1, response_mime_type=None),
            timeout_seconds=8.0,
            provider_name=self.provider_name,
        )
        candidates = _provider_list(data, self.provider_name, "candidates")
        _provider_text(candidates[0], self.provider_name, "content", "parts", "0", "text")
        return True, "gemini"


class ClaudeProvider(AIProvider):
    """Anthropic Messages API provider."""

    provider_name = "Claude"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def _payload(self, text: str, max_tokens: int) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": text}],
        }

    async def analyze(self, idea: str) -> tuple[str, str]:
        data = await self._post_json_with_retry(
            url="https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            payload=self._payload(build_user_prompt(idea), MAX_OUTPUT_TOKENS),
            provider_name=self.provider_name,
        )
        content = _provider_list(data, self.provider_name, "content")
        return _provider_text(content[0], self.provider_name, "text"), "claude"

    async def validate(self) -> tuple[bool, str]:
        data = await self._post_json_with_retry(
            url="https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            payload=self._payload("ping", 1),
            timeout_seconds=8.0,
            provider_name=self.provider_name,
        )
        content = _provider_list(data, self.provider_name, "content")
        _provider_text(content[0], self.provider_name, "text")
        return True, "claude"
