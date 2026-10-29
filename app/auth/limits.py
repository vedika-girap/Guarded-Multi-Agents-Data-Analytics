from collections import defaultdict, deque
from hashlib import sha256
from math import ceil
from threading import Lock
from time import monotonic
from uuid import uuid4

import tiktoken
from fastapi import HTTPException

try:  # Redis is optional for local development, but installed in deployed builds.
    import redis
    from redis.exceptions import RedisError
except ImportError:  # Keep API imports and local mode usable before optional deps are installed.
    redis = None

    class RedisError(ConnectionError):
        pass

from app.auth.policy import Identity
from app.config import Settings, get_settings

_WINDOW_SECONDS = 60.0
_requests: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()
_redis_clients: dict[tuple[str, float], object] = {}
_redis_lock = Lock()

_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')[2]
  redis.call('PEXPIRE', key, window)
  return {0, math.max(1, math.ceil((tonumber(oldest) + window - now) / 1000))}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window)
return {1, 0}
"""


def _question_tokens(question: str, model: str) -> int:
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(question))


def _redis_client(settings: Settings):
    assert settings.rate_limit_redis_url
    if redis is None:
        raise ImportError("The Redis package is not installed.")
    cache_key = (settings.rate_limit_redis_url, settings.rate_limit_redis_timeout_seconds)
    with _redis_lock:
        client = _redis_clients.get(cache_key)
        if client is None:
            client = redis.Redis.from_url(
                settings.rate_limit_redis_url,
                socket_connect_timeout=settings.rate_limit_redis_timeout_seconds,
                socket_timeout=settings.rate_limit_redis_timeout_seconds,
                decode_responses=True,
            )
            _redis_clients[cache_key] = client
        return client


def _enforce_local_limit(key: str, limit: int) -> None:
    now = monotonic()
    with _lock:
        user_requests = _requests[key]
        while user_requests and now - user_requests[0] >= _WINDOW_SECONDS:
            user_requests.popleft()
        if len(user_requests) >= limit:
            retry_after = max(1, ceil(_WINDOW_SECONDS - (now - user_requests[0])))
            raise HTTPException(
                status_code=429,
                detail={"error_code": "RATE_LIMIT_EXCEEDED", "message": "Request rate limit exceeded."},
                headers={"Retry-After": str(retry_after)},
            )
        user_requests.append(now)


def _enforce_redis_limit(identity: Identity, settings: Settings) -> None:
    # Hash identity fields so user and tenant IDs are not stored in Redis key names.
    digest = sha256(f"{identity.tenant_id}\0{identity.user_id}".encode("utf-8")).hexdigest()
    key = f"analytics:ask:rate:{digest}"
    now_ms = int(__import__("time").time() * 1000)
    try:
        allowed, retry_after = _redis_client(settings).eval(
            _SLIDING_WINDOW_SCRIPT,
            1,
            key,
            now_ms,
            int(_WINDOW_SECONDS * 1000),
            settings.rate_limit_per_minute,
            uuid4().hex,
        )
    except (RedisError, ImportError):
        # A configured shared limiter must fail closed. Silently switching to local
        # counters would allow every replica to grant another full quota.
        raise HTTPException(
            status_code=503,
            detail={"error_code": "RATE_LIMITER_UNAVAILABLE", "message": "Request limits are temporarily unavailable."},
            headers={"Retry-After": "1"},
        ) from None
    if not int(allowed):
        raise HTTPException(
            status_code=429,
            detail={"error_code": "RATE_LIMIT_EXCEEDED", "message": "Request rate limit exceeded."},
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )


def enforce_request_limits(identity: Identity, question: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if _question_tokens(question, settings.gemini_model) > settings.max_question_tokens:
        raise HTTPException(
            status_code=413,
            detail={"error_code": "QUESTION_TOKEN_LIMIT", "message": "The question exceeds the token limit for this environment."},
        )

    if settings.rate_limit_redis_url:
        _enforce_redis_limit(identity, settings)
    else:
        key = f"{identity.tenant_id}:{identity.user_id}"
        _enforce_local_limit(key, settings.rate_limit_per_minute)
