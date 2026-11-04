"""Gemini embedding adapter shared by indexing and search."""
from functools import lru_cache

from app.config import get_settings


@lru_cache(maxsize=1)
def _client():
    from google import genai

    settings = get_settings()
    key = settings.gemini_api_key
    if key is None:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    timeout_ms = int(settings.demo_request_timeout_seconds * 1000) if settings.demo_mode else 30_000
    return genai.Client(api_key=key.get_secret_value(), http_options={"timeout": timeout_ms})


def embed(text: str, task_type: str, title: str | None = None) -> list[float]:
    from google.genai import types

    result = _client().models.embed_content(
        model=get_settings().gemini_embedding_model,
        contents=text,
        config=types.EmbedContentConfig(task_type=task_type, title=title),
    )
    if not result.embeddings or not result.embeddings[0].values:
        raise ValueError("Gemini returned no embedding")
    return result.embeddings[0].values
