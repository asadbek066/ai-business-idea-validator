"""Multi-provider AI client abstraction."""
import json
import re
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod
import httpx
from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, RESPONSE_KEYS


class AIProvider(ABC):
    """Base class for AI providers."""
    
    @abstractmethod
    async def analyze(self, idea: str) -> tuple[str, str]:
        """
        Analyze business idea. Returns (response_text, provider_name).
        Raises exception on failure.
        """
        pass


class OllamaProvider(AIProvider):
    """Ollama local provider."""
    
    def __init__(self, url: str, model: str):
        self.url = url.rstrip('/')
        self.model = model
    
    async def analyze(self, idea: str) -> tuple[str, str]:
        """Call Ollama API."""
        url = f"{self.url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(idea=idea)},
            ],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        
        message = (data.get("message") or {}).get("content") or ""
        if not message:
            raise ValueError("Empty response from Ollama")
        return message, "ollama"


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
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        
        message = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        if not message:
            raise ValueError("Empty response from OpenAI")
        return message, "openai"


class AzureOpenAIProvider(AIProvider):
    """Azure OpenAI provider."""
    
    def __init__(self, endpoint: str, api_key: str, model: str):
        self.endpoint = endpoint.rstrip('/')
        self.api_key = api_key
        self.model = model
    
    async def analyze(self, idea: str) -> tuple[str, str]:
        """Call Azure OpenAI API."""
        url = f"{self.endpoint}/openai/deployments/{self.model}/chat/completions?api-version=2024-02-15-preview"
        headers = {"api-key": self.api_key}
        payload = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(idea=idea)},
            ],
            "temperature": 0.6,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        
        message = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        if not message:
            raise ValueError("Empty response from Azure OpenAI")
        return message, "azure_openai"


class GeminiProvider(AIProvider):
    """Google Gemini provider."""
    
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
    
    async def analyze(self, idea: str) -> tuple[str, str]:
        """Call Gemini API."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"{SYSTEM_PROMPT}\n\n{USER_PROMPT_TEMPLATE.format(idea=idea)}"
                }]
            }]
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        
        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("No candidates in Gemini response")
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise ValueError("No parts in Gemini response")
        message = parts[0].get("text", "")
        if not message:
            raise ValueError("Empty response from Gemini")
        return message, "gemini"


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
            "messages": [{
                "role": "user",
                "content": f"{SYSTEM_PROMPT}\n\n{USER_PROMPT_TEMPLATE.format(idea=idea)}"
            }]
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        
        content = data.get("content", [])
        if not content:
            raise ValueError("Empty content in Claude response")
        message = content[0].get("text", "")
        if not message:
            raise ValueError("Empty response from Claude")
        return message, "claude"
