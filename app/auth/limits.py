from collections import defaultdict, deque
from math import ceil
from threading import Lock
from time import monotonic

import tiktoken
from fastapi import HTTPException

from app.auth.policy import Identity
from app.config import Settings, get_settings

_WINDOW_SECONDS = 60.0
_requests: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()


def _question_tokens(question: str, model: str) -> int:
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(question))


def enforce_request_limits(identity: Identity, question: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if _question_tokens(question, settings.openai_model) > settings.max_question_tokens:
        raise HTTPException(
            status_code=413,
            detail={"error_code": "QUESTION_TOKEN_LIMIT", "message": "The question exceeds the token limit for this environment."},
        )

    key = f"{identity.tenant_id}:{identity.user_id}"
    now = monotonic()
    with _lock:
        user_requests = _requests[key]
        while user_requests and now - user_requests[0] >= _WINDOW_SECONDS:
            user_requests.popleft()
        if len(user_requests) >= settings.rate_limit_per_minute:
            retry_after = max(1, ceil(_WINDOW_SECONDS - (now - user_requests[0])))
            raise HTTPException(
                status_code=429,
                detail={"error_code": "RATE_LIMIT_EXCEEDED", "message": "Request rate limit exceeded."},
                headers={"Retry-After": str(retry_after)},
            )
        user_requests.append(now)
