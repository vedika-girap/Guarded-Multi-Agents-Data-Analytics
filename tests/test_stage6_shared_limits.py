from fastapi import HTTPException
from pydantic import SecretStr, ValidationError
import pytest

from app.auth import limits
from app.auth.policy import Identity
from app.config import Settings


def production_settings(**overrides):
    values = {
        "environment": "production",
        "auth_mode": "jwt",
        "auth_jwt_secret": SecretStr("stage-six-test-secret-at-least-32-bytes"),
        "auth_jwt_issuer": "https://issuer.example.test",
        "auth_jwt_audience": "analytics-api",
        "rate_limit_redis_url": "redis://localhost:6379/0",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


class FakeRedis:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def eval(self, *args):
        self.calls.append(args)
        return self.result


def test_production_requires_shared_redis_rate_limiter():
    with pytest.raises(ValidationError, match="RATE_LIMIT_REDIS_URL is required"):
        production_settings(rate_limit_redis_url=None)


def test_shared_rate_limit_uses_atomic_window_and_hashed_identity(monkeypatch):
    fake = FakeRedis([1, 0])
    monkeypatch.setattr(limits, "_redis_client", lambda _: fake)
    monkeypatch.setattr(limits, "_question_tokens", lambda *_: 1)
    identity = Identity(user_id="user-secret", tenant_id="tenant-secret", role="viewer")

    limits.enforce_request_limits(identity, "question", production_settings())

    _, key_count, key, *_ = fake.calls[0]
    assert key_count == 1
    assert key.startswith("analytics:ask:rate:")
    assert "user-secret" not in key and "tenant-secret" not in key


def test_shared_rate_limit_returns_retry_after_when_window_is_full(monkeypatch):
    fake = FakeRedis([0, 23])
    monkeypatch.setattr(limits, "_redis_client", lambda _: fake)
    monkeypatch.setattr(limits, "_question_tokens", lambda *_: 1)

    with pytest.raises(HTTPException) as error:
        limits.enforce_request_limits(
            Identity(user_id="u1", tenant_id="t1", role="viewer"),
            "question",
            production_settings(),
        )

    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "23"


def test_configured_redis_failure_fails_closed(monkeypatch):
    class BrokenRedis:
        def eval(self, *_):
            raise limits.RedisError("private connection detail")

    monkeypatch.setattr(limits, "_redis_client", lambda _: BrokenRedis())
    monkeypatch.setattr(limits, "_question_tokens", lambda *_: 1)

    with pytest.raises(HTTPException) as error:
        limits.enforce_request_limits(
            Identity(user_id="u1", tenant_id="t1", role="viewer"),
            "question",
            production_settings(),
        )

    assert error.value.status_code == 503
    assert error.value.detail["error_code"] == "RATE_LIMITER_UNAVAILABLE"
    assert "private connection detail" not in error.value.detail["message"]
