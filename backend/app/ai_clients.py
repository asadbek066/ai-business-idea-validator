"""Multi-provider AI client with safe JSON parsing."""
import json
import logging
import re
from typing import List, Optional, Tuple
from .prompts import RESPONSE_KEYS, SECTION_LABELS
from .providers import (
    OpenAIProvider,
    AzureOpenAIProvider,
    GeminiProvider,
    ClaudeProvider,
)
from .schemas import AIProvidersConfig

logger = logging.getLogger(__name__)


def _print_raw_ai_output(raw: str) -> None:
    """Print raw AI response for debugging."""
    try:
        logger.debug("[AI raw output] %s", (raw or "")[:2000] + ("..." if len(raw or "") > 2000 else ""))
    except Exception:
        pass


def _extract_balanced_brace_blocks(text: str) -> List[str]:
    """Extract all balanced { ... } JSON blocks. Handles nested braces and strings."""
    if not text or "{" not in text:
        return []
    candidates = []
    i = 0
    while i < len(text):
        start = text.find("{", i)
        if start == -1:
            break
        depth = 0
        in_string = None
        escape = False
        j = start
        while j < len(text):
            c = text[j]
            if escape:
                escape = False
                j += 1
                continue
            if c == "\\" and in_string:
                escape = True
                j += 1
                continue
            if in_string:
                if c == in_string:
                    in_string = None
                j += 1
                continue
            if c in ('"', "'"):
                in_string = c
                j += 1
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : j + 1])
                    break
            j += 1
        i = start + 1
    candidates.sort(key=len, reverse=True)
    return candidates


def _repair_json(s: str) -> str:
    """Apply common fixes for broken LLM JSON."""
    if not s or not s.strip():
        return s
    s = s.strip()
    if s.startswith("\ufeff"):
        s = s[1:]
    s = re.sub(r"^\s+", "", s)
    if not s.startswith("{") and s.strip().startswith('"'):
        s = "{" + s
    if not s.endswith("}") and '"' in s:
        s = s + "}"
    s = re.sub(r",\s*}", "}", s)
    s = re.sub(r",\s*]", "]", s)
    if "'" in s and '"' not in s:
        s = s.replace("'", '"')
    return s


def _safe_json_loads(s: str) -> Optional[dict]:
    """Parse JSON without raising. Returns dict or None."""
    if not s or not s.strip():
        return None
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _parse_json_response(text: str) -> Optional[dict]:
    """Safe JSON extraction. Never raises."""
    if not text or not isinstance(text, str):
        return None
    text = text.strip()
    if not text:
        return None

    result = _safe_json_loads(text)
    if result is not None:
        return result
    
    repaired = _repair_json(text)
    result = _safe_json_loads(repaired)
    if result is not None:
        return result

    for pattern in (r"```(?:json)?\s*([\s\S]*?)```", r"```\s*([\s\S]*?)```"):
        try:
            match = re.search(pattern, text)
            if match:
                raw = match.group(1).strip()
                result = _safe_json_loads(raw)
                if result is not None:
                    return result
                result = _safe_json_loads(_repair_json(raw))
                if result is not None:
                    return result
        except Exception:
            continue

    try:
        candidates = _extract_balanced_brace_blocks(text)
        for candidate in candidates:
            result = _safe_json_loads(candidate)
            if result is not None:
                return result
            result = _safe_json_loads(_repair_json(candidate))
            if result is not None:
                return result
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        result = _safe_json_loads(candidate)
        if result is not None:
            return result
        result = _safe_json_loads(_repair_json(candidate))
        if result is not None:
            return result

    try:
        partial = {}
        for key in RESPONSE_KEYS:
            pattern = rf'"{key}"\s*:\s*"([^"]*(?:\\.[^"]*)*)"'
            match = re.search(pattern, text, re.DOTALL)
            if match:
                partial[key] = match.group(1).replace('\\"', '"').replace('\\n', ' ')
        if len(partial) >= 2:
            return partial
    except Exception:
        pass

    return None


def _normalize_parsed(data: dict) -> dict:
    """Ensure all four keys exist and are non-None strings. Never raises."""
    result = {}
    try:
        for key in RESPONSE_KEYS:
            val = data.get(key) if isinstance(data, dict) else None
            result[key] = str(val).strip() if val is not None else ""
    except Exception:
        result = {k: "" for k in RESPONSE_KEYS}
    return result


def _parse_structured_response_fallback(text: str) -> dict:
    """Fallback: parse by section labels. Never raises."""
    result = {k: "" for k in RESPONSE_KEYS}
    try:
        text = (text or "").strip()
        if not text:
            return result
        if "---SECTION---" in text:
            parts = re.split(r"\s*---SECTION---\s*", text)
            for i, key in enumerate(RESPONSE_KEYS):
                if i < len(parts):
                    result[key] = (parts[i] or "").strip()
            return result
        for key, label in SECTION_LABELS:
            patterns = [
                rf"##\s*{re.escape(label)}\s*\n(.*?)(?=##\s|\Z)",
                rf"SECTION:\s*{re.escape(label)}\s*\n(.*?)(?=SECTION:\s|---SECTION---|\Z)",
                rf"(?i){re.escape(label)}\s*\n(.*?)(?=Market Potential|Risks|First Steps|Verdict|\Z)",
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                if match:
                    result[key] = (match.group(1) or "").strip()
                    break
    except Exception:
        pass
    return result


def _safe_default_response(message: str = "Analysis could not be parsed. Please try again.") -> dict:
    """Return a valid dict with all 4 keys when parsing fails. Never raises."""
    return {k: message for k in RESPONSE_KEYS}


def _extract_and_normalize(raw: str) -> dict:
    """Try JSON first, then section fallback. Always returns a valid dict."""
    try:
        _print_raw_ai_output(raw)
    except Exception:
        pass
    raw = (raw or "").strip()

    try:
        parsed = _parse_json_response(raw)
        if parsed is not None:
            return _normalize_parsed(parsed)
    except Exception:
        pass

    try:
        fallback = _parse_structured_response_fallback(raw)
        if any(fallback.values()):
            return fallback
    except Exception:
        pass

    return _safe_default_response()


async def analyze_idea(idea: str, providers_config: Optional[AIProvidersConfig] = None) -> Tuple[dict, str, Optional[str]]:
    """
    Analyze idea using the single selected provider.
    Returns (result_dict, provider_name_used, fallback_message).
    fallback_message is reserved for API compatibility and is always None.
    """
    if providers_config is None:
        providers_config = AIProvidersConfig()
    idea = (idea or "").strip()
    if not idea:
        raise RuntimeError("Idea text is empty after normalization.")
    
    # Exactly one provider should be enabled (validated by schema).
    primary_provider = None
    primary_name = None
    
    if providers_config.openai.enabled:
        if providers_config.openai.api_key and providers_config.openai.model:
            primary_provider = OpenAIProvider(providers_config.openai.api_key, providers_config.openai.model)
            primary_name = "openai"
        else:
            raise RuntimeError("OpenAI is enabled but missing API key or model.")
    
    elif providers_config.azure_openai.enabled:
        if providers_config.azure_openai.api_key and providers_config.azure_openai.endpoint and providers_config.azure_openai.model:
            primary_provider = AzureOpenAIProvider(
                providers_config.azure_openai.endpoint,
                providers_config.azure_openai.api_key,
                providers_config.azure_openai.model
            )
            primary_name = "azure_openai"
        else:
            raise RuntimeError("Azure OpenAI is enabled but missing API key, endpoint, or model.")
    
    elif providers_config.gemini.enabled:
        if providers_config.gemini.api_key and providers_config.gemini.model:
            primary_provider = GeminiProvider(providers_config.gemini.api_key, providers_config.gemini.model)
            primary_name = "gemini"
        else:
            raise RuntimeError("Gemini is enabled but missing API key or model.")
    
    elif providers_config.claude.enabled:
        if providers_config.claude.api_key and providers_config.claude.model:
            primary_provider = ClaudeProvider(providers_config.claude.api_key, providers_config.claude.model)
            primary_name = "claude"
        else:
            raise RuntimeError("Claude is enabled but missing API key or model.")

    if not primary_provider or not primary_name:
        raise RuntimeError("No AI provider configured. Enable one provider and add model + API key.")

    try:
        logger.info("Trying provider: %s", primary_name)
        raw_response, used_provider = await primary_provider.analyze(idea)
        result = _extract_and_normalize(raw_response)
        logger.info("Provider succeeded: %s", used_provider)
        return result, used_provider, None
    except Exception as e:
        logger.warning("Provider failed (%s): %s: %s", primary_name, type(e).__name__, e)
        raise RuntimeError(f"{primary_name} provider failed: {e}")
