"""Small OpenAI Responses API adapter. No client is created without a configured key."""
import json
from functools import lru_cache

from app.config import get_settings


def enabled() -> bool:
    return get_settings().openai_api_key is not None


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI

    api_key = get_settings().openai_api_key
    if api_key is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=api_key.get_secret_value(), timeout=30.0, max_retries=1)


def structured(name: str, schema: dict, instructions: str, input_text: str) -> dict:
    """Return schema-constrained JSON from the configured model."""
    settings = get_settings()
    response = _client().responses.create(
        model=settings.openai_model,
        instructions=instructions,
        input=input_text,
        text={"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
        max_output_tokens=settings.llm_max_output_tokens,
    )
    if not response.output_text:
        raise ValueError("The model returned no text output")
    return json.loads(response.output_text)
