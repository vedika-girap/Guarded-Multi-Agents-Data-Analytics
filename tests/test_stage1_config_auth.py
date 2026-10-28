from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from app.auth.policy import DEV_IDENTITY, resolve_identity
from app.config import Settings

JWT_SECRET = "stage-one-test-secret-which-is-at-least-32-bytes"
ISSUER = "https://identity.example.test/"
AUDIENCE = "analytics-api"


def jwt_settings(**overrides) -> Settings:
    values = {
        "environment": "staging",
        "auth_mode": "jwt",
        "auth_jwt_secret": SecretStr(JWT_SECRET),
        "auth_jwt_issuer": ISSUER,
        "auth_jwt_audience": AUDIENCE,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def make_token(secret: str = JWT_SECRET, *, role: str = "analyst", expires: datetime | None = None) -> str:
    return jwt.encode(
        {
            "sub": "user-123",
            "tenant_id": "tenant-abc",
            "role": role,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": expires or (datetime.now(timezone.utc) + timedelta(minutes=5)),
        },
        secret,
        algorithm="HS256",
    )


def test_jwt_mode_reports_all_missing_configuration_together():
    with pytest.raises(ValidationError) as error:
        Settings(auth_mode="jwt", environment="staging", _env_file=None)
    message = str(error.value)
    assert "AUTH_JWT_SECRET" in message
    assert "AUTH_JWT_ISSUER" in message
    assert "AUTH_JWT_AUDIENCE" in message


def test_process_environment_overrides_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ENVIRONMENT=staging\nOPENAI_MODEL=dotenv-model\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_MODEL", "process-model")
    settings = Settings(_env_file=env_file)
    assert settings.environment == "staging"
    assert settings.openai_model == "process-model"


def test_dev_auth_returns_fixed_viewer_and_ignores_role_escalation_header():
    settings = Settings(environment="development", auth_mode="dev", _env_file=None)
    identity = resolve_identity(None, settings, x_role="admin")
    assert identity == DEV_IDENTITY
    assert identity.role == "viewer"


def test_jwt_verified_role_cannot_be_overridden_by_x_role_header():
    settings = jwt_settings()
    identity = resolve_identity(f"Bearer {make_token(role='viewer')}", settings, x_role="admin")
    assert identity.role == "viewer"
    assert identity.user_id == "user-123"
    assert identity.tenant_id == "tenant-abc"


def test_missing_bearer_token_is_401():
    with pytest.raises(HTTPException) as error:
        resolve_identity(None, jwt_settings())
    assert error.value.status_code == 401
    assert error.value.detail["error_code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.parametrize("token", ["not-a-jwt", make_token(secret="forged-signature-key-not-the-configured-secret")])
def test_bad_or_forged_token_is_401(token):
    with pytest.raises(HTTPException) as error:
        resolve_identity(f"Bearer {token}", jwt_settings())
    assert error.value.status_code == 401
    assert error.value.detail["error_code"] == "INVALID_TOKEN"


def test_expired_token_is_401():
    expired = make_token(expires=datetime.now(timezone.utc) - timedelta(minutes=1))
    with pytest.raises(HTTPException) as error:
        resolve_identity(f"Bearer {expired}", jwt_settings())
    assert error.value.status_code == 401
    assert error.value.detail["error_code"] == "TOKEN_EXPIRED"


def test_development_auth_is_rejected_in_production():
    with pytest.raises(ValidationError, match="AUTH_MODE=dev is forbidden"):
        Settings(environment="production", auth_mode="dev", _env_file=None)
