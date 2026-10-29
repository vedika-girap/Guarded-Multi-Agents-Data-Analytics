"""Gemini Interactions API adapter with JSON Schema constrained output."""
import json
from functools import lru_cache
from typing import Any

from app.config import get_settings


class GeminiProviderError(RuntimeError):
    """Provider failure with a safe, stable category and no request payload."""

    def __init__(self, category: str, status_code: int | None = None):
        self.category = category
        self.status_code = status_code
        super().__init__(category)


def _normalize_provider_error(error: Exception) -> GeminiProviderError:
    status_code = getattr(error, "code", None)
    if not isinstance(status_code, int):
        status_code = None
    name = type(error).__name__.lower()
    if "timeout" in name or isinstance(error, TimeoutError):
        category = "timeout"
    elif any(token in name for token in ("connect", "network", "protocol")):
        category = "provider_unavailable"
    elif status_code in (401, 403):
        category = "authentication"
    elif status_code == 429:
        category = "rate_limited"
    elif status_code is not None and status_code >= 500:
        category = "provider_unavailable"
    elif status_code is not None and 400 <= status_code < 500:
        category = "request_rejected"
    else:
        category = "provider_error"
    return GeminiProviderError(category, status_code)


def _matches_schema(value: Any, schema: dict) -> bool:
    expected_type = schema.get("type")
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
    }
    if expected_type in checks and not checks[expected_type](value):
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if any(key not in value for key in schema.get("required", [])):
            return False
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            return False
        return all(
            key not in properties or _matches_schema(item, properties[key])
            for key, item in value.items()
        )
    if isinstance(value, list) and "items" in schema:
        return all(_matches_schema(item, schema["items"]) for item in value)
    return True


def enabled() -> bool:
    return get_settings().gemini_api_key is not None


@lru_cache(maxsize=1)
def _client():
    from google import genai

    api_key = get_settings().gemini_api_key
    if api_key is None:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    return genai.Client(api_key=api_key.get_secret_value(), http_options={"timeout": 30_000})


def structured(name: str, schema: dict, instructions: str, input_text: str) -> dict:
    """Return schema-constrained JSON from Gemini."""
    del name  # Gemini response schemas do not use a named-schema parameter.
    settings = get_settings()
    try:
        interaction = _client().interactions.create(
            model=settings.gemini_model,
            system_instruction=instructions,
            input=input_text,
            response_format={"type": "text", "mime_type": "application/json", "schema": schema},
            generation_config={"max_output_tokens": settings.llm_max_output_tokens},
            store=False,
        )
    except GeminiProviderError:
        raise
    except Exception as exc:
        raise _normalize_provider_error(exc) from None
    if not interaction.output_text:
        raise GeminiProviderError("invalid_response")
    try:
        output: Any = json.loads(interaction.output_text)
    except (TypeError, json.JSONDecodeError):
        raise GeminiProviderError("invalid_response") from None
    if not _matches_schema(output, schema):
        raise GeminiProviderError("invalid_response")
    return output
